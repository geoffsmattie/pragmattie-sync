"""Poll GitHub and run the agents. (The demo is local-only, so it polls; no webhooks.)

`run` and `once` drive the PR risk agent (this module), the triage agent
(sdlc/issue_runner.py), the forecaster (sdlc/forecaster.py) and the planner (sdlc/plan_runner.py)
together, one poll cycle each, in one process — one container for the whole orchestrator, per
the blueprint's shared ORCHESTRATOR_MODE kill switch. The agents are otherwise independent: see
each one's module for its own triggers and autonomy rules.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.runner run            # poll every agent forever, every POLL_SECONDS
    python -m sdlc.runner once           # one poll of every agent, then exit
    python -m sdlc.runner dry-run 7      # show the exact PR risk request for PR #7; calls nothing
    python -m sdlc.runner try 7 --yes    # call Claude for PR #7; prints the answer, writes nothing
For the triage agent's own dry-run/try commands, use `python -m sdlc.issue_runner`.

ORCHESTRATOR_MODE decides what a poll may do, for both agents:
    off      nothing at all: no reads, no writes, no API calls
    shadow   comment, label and record decisions, but the PR risk-gate status always passes
    enforce  the risk-gate status is real: pending until the tier's people have signed off
One decision per PR commit: a new push is assessed once, and the sign-off boxes start empty.
A failed run is retried up to three times, five minutes apart, and fails closed until it works.
"""

import argparse
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sdlc import gate_status
from sdlc.agents.comment import Meta, comment_head, read_ticks, refresh, render
from sdlc.agents.gate import Approvals, evaluate
from sdlc.agents.github_effects import Effects
from sdlc.agents.llm import StructuredLLM
from sdlc.agents.pr_risk import (
    AGENT,
    AGENT_VERSION,
    PROMPT_HASH,
    PROMPT_VERSION,
    SCHEMA,
    SYSTEM_PROMPT,
    Assessment,
    assess,
    build_prompt,
)
from sdlc.approver import ApproverError, load_approvers, request_approval, resolve_approver
from sdlc.audit import decisions_for, record_decision
from sdlc.calibration import facts_of
from sdlc.config import get_settings
from sdlc.db import SessionLocal
from sdlc.forecaster import ForecastRunner
from sdlc.github_client import GitHubClient, GitHubError
from sdlc.issue_runner import IssueRunner
from sdlc.plan_runner import PlannerRunner
from sdlc.scoring import compute_features, features_digest, score_features
from sdlc.signals.github import Collector
from sdlc.tables import Approval, PullRequest
from sdlc.tiers import Policy, load_policy

log = logging.getLogger("sdlc.runner")

MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=5)
# Rough Sonnet 5 rates in dollars per million tokens, only for the dry-run estimate.
INPUT_RATE, OUTPUT_RATE = 2.0, 10.0


