"""The pre-demo checklist: is everything the demo needs actually ready?

Each check says PASS, WARN or FAIL, and every FAIL says how to fix it. The exit code is 1 if
anything failed, so scripts/demo.ps1 can stop on it. Container state and the web app are checked
by scripts/demo.ps1 from the host (the web dev server refuses requests from inside Docker).

Checks: the database and both migration histories, both APIs, the CRM's demo data, the simulated
history (a sprint in progress today), today's saved forecasts, GitHub access, the repository
matching the demo baseline (no residue from a previous demo), the release gate's GitHub setup (the
deploy workflow, both environments, the sign-off environment's reviewer, the token's Deployments
access), and ORCHESTRATOR_MODE (enforce, so the release gate really holds a deploy).
`--smoke --yes` also scores one real PR and triages one real issue end to end with Claude (about
5 cents; recorded as trial audit rows, nothing written to GitHub).

Usage (inside the orchestrator container; scripts/demo.ps1 check wraps it):
    python -m sdlc.demo_check
    python -m sdlc.demo_check --smoke --yes
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

CRM_API = "http://api:8000/api/v1/health"
ORCH_API = "http://localhost:8001/api/v1/health"
MIN_CRM = {"accounts": 20, "leads": 50, "opportunities": 50}
MIN_SIMULATED_PRS = 300


@dataclass(frozen=True)
class Check:
    name: str
    state: str  # PASS | WARN | FAIL
    detail: str


def _db(db: Session) -> list[Check]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    try:
        db.execute(text("SELECT 1"))
    except Exception as err:  # noqa: BLE001 - any failure here means "not reachable"
        return [Check("Database", "FAIL", f"Not reachable ({err}). Is the db container up?")]
    out = [Check("Database", "PASS", "reachable")]
    root = Path(__file__).resolve().parents[1]
    head = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
    current = db.execute(text("SELECT version_num FROM sdlc_alembic_version")).scalar()
    out.append(
        Check("Orchestrator migrations", "PASS", f"at {head}")
        if current == head
        else Check(
            "Orchestrator migrations",
            "FAIL",
            f"at {current}, head is {head}: run `alembic upgrade head` in the orchestrator.",
        )
    )
    counts = {
        table: db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in MIN_CRM
    }
    thin = [t for t, n in counts.items() if n < MIN_CRM[t]]
    summary = ", ".join(f"{n} {t}" for t, n in counts.items())
    out.append(
        Check("CRM demo data", "FAIL", f"{summary}: run the reset (it reseeds the CRM).")
        if thin
        else Check("CRM demo data", "PASS", summary)
    )
    return out


def _apis() -> list[Check]:
    out = []
    for name, url in (("Orchestrator API", ORCH_API), ("CRM API", CRM_API)):
        try:
            body = httpx.get(url, timeout=5).json()
            ok = body.get("status") == "ok" and body.get("database") == "ok"
            out.append(
                Check(name, "PASS" if ok else "FAIL", "healthy" if ok else f"degraded: {body}")
            )
        except Exception as err:  # noqa: BLE001
            out.append(Check(name, "FAIL", f"not answering at {url} ({type(err).__name__})."))
    return out


def _history(db: Session, today: date) -> list[Check]:
    from sdlc.forecast import current_sprint
    from sdlc.tables import Forecast, PullRequest

    out = []
    sprint = current_sprint(db, today, "synthetic")
    prs = db.scalar(
        select(func.count()).select_from(PullRequest).where(PullRequest.source == "synthetic")
    )
    if sprint and prs >= MIN_SIMULATED_PRS:
        out.append(
            Check(
                "Simulated history",
                "PASS",
                f"{prs} simulated PRs; {sprint.name} runs to {sprint.end_date:%a %b %d}",
            )
        )
    else:
        out.append(
            Check(
                "Simulated history",
                "FAIL",
                f"{prs} simulated PRs, {'a' if sprint else 'no'} sprint in progress today: "
                "run the reset.",
            )
        )
    saved_today = db.scalar(
        select(func.count()).select_from(Forecast).where(Forecast.as_of == today)
    )
    out.append(
        Check("Forecasts", "PASS", f"{saved_today} saved today")
        if saved_today
        else Check(
            "Forecasts",
            "FAIL",
            "none saved today: start the agent loop, or run `python -m sdlc.forecaster now`.",
        )
    )
    return out


def _github() -> list[Check]:
    from sdlc.demo_reset import load_baseline, plan
    from sdlc.github_client import GitHubClient, GitHubError

    try:
        gh = GitHubClient()
        repo = gh.get("/repos/{repo}")
    except GitHubError as err:
        return [Check("GitHub", "FAIL", f"{err}. Check GITHUB_TOKEN and GITHUB_REPO in .env.")]
    out = [Check("GitHub", "PASS", f"token works for {repo['full_name']}")]
    baseline = load_baseline()
    if baseline is None:
        return out + [
            Check(
                "Demo baseline",
                "FAIL",
                "none recorded: with the repo clean, run `python -m sdlc.demo_reset baseline`.",
            )
        ]
    out += _release_setup(gh)
    p = plan(gh, baseline)
    if p.actions:
        return out + [
            Check(
                "Clean start",
                "FAIL",
                f"{len(p.actions)} thing(s) left from a previous demo "
                f"({p.actions[0].what}{' ...' if len(p.actions) > 1 else ''}): run the reset.",
            )
        ]
    return out + [Check("Clean start", "PASS", "the repository matches the demo baseline")]


def _release_setup(gh) -> list[Check]:
    """What the no-op deploy and its release gate need on GitHub. Setting it up: CLAUDE.md."""
    from sdlc.github_client import GitHubError
    from sdlc.release_runner import DEPLOY_WORKFLOW
    from sdlc.tiers import load_policy

    rules = load_policy().release
    out = []
    try:
        gh.get(f"/repos/{{repo}}/actions/workflows/{DEPLOY_WORKFLOW}")
        out.append(Check("Deploy workflow", "PASS", f"{DEPLOY_WORKFLOW} is on the default branch"))
    except GitHubError as err:
        out.append(Check("Deploy workflow", "FAIL", f"{err}. Merge {DEPLOY_WORKFLOW} into main."))
    for name, needs_reviewer in ((rules.environment, False), (rules.signoff_environment, True)):
        label = f"Environment {name}"
        try:
            env = gh.get(f"/repos/{{repo}}/environments/{name}")
        except GitHubError as err:
            fix = "create it in Settings > Environments" + (
                ", with yourself as required reviewer" if needs_reviewer else ""
            )
            out.append(Check(label, "FAIL", f"{err}: {fix}."))
            continue
        reviewers = [
            r for r in env.get("protection_rules", []) if r.get("type") == "required_reviewers"
        ]
        if needs_reviewer and not reviewers:
            out.append(
                Check(
                    label,
                    "FAIL",
                    "has no required reviewer, so T3 deploys won't wait for your approval: "
                    "add yourself under Deployment protection rules.",
                )
            )
        else:
            out.append(Check(label, "PASS", "required reviewer set" if reviewers else "exists"))
    try:
        gh.get("/repos/{repo}/deployments", per_page=1)
        out.append(
            Check(
                "Token: deployments",
                "PASS",
                "can read deployments (the reset also needs write, which can't be tested safely)",
            )
        )
    except GitHubError as err:
        out.append(
            Check(
                "Token: deployments", "FAIL", f"{err}: give the token Deployments read and write."
            )
        )
    return out


def _mode(mode: str) -> Check:
    if mode == "off":
        return Check(
            "ORCHESTRATOR_MODE",
            "FAIL",
            "off: the agents won't react during the demo. Set it to shadow in .env.",
        )
    if mode == "shadow":
        return Check(
            "ORCHESTRATOR_MODE",
            "WARN",
            "shadow: the release gate will only say what it would do and never hold a deploy. "
            "Set enforce in .env for the demo, and shadow again afterwards.",
        )
    return Check(
        "ORCHESTRATOR_MODE",
        "PASS",
        "enforce: the release gate holds deploys and risk-gate shows its real state (it isn't a "
        "required check, so it never blocks a merge). Set shadow again after the demo.",
    )


def _smoke() -> list[Check]:
    """Score one real merged PR and triage one real issue with the real models."""
    from sdlc.db import SessionLocal
    from sdlc.tables import Issue, PullRequest

    with SessionLocal() as db:
        pr = db.scalar(
            select(PullRequest.number)
            .where(PullRequest.source == "github", PullRequest.state == "merged")
            .order_by(PullRequest.number.desc())
            .limit(1)
        )
        issue = db.scalar(
            select(Issue.number)
            .where(Issue.source == "github", Issue.state == "open")
            .order_by(Issue.number)
            .limit(1)
        )
    out = []
    for name, module, number in (
        ("Smoke: PR risk", "sdlc.runner", pr),
        ("Smoke: triage", "sdlc.issue_runner", issue),
    ):
        if number is None:
            out.append(Check(name, "FAIL", "nothing real to try it on: run the reset first."))
            continue
        run = subprocess.run(
            [sys.executable, "-m", module, "try", str(number), "--yes"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        ok = "Status: ok" in run.stdout
        detail = f"#{number} scored end to end" if ok else (run.stdout + run.stderr)[-300:]
        out.append(Check(name, "PASS" if ok else "FAIL", detail))
    return out


def run_checks(*, smoke: bool = False, today: date | None = None) -> list[Check]:
    from sdlc.config import get_settings
    from sdlc.db import SessionLocal

    today = today or date.today()
    with SessionLocal() as db:
        checks = _db(db)
        if checks[0].state == "PASS":
            checks += _history(db, today)
    checks += _apis()
    checks += _github()
    checks.append(_mode(get_settings().orchestrator_mode))
    if smoke:
        checks += _smoke()
    return checks


def describe(checks: list[Check]) -> str:
    lines = [f"  {c.state:<4}  {c.name:<24} {c.detail}" for c in checks]
    failed = sum(c.state == "FAIL" for c in checks)
    lines.append("")
    lines.append("Ready for the demo." if not failed else f"Not ready: {failed} check(s) failed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check the demo is ready.")
    parser.add_argument("--smoke", action="store_true", help="also run one PR and one issue")
    parser.add_argument("--yes", action="store_true", help="allow the smoke test's API calls")
    args = parser.parse_args(argv)
    if args.smoke and not args.yes:
        raise SystemExit("The smoke test calls Claude (about 5 cents). Add --yes to run it.")
    checks = run_checks(smoke=args.smoke)
    print(describe(checks))
    raise SystemExit(1 if any(c.state == "FAIL" for c in checks) else 0)


if __name__ == "__main__":
    main()
