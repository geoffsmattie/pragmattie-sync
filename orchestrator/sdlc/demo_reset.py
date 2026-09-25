"""Put the demo back to a clean start: the repository as it was at the baseline, fresh history.

Every demo leaves residue on GitHub: issues opened live, labels the agents applied, demo PRs and
their branches, the agents' comments. GitHub can't delete an issue, only close it, so "exactly as
it was" isn't possible; this gets as close as the API allows, and says what it left behind.

The baseline is a snapshot of the repository at a clean moment (which issues and PRs exist, each
issue's state and labels, which branches exist), recorded once with `baseline` and kept in
orchestrator/.demo/baseline.json (not committed; it describes one person's repository). Nothing
that was in the baseline is ever closed or deleted, and `main` and any branch that existed at the
baseline are never touched.

Demo items are marked, not guessed: an issue or PR labelled `demo`, or a PR from a branch whose
name starts with `demo-`. Real development in the same repository (new PRs, their risk scores,
CI results, release verdicts and deploys) is never touched, so its history keeps growing; the
reset lists what it kept. Only the backlog issues in the baseline are put back as they were
(agents relabel them during a demo).

The reset:
  1. GitHub: close demo issues (taking the `incident` label off demo incident reports, so they
     stop counting as incidents); reopen (or re-close) baseline issues to their baseline state and
     restore their baseline labels; close demo PRs, delete the agents' comments and the `tier:`
     labels on them, and delete their branches; delete the deployments of demo PRs' merge
     commits (marked inactive first).
  2. Database: regenerate the simulated history with dates relative to today (which also forgets
     saved forecasts and planner drafts), and forget the audit rows, simulated approvals and gate
     states about the demo issues and PRs (release gate verdicts included).
  3. Collect from GitHub again, so the database matches the repository.
  4. Save fresh forecasts, so the delivery forecast page is ready (skipped when
     ORCHESTRATOR_MODE is off).
The CRM's demo data lives in the API service; scripts/demo.ps1 resets both, in one command.

Usage (inside the orchestrator container; scripts/demo.ps1 wraps all of this):
    python -m sdlc.demo_reset baseline            # record the clean state (once, or --force)
    python -m sdlc.demo_reset                     # what a reset would do; changes nothing
    python -m sdlc.demo_reset --apply             # do it
"""

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from sdlc.agents.comment import MARKER as RISK_MARKER
from sdlc.agents.triage_comment import MARKER as TRIAGE_MARKER
from sdlc.github_client import GitHubClient, GitHubError
from sdlc.signals.github import INCIDENT_LABEL, labels_of
from sdlc.tables import (
    AgentDecision,
    Approval,
    Forecast,
    GateStatus,
    Incident,
    Issue,
    PullRequest,
    Sprint,
)

BASELINE = Path(__file__).resolve().parents[1] / ".demo" / "baseline.json"
DEMO_LABEL = "demo"
DEMO_BRANCH_PREFIX = "demo-"


def is_demo(item: dict) -> bool:
    """A demo issue or PR: labelled `demo`, or (a PR) from a `demo-` branch."""
    ref = (item.get("head") or {}).get("ref", "")
    return DEMO_LABEL in labels_of(item) or ref.startswith(DEMO_BRANCH_PREFIX)


AGENT_MARKERS = (RISK_MARKER, TRIAGE_MARKER)


# --- the baseline ------------------------------------------------------------------------------


def snapshot(gh: GitHubClient) -> dict:
    issues, prs = {}, []
    for item in gh.paginate("/repos/{repo}/issues", state="all"):
        if "pull_request" in item:
            prs.append(item["number"])
        else:
            issues[str(item["number"])] = {
                "state": item["state"],
                "labels": sorted(label["name"] for label in item.get("labels", [])),
            }
    return {
        "recorded_at": datetime.now().replace(microsecond=0).isoformat(),
        "repo": gh.repo,
        "issues": issues,
        "prs": sorted(prs),
        "branches": sorted(b["name"] for b in gh.paginate("/repos/{repo}/branches")),
        "deployments": sorted(d["id"] for d in gh.paginate("/repos/{repo}/deployments")),
    }


