"""The release gate for real releases: judge each deploy waiting in GitHub, post `release-gate`.

The deploy workflow (.github/workflows/deploy.yml) runs on every push to `main` and waits for a
`release-gate` commit status on that commit. This runner, in the shared poll loop, finds deploy
runs still waiting, works out the release (every PR merged since the last successful deploy, up
to the commit being deployed), gathers the facts (CI on that commit, open incidents, recent
deploys) and lets sdlc/agents/release_gate.py decide. No Claude calls, so it costs nothing.

It writes one thing to GitHub, the `release-gate` status, and one audit row each time its verdict
on a commit changes (`agent = release_gate`, `subject_type = release`, `subject_id` = the PR whose
merge made that commit, `head_sha` = the commit). It never deploys, approves a deployment or
cancels a run: the workflow deploys, and a person approves T3 deployments in GitHub.

Incidents are GitHub issues labelled `incident` plus `module:<name>` (see sdlc/signals/github.py):
open one to hold a release that touches that module, close it to let the release go.

Usage (inside the orchestrator container):
    python -m sdlc.release_runner once    # one poll; `python -m sdlc.runner run` polls forever
"""

import argparse
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.agents import release_gate as gate
from sdlc.agents.github_effects import Effects
from sdlc.agents.pr_risk import AGENT as PR_RISK_AGENT
from sdlc.audit import decisions_for, latest_decision, record_decision
from sdlc.github_client import GitHubClient, GitHubError
from sdlc.governance import Facts, assign_tier
from sdlc.scoring import score_pull_request
from sdlc.signals.github import Collector
from sdlc.suite_selector import ci_results
from sdlc.tables import Deployment, GateStatus, Incident, PullRequest
from sdlc.tiers import Policy, load_policy

log = logging.getLogger("sdlc.release_runner")

SOURCE = "github"
DEPLOY_WORKFLOW = "deploy.yml"
# Run states in which the workflow's release-gate job may still be waiting for a verdict. A run
# "waiting" for a deployment approval has already passed the gate: its verdict can't change it.
JUDGING = {"queued", "requested", "pending", "in_progress"}


def shipped_through(db: Session, deployment: Deployment) -> datetime:
    """The last merge a deployment shipped: the merge of the commit it deployed, when known.

    Deploying a merge commit ships every PR merged up to it. A simulated deployment has no
    commit and ships everything merged before it went out."""
    if deployment.sha:
        merged = db.scalar(
            select(PullRequest.merged_at).where(
                PullRequest.source == deployment.source,
                PullRequest.merge_commit_sha == deployment.sha,
            )
        )
        if merged:
            return merged
    return deployment.deployed_at


def release_prs(db: Session, head: PullRequest) -> list[PullRequest]:
    """Every real PR merged since the last successful deploy, up to and including `head`."""
    deploys = db.scalars(
        select(Deployment).where(Deployment.source == SOURCE, Deployment.status == "success")
    )
    cutoffs = [shipped_through(db, d) for d in deploys]
    since = max(cutoffs) if cutoffs else None
    if since is None:
        return [head]  # the first release: just this commit's PR
    rows = db.scalars(
        select(PullRequest).where(
            PullRequest.source == SOURCE,
            PullRequest.state == "merged",
            PullRequest.merged_at > since,
            PullRequest.merged_at <= head.merged_at,
        )
    )
    prs = list(rows)
    return prs if head in prs else [*prs, head]


def tier_of(db: Session, policy: Policy, pr: PullRequest) -> str:
    """The tier in force at merge (overrides included), else the agent's, else the rubric's."""
    status = db.scalar(select(GateStatus.tier).where(GateStatus.pull_request_id == pr.id))
    if status:
        return status
    decided = latest_decision(
        db, PR_RISK_AGENT, subject_type="pr", subject_source=SOURCE, subject_id=pr.number
    )
    if decided and decided.tier:
        return decided.tier
    facts = Facts(pr.module, pr.touches_migration, pr.docs_only)
    return assign_tier(policy, score_pull_request(db, pr).total, facts).tier


def recent_deploys(db: Session, policy: Policy, now: datetime) -> tuple[int, int]:
    """(real deploys in the failure-rate window, how many of them caused an incident)."""
    since = now - timedelta(days=policy.release.failure_window_days)
    deploys = list(
        db.scalars(
            select(Deployment).where(
                Deployment.source == SOURCE,
                Deployment.status == "success",
                Deployment.deployed_at >= since,
            )
        )
    )
    caused = {
        i.deployment_id
        for i in db.scalars(select(Incident).where(Incident.source == SOURCE))
        if i.deployment_id
    }
    return len(deploys), sum(d.id in caused for d in deploys)