class Runner:
    def __init__(self, gh: GitHubClient, llm: StructuredLLM, policy: Policy, mode: str):
        self.gh = gh
        self.llm = llm
        self.policy = policy
        self.mode = mode
        self.effects = Effects(gh, mode)
        self.diff_char_limit = get_settings().diff_char_limit
        self._last_status: dict[tuple[int, str], tuple[str, str]] = {}

    # --- one poll ----------------------------------------------------------------------------

    def poll_once(self, now: datetime | None = None) -> dict:
        if self.mode == "off":
            return {"mode": "off"}
        now = now or datetime.now().replace(microsecond=0)
        summary = {"mode": self.mode, "prs": 0, "assessed": 0, "failed": 0, "errors": 0}
        for item in self.gh.get("/repos/{repo}/pulls", state="open", per_page=100):
            if item.get("draft"):
                continue  # scored once it is marked ready for review
            summary["prs"] += 1
            try:
                self._handle(item, now, summary)
            except (GitHubError, IntegrityError) as err:
                summary["errors"] += 1
                log.warning("PR #%s: %s", item["number"], err)
        return summary

    def _handle(self, item: dict, now: datetime, summary: dict) -> None:
        number, sha = item["number"], item["head"]["sha"]
        with SessionLocal() as db:
            pr = Collector(db, self.gh).collect_pull_request(item)
            decisions = decisions_for(
                db,
                AGENT,
                subject_type="pr",
                subject_source=pr.source,
                subject_id=pr.number,
                head_sha=sha,
            )
            good = next((d for d in decisions if d.status == "ok"), None)
            comment = self.effects.find_comment(number)

            if good is None and self._may_try(decisions, now):
                self._assess_and_publish(db, pr, sha, len(decisions) + 1, comment, now, summary)
            elif decisions:
                self._refresh_gate(db, pr, sha, good or decisions[-1], comment, now)
            db.commit()

    def _may_try(self, decisions: list, now: datetime) -> bool:
        if not decisions:
            return True
        return len(decisions) < MAX_ATTEMPTS and now - decisions[-1].created_at >= RETRY_AFTER

    # --- assess, then publish ----------------------------------------------------------------

    def _assess_and_publish(self, db, pr, sha, attempt, comment, now, summary) -> None:
        description = self.effects.read_pr(pr.number).get("body") or ""
        diff = self.effects.read_diff(pr.number)
        assessment = assess(
            db,
            pr,
            llm=self.llm,
            policy=self.policy,
            description=description,
            diff=diff,
            diff_char_limit=self.diff_char_limit,
            now=now,
        )
        summary["assessed"] += 1
        summary["failed"] += 0 if assessment.ok else 1

        tier = assessment.assignment.tier
        approver = self._request_simulated_approval(db, pr, tier)
        approvals = Approvals()  # a new commit starts with nothing signed off
        gate = evaluate(self.policy, tier, ok=assessment.ok, approvals=approvals, mode=self.mode)

        # Record first so the comment can name its decision; the row is one flush, one commit.
        decision = record_decision(
            db,
            agent=AGENT,
            agent_version=AGENT_VERSION,
            subject_type="pr",
            subject_source=pr.source,
            subject_id=pr.number,
            trigger="poll",
            now=now,
            head_sha=sha,
            attempt=attempt,
            model_id=self.llm.model,
            prompt_version=PROMPT_VERSION,
            prompt_hash=PROMPT_HASH,
            inputs_digest=features_digest(assessment.features) if assessment.features else None,
            raw_score=assessment.raw_score,
            adjustment=assessment.adjustment,
            final_score=assessment.final_score,
            tier=tier,
            signals=assessment.signals,
            output=_output_of(assessment),
            status=assessment.status,
            error=assessment.error,
            latency_ms=assessment.llm.latency_ms if assessment.llm else None,
            input_tokens=assessment.llm.input_tokens if assessment.llm else None,
            output_tokens=assessment.llm.output_tokens if assessment.llm else None,
        )
        meta = Meta(decision.id, self.mode, approver, sha)
        body = render(assessment, gate, approvals, self.policy, meta)
        decision.action_taken = {
            "comment": self.effects.upsert_comment(pr.number, body, comment),
            "label": self.effects.set_tier_label(pr.number, tier),
            "status": self.effects.set_status(sha, gate.state, gate.description),
            "mode": self.mode,
        }
        self._last_status[(pr.number, sha)] = (gate.state, gate.description)
        gate_status.upsert(db, pr, gate, tier=tier, mode=self.mode, now=now)

    def _request_simulated_approval(self, db, pr: PullRequest, tier: str) -> str:
        """T3 needs a second human; Geoff is the only one, so the simulated approver fills in."""
        try:
            approver = resolve_approver(load_approvers(), None)
            if tier in approver["applies_to_tiers"]:
                request_approval(db, pr, approver, tier, "Assigned by the PR risk agent")
            return approver["name"]
        except ApproverError:
            return "Simulated second approver"  # already requested, or not needed

    # --- keep the check in step with what people do ------------------------------------------

    def _refresh_gate(self, db, pr, sha, decision, comment, now) -> None:
        ok = decision.status == "ok"
        signoff, qa = read_ticks(comment["body"], sha) if comment else (False, False)
        simulated = bool(
            db.scalar(
                select(Approval.id).where(
                    Approval.pull_request_id == pr.id, Approval.status == "approved"
                )
            )
        )
        approvals = Approvals(signoff=signoff, qa_done=qa, simulated_approved=simulated)
        gate = evaluate(self.policy, decision.tier, ok=ok, approvals=approvals, mode=self.mode)
        gate_status.upsert(db, pr, gate, tier=decision.tier, mode=self.mode, now=now)

        key = (pr.number, sha)
        if self._last_status.get(key) != (gate.state, gate.description):
            self.effects.set_status(sha, gate.state, gate.description)
            self._last_status[key] = (gate.state, gate.description)
        if comment and comment_head(comment["body"]) == sha:
            updated = refresh(comment["body"], gate, simulated)
            if updated != comment["body"]:
                self.effects.upsert_comment(pr.number, updated, comment)


def _output_of(a: Assessment) -> dict | None:
    if a.llm is None:
        return None
    return {
        "model_answer": a.llm.data,  # verbatim, before the clamp
        "applied_adjustment": a.adjustment,
        "clamped": a.clamped,
        "request_id": a.llm.request_id,
        "cache_read_tokens": a.llm.cache_read_tokens,
        "cache_write_tokens": a.llm.cache_write_tokens,
        "reasons": list(a.assignment.reasons),
        "floors": list(a.assignment.floors),
    }


# --- commands that look before they leap -----------------------------------------------------