def save_baseline(data: dict, path: Path = BASELINE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_baseline(path: Path = BASELINE) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --- what to do on GitHub ----------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    what: str  # plain English, for the dry run and the summary
    method: str  # PATCH | PUT | POST | DELETE
    path: str
    body: dict | None = None


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    left_behind: list[str] = field(default_factory=list)
    demo_issues: list[int] = field(default_factory=list)
    demo_prs: list[int] = field(default_factory=list)
    demo_deployments: int = 0
    real_issues: list[int] = field(default_factory=list)  # new since the baseline, not demo: kept
    real_prs: list[int] = field(default_factory=list)


def plan(gh: GitHubClient, baseline: dict) -> Plan:
    if baseline.get("repo") != gh.repo:
        raise SystemExit(
            f"The baseline is for {baseline.get('repo')}, but GITHUB_REPO is {gh.repo}. "
            "Record a baseline for this repository first."
        )
    p = Plan()
    base_issues: dict = baseline["issues"]
    base_prs = set(baseline["prs"])
    base_branches = set(baseline["branches"])
    default = gh.get("/repos/{repo}").get("default_branch", "main")
    branches = {b["name"] for b in gh.paginate("/repos/{repo}/branches")}
    pr_heads: set[str] = set()

    for item in gh.paginate("/repos/{repo}/issues", state="all"):
        n = item["number"]
        if "pull_request" in item:
            continue
        labels = sorted(label["name"] for label in item.get("labels", []))
        was = base_issues.get(str(n))
        if was is None:
            if not is_demo(item):
                p.real_issues.append(n)
                continue
            p.demo_issues.append(n)
            if INCIDENT_LABEL in labels:
                p.actions.append(
                    Action(
                        f"Take the incident label off issue #{n} (a demo incident)",
                        "DELETE",
                        f"/repos/{{repo}}/issues/{n}/labels/{INCIDENT_LABEL}",
                    )
                )
            if item["state"] == "open":
                p.actions.append(
                    Action(
                        f"Close issue #{n} (opened during a demo): {item['title'][:60]}",
                        "PATCH",
                        f"/repos/{{repo}}/issues/{n}",
                        {"state": "closed", "state_reason": "not_planned"},
                    )
                )
            continue
        if item["state"] != was["state"]:
            verb = "Reopen" if was["state"] == "open" else "Close"
            p.actions.append(
                Action(
                    f"{verb} backlog issue #{n}",
                    "PATCH",
                    f"/repos/{{repo}}/issues/{n}",
                    {"state": was["state"]},
                )
            )
        if labels != was["labels"]:
            p.actions.append(
                Action(
                    f"Restore issue #{n}'s labels ({', '.join(labels) or 'none'} -> "
                    f"{', '.join(was['labels']) or 'none'})",
                    "PUT",
                    f"/repos/{{repo}}/issues/{n}/labels",
                    {"labels": was["labels"]},
                )
            )

    demo_merges: set[str] = set()
    for pr in gh.paginate("/repos/{repo}/pulls", state="all"):
        n = pr["number"]
        if n in base_prs:
            continue
        pr_heads.add(pr["head"]["ref"])  # a branch with a PR, demo or not, isn't an orphan
        if not is_demo(pr):
            p.real_prs.append(n)
            continue
        p.demo_prs.append(n)
        if pr.get("merged_at") and pr.get("merge_commit_sha"):
            demo_merges.add(pr["merge_commit_sha"])
        if pr["state"] == "open":
            p.actions.append(
                Action(
                    f"Close PR #{n} (opened during a demo): {pr['title'][:60]}",
                    "PATCH",
                    f"/repos/{{repo}}/pulls/{n}",
                    {"state": "closed"},
                )
            )
        if pr.get("merged_at"):
            p.left_behind.append(f"PR #{n} was merged: its commits stay on {default}.")
        for comment in gh.paginate(f"/repos/{{repo}}/issues/{n}/comments"):
            if any(marker in (comment.get("body") or "") for marker in AGENT_MARKERS):
                p.actions.append(
                    Action(
                        f"Delete an agent comment on PR #{n}",
                        "DELETE",
                        f"/repos/{{repo}}/issues/comments/{comment['id']}",
                    )
                )
        for label in pr.get("labels", []):
            if label["name"].startswith("tier:"):
                p.actions.append(
                    Action(
                        f"Remove label {label['name']} from PR #{n}",
                        "DELETE",
                        f"/repos/{{repo}}/issues/{n}/labels/{quote(label['name'], safe='')}",
                    )
                )
        head = pr["head"]
        ref = head["ref"]
        same_repo = (head.get("repo") or {}).get("full_name") == gh.repo
        pr_heads.add(ref)
        if same_repo and ref != default and ref not in base_branches and ref in branches:
            p.actions.append(
                Action(
                    f"Delete branch {ref} (PR #{n})",
                    "DELETE",
                    f"/repos/{{repo}}/git/refs/heads/{quote(ref, safe='/')}",
                )
            )

    base_deployments = set(baseline.get("deployments", []))  # older baselines: none existed
    for d in gh.paginate("/repos/{repo}/deployments"):
        if d["id"] in base_deployments or d["sha"] not in demo_merges:
            continue  # the baseline's, or a real release: kept
        what = f"deployment {d['id']} of {d['sha'][:7]} to {d.get('environment')}"
        p.actions.append(
            Action(
                f"Mark {what} inactive",
                "POST",
                f"/repos/{{repo}}/deployments/{d['id']}/statuses",
                {"state": "inactive"},
            )
        )
        p.actions.append(
            Action(f"Delete {what}", "DELETE", f"/repos/{{repo}}/deployments/{d['id']}")
        )
        p.demo_deployments += 1
    if p.demo_deployments:
        p.left_behind.append(
            "release-gate statuses stay on the demo's commits in main (GitHub can't delete a "
            "commit status), as do the deploy workflow's run logs."
        )

    for name in sorted(branches - base_branches - pr_heads - {default}):
        p.left_behind.append(f"Branch {name} is new since the baseline but has no PR: kept.")
    if p.real_issues or p.real_prs:
        p.left_behind.append(
            f"Kept as real work (not marked demo): {len(p.real_issues)} issue(s) and "
            f"{len(p.real_prs)} PR(s) new since the baseline."
        )
    if p.demo_issues:
        p.left_behind.append(
            f"{len(p.demo_issues)} issue(s) opened during demos stay on GitHub as closed "
            "(GitHub can't delete issues)."
        )
    return p


def apply_plan(gh: GitHubClient, p: Plan) -> tuple[list[str], list[str]]:
    """Carry out every action; one failure doesn't stop the rest. Returns (done, failed)."""
    done, failed = [], []
    for a in p.actions:
        try:
            if a.method == "PATCH":
                gh.patch(a.path, a.body or {})
            elif a.method == "POST":
                gh.post(a.path, a.body or {})
            elif a.method == "PUT":
                gh.put(a.path, a.body or {})
            else:
                gh.delete(a.path)
            done.append(a.what)
        except GitHubError as err:
            failed.append(f"{a.what}: {err}")
    return done, failed


# --- the database ------------------------------------------------------------------------------


def reset_database(db: Session, demo_issues: list[int], demo_prs: list[int]) -> dict:
    """Fresh simulated history, and no audit rows, approvals or gate states about demo items."""
    from sdlc.synth import build
    from sdlc.synth import reset as synth_reset

    numbers = sorted(set(demo_issues) | set(demo_prs))
    forgotten = 0
    if numbers:
        demo_pr_ids = select(PullRequest.id).where(
            PullRequest.source == "github", PullRequest.number.in_(demo_prs or [-1])
        )
        db.execute(delete(Approval).where(Approval.pull_request_id.in_(demo_pr_ids)))
        db.execute(delete(GateStatus).where(GateStatus.pull_request_id.in_(demo_pr_ids)))
        forgotten = db.execute(
            delete(AgentDecision).where(
                AgentDecision.subject_source == "github",
                AgentDecision.subject_type.in_(["issue", "pr", "release"]),
                AgentDecision.subject_id.in_(numbers),
            )
        ).rowcount
        db.execute(
            delete(Incident).where(
                Incident.source == "github",
                Incident.external_id.in_([f"issue-{n}" for n in demo_issues] or ["-"]),
            )
        )
        db.commit()
    synth_reset(db)
    counts = build(db)
    return {"history": counts, "audit_rows_forgotten": forgotten}


def row_counts(db: Session) -> dict:
    def n(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where))

    return {
        "sprints": n(Sprint),
        "simulated issues": n(Issue, Issue.source == "synthetic"),
        "simulated PRs": n(PullRequest, PullRequest.source == "synthetic"),
        "open real issues": n(Issue, Issue.source == "github", Issue.state == "open"),
        "open real PRs": n(
            PullRequest, PullRequest.source == "github", PullRequest.state == "open"
        ),
        "saved forecasts": n(Forecast),
        "audit rows": n(AgentDecision),
    }