class ReleaseRunner:
    def __init__(self, gh: GitHubClient, policy: Policy, mode: str):
        self.gh = gh
        self.policy = policy
        self.mode = mode
        self.effects = Effects(gh, mode)
        self._posted: dict[str, tuple[str, str]] = {}  # commit -> status last posted

    def poll_once(self, now: datetime | None = None) -> dict:
        if self.mode == "off":
            return {"mode": "off"}
        from sdlc.db import SessionLocal

        now = now or datetime.now().replace(microsecond=0)
        summary = {"mode": self.mode, "releases": 0, "assessed": 0, "errors": 0}
        rules = self.policy.release
        with SessionLocal() as db:
            collector = Collector(db, self.gh)
            collector.collect_deployments((rules.environment, rules.signoff_environment))
            collector.collect_incidents()
            waiting = self.waiting_commits()
            if waiting:
                self.refresh_merged(db, collector)
            for sha in waiting:
                summary["releases"] += 1
                try:
                    if self.judge(db, collector, sha, now):
                        summary["assessed"] += 1
                except GitHubError as err:
                    summary["errors"] += 1
                    log.warning("release %s: %s", sha[:7], err)
            db.commit()
        return summary

    def waiting_commits(self) -> list[str]:
        """Commits on `main` whose deploy run may still be waiting for the gate, newest first."""
        try:
            runs = self.gh.get(
                f"/repos/{{repo}}/actions/workflows/{DEPLOY_WORKFLOW}/runs",
                branch="main",
                per_page=20,
            )["workflow_runs"]
        except GitHubError as err:
            if " 404 " in str(err):
                return []  # no deploy workflow on this repository (yet)
            raise
        commits: list[str] = []
        for run in runs:
            if run.get("status") in JUDGING and run["head_sha"] not in commits:
                commits.append(run["head_sha"])
        return commits

    def refresh_merged(self, db: Session, collector: Collector) -> None:
        """Store recently merged PRs as merged: the risk agent's poll only looks at open ones."""
        for item in self.gh.get(
            "/repos/{repo}/pulls", state="closed", sort="updated", direction="desc", per_page=20
        ):
            if not item.get("merged_at"):
                continue
            known = db.scalar(
                select(PullRequest).where(
                    PullRequest.source == SOURCE, PullRequest.external_id == f"pr-{item['number']}"
                )
            )
            if known is None or known.merge_commit_sha is None:
                collector.collect_pull_request(item)

    def head_pr(self, db: Session, collector: Collector, sha: str) -> PullRequest | None:
        pr = db.scalar(
            select(PullRequest).where(
                PullRequest.source == SOURCE, PullRequest.merge_commit_sha == sha
            )
        )
        if pr:
            return pr
        for item in self.gh.get(f"/repos/{{repo}}/commits/{sha}/pulls"):
            if item.get("merged_at"):
                pr = collector.collect_pull_request(item)
                if pr.merge_commit_sha == sha:
                    return pr
        return None

    def facts_for(self, db: Session, head: PullRequest | None, sha: str, now: datetime):
        prs = release_prs(db, head) if head else []
        modules = sorted({p.module for p in prs if p.module})
        results = ci_results(self.gh, sha)
        if results is None:
            ci = "running"
        else:
            ci = (
                "failed"
                if any(r["conclusion"] == "failure" for r in results.values())
                else "passed"
            )
        incidents = db.scalars(
            select(Incident).where(
                Incident.source == SOURCE,
                Incident.resolved_at.is_(None),
                Incident.module.in_(modules or ["-"]),
            )
        )
        deploys, failed = recent_deploys(db, self.policy, now)
        return gate.ReleaseFacts(
            tier=gate.release_tier(
                [tier_of(db, self.policy, p) for p in prs], self.policy.fallback_tier
            ),
            prs=tuple(p.number for p in prs),
            modules=tuple(modules),
            ci=ci,
            open_incidents=tuple(
                gate.OpenIncident(
                    module=i.module or "",
                    number=int(i.external_id.split("-")[1]) if i.external_id else None,
                    title=i.title,
                )
                for i in incidents
            ),
            recent_deploys=deploys,
            failed_deploys=failed,
            signoff=None,  # given in GitHub, on the sign-off environment
        )

    def judge(self, db: Session, collector: Collector, sha: str, now: datetime) -> bool:
        """Post this commit's release-gate status; record a row when the verdict changed."""
        head = self.head_pr(db, collector, sha)
        facts = self.facts_for(db, head, sha, now)
        verdict = gate.evaluate(self.policy, facts, mode=self.mode)
        posted = (verdict.state, verdict.description)
        subject = head.number if head else 0
        prior = decisions_for(
            db,
            gate.AGENT,
            subject_type="release",
            subject_source=SOURCE,
            subject_id=subject,
            head_sha=sha,
        )
        last = (prior[-1].action_taken or {}) if prior else {}
        changed = (last.get("state"), last.get("description")) != posted
        if not changed and self._posted.get(sha) == posted:
            return False
        effect = self.effects.set_status(
            sha, verdict.state, verdict.description, context=gate.STATUS_CONTEXT
        )
        self._posted[sha] = posted
        if not changed:
            return False  # re-posted after a restart; the audit trail already has it
        record_decision(
            db,
            agent=gate.AGENT,
            agent_version=gate.AGENT_VERSION,
            subject_type="release",
            subject_source=SOURCE,
            subject_id=subject,
            trigger="poll",
            now=now,
            head_sha=sha,
            attempt=len(prior) + 1,
            tier=facts.tier,
            output=gate.output_of(facts, verdict, mode=self.mode),
            action_taken={"state": verdict.state, "description": verdict.description, **effect},
            status="ok",
        )
        return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the release gate once.")
    parser.add_argument("command", choices=["once"])
    parser.parse_args(argv)
    from sdlc.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        runner = ReleaseRunner(GitHubClient(), load_policy(), get_settings().orchestrator_mode)
    except GitHubError as err:
        raise SystemExit(str(err)) from err
    print(runner.poll_once())


if __name__ == "__main__":
    main()