def prepare(runner: Runner, number: int):
    """The PR's row, features, and the exact prompt Claude would get. Reads only from GitHub."""
    details = runner.effects.read_pr(number)
    diff = runner.effects.read_diff(number)
    with SessionLocal() as db:
        pr = Collector(db, runner.gh).collect_pull_request(details)
        features = compute_features(db, pr, datetime.now().replace(microsecond=0))
        score = score_features(features)
        user = build_prompt(
            pr, features, score, details.get("body") or "", diff, runner.diff_char_limit
        )
        facts = facts_of(pr)
        db.commit()
    return pr.title, score, facts, user, details.get("body") or "", diff


def estimate(system: str, user: str, max_tokens: int) -> str:
    # Measured on the first live call: code, JSON and markdown run about two characters a
    # token, so this errs high on purpose (it is a ceiling, not a forecast).
    tokens_in = (len(system) + len(user)) // 2
    ceiling = tokens_in * INPUT_RATE / 1e6 + max_tokens * OUTPUT_RATE / 1e6
    return (
        f"about {tokens_in:,} input tokens; at most {max_tokens:,} output tokens; "
        f"a ceiling of roughly ${ceiling:.3f} for this one call (Sonnet 5 rates)"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the PR risk agent.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="poll forever")
    commands.add_parser("once", help="poll once")
    for name, text in (("dry-run", "show the request for a PR"), ("try", "call Claude for a PR")):
        cmd = commands.add_parser(name, help=text)
        cmd.add_argument("number", type=int)
        if name == "try":
            cmd.add_argument("--yes", action="store_true", help="really call the API (costs money)")
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for noisy in ("httpx", "httpx2"):  # one log line per request is noise
        logging.getLogger(noisy).setLevel(logging.WARNING)
    runner_mode = settings.orchestrator_mode
    try:
        gh = GitHubClient()
        runner = Runner(gh, StructuredLLM(), load_policy(), runner_mode)
        triage_runner = IssueRunner(gh, StructuredLLM(model=settings.triage_model), runner_mode)
        forecaster = ForecastRunner(runner_mode)
        planner = PlannerRunner(
            StructuredLLM(
                model=settings.planner_model, max_tokens=settings.planner_max_output_tokens
            ),
            runner_mode,
        )
    except GitHubError as err:
        raise SystemExit(str(err)) from err

    if args.command in ("dry-run", "try"):
        _look(runner, args)
    elif args.command == "once":
        print(
            {
                "pr_risk": runner.poll_once(),
                "triage": triage_runner.poll_once(),
                "forecaster": forecaster.poll_once(),
                "planner": planner.poll_once(),
            }
        )
    else:
        log.info(
            "risk, triage, forecaster and planner agents started in %s mode, polling every %ss",
            runner_mode,
            settings.poll_seconds,
        )
        while True:
            agents = (
                ("pr_risk", runner),
                ("triage", triage_runner),
                ("forecaster", forecaster),  # before the planner: it reads the saved forecast
                ("planner", planner),
            )
            for name, agent in agents:
                try:
                    summary = agent.poll_once()
                    if summary.get("assessed") or summary.get("errors"):
                        log.info("%s poll: %s", name, summary)
                except Exception:  # noqa: BLE001 - one bad poll must not stop the loop or the other agent
                    log.exception("%s poll failed", name)
            time.sleep(settings.poll_seconds)


def _look(runner: Runner, args) -> None:
    title, score, facts, user, description, diff = prepare(runner, args.number)
    sent = runner.llm.request_kwargs(SYSTEM_PROMPT, user, SCHEMA, "medium")
    print(f"PR #{args.number}: {title}")
    print(f"Rubric score {score.total}/100; model {sent['model']}, effort medium.")
    print("Request:", estimate(SYSTEM_PROMPT, user, sent["max_tokens"]))
    if args.command == "dry-run":
        print("Dry run: nothing was sent to Claude and nothing was written to GitHub.")
        return
    if not args.yes:
        print("Not sent. Add --yes to make the real API call.")
        return
    with SessionLocal() as db:
        pr = db.scalar(
            select(PullRequest).where(
                PullRequest.source == "github", PullRequest.number == args.number
            )
        )
        result = assess(
            db,
            pr,
            llm=runner.llm,
            policy=runner.policy,
            description=description,
            diff=diff,
            diff_char_limit=runner.diff_char_limit,
        )
    print(
        f"Status: {result.status}. Score {result.final_score}/100 (rubric {result.raw_score}, "
        f"adjustment {result.adjustment}) -> tier {result.assignment.tier}"
    )
    for reason in result.top_reasons:
        print(f"  - {reason}")
    if result.llm:
        u = result.llm
        print(
            f"Tokens: {u.input_tokens} in, {u.output_tokens} out, "
            f"{u.cache_read_tokens} from cache; {u.latency_ms} ms"
        )
    if result.error:
        print(f"Problem: {result.error}")
    print("Nothing was written to GitHub or the audit table.")


if __name__ == "__main__":
    main()