# --- the command -------------------------------------------------------------------------------


def run(gh: GitHubClient, baseline: dict, *, apply: bool, mode: str) -> str:
    from sdlc.db import SessionLocal

    started = time.monotonic()
    p = plan(gh, baseline)
    lines = [
        f"Baseline recorded {baseline['recorded_at']}: {len(baseline['issues'])} issues, "
        f"{len(baseline['prs'])} PRs, {len(baseline['branches'])} branches.",
        f"Since then: {len(p.demo_issues)} demo issue(s), {len(p.demo_prs)} demo PR(s), "
        f"{p.demo_deployments} deployment(s).",
        "",
        "GitHub:" if p.actions else "GitHub: nothing to undo.",
        *[f"  - {a.what}" for a in p.actions],
    ]
    if not apply:
        lines += [
            "",
            "Database: regenerate the simulated history for today; forget audit rows, simulated "
            "approvals and gate states about the demo items; collect from GitHub; save forecasts.",
            "",
            "Dry run: nothing was changed. Add --apply to do it.",
        ]
    else:
        done, failed = apply_plan(gh, p)
        with SessionLocal() as db:
            reset = reset_database(db, p.demo_issues, p.demo_prs)
            from sdlc.signals.github import Collector
            from sdlc.tiers import load_policy

            rules = load_policy().release
            collected = Collector(db, gh).run((rules.environment, rules.signoff_environment))
            forecasts = "skipped (ORCHESTRATOR_MODE is off)"
            if mode != "off":
                from sdlc.forecaster import ForecastRunner

                saved = ForecastRunner(mode).poll_once(force=True)
                forecasts = f"{saved.get('assessed', 0)} saved"
            counts = row_counts(db)
        history = ", ".join(f"{v} {k}" for k, v in reset["history"].items())
        lines += [
            "",
            f"GitHub: {len(done)} done, {len(failed)} failed.",
            *[f"  FAILED {f}" for f in failed],
            f"Simulated history regenerated: {history}.",
            f"Audit rows about demo items forgotten: {reset['audit_rows_forgotten']}.",
            "Collected from GitHub: " + ", ".join(f"{v} {k}" for k, v in collected.items()) + ".",
            f"Forecasts: {forecasts}.",
            "",
            "Row counts now: " + ", ".join(f"{v} {k}" for k, v in counts.items()) + ".",
        ]
    if p.left_behind:
        lines += ["", "Left behind:", *[f"  - {x}" for x in p.left_behind]]
    lines += ["", f"Took {time.monotonic() - started:.0f} seconds."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Reset the demo to its baseline.")
    parser.add_argument("command", nargs="?", choices=["baseline"], help="record the baseline")
    parser.add_argument("--apply", action="store_true", help="really reset (default: dry run)")
    parser.add_argument("--force", action="store_true", help="replace an existing baseline")
    args = parser.parse_args(argv)

    from sdlc.config import get_settings

    try:
        gh = GitHubClient()
    except GitHubError as err:
        raise SystemExit(str(err)) from err

    if args.command == "baseline":
        if BASELINE.exists() and not args.force:
            raise SystemExit(f"A baseline already exists ({BASELINE}). Add --force to replace it.")
        data = snapshot(gh)
        save_baseline(data)
        print(
            f"Baseline recorded for {data['repo']}: {len(data['issues'])} issues "
            f"({sum(i['state'] == 'open' for i in data['issues'].values())} open), "
            f"{len(data['prs'])} PRs, {len(data['branches'])} branches."
        )
        return

    baseline = load_baseline()
    if baseline is None:
        raise SystemExit(
            "No baseline yet. When the repository is in a clean state, record one with "
            "`python -m sdlc.demo_reset baseline`."
        )
    print(run(gh, baseline, apply=args.apply, mode=get_settings().orchestrator_mode))


if __name__ == "__main__":
    main()
