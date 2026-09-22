"""Poll GitHub and run the triage agent on new or edited issues.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.issue_runner once            # one poll, then exit
    python -m sdlc.issue_runner dry-run 12      # exact request for issue #12; calls nothing
    python -m sdlc.issue_runner try 12 --yes    # one real call; prints the answer, writes nothing

Normally this runs inside `python -m sdlc.runner run`'s poll loop, alongside the PR risk agent, so
one container drives both agents on one schedule. This module's own `run`/`once` exist so triage
can be watched or tested on its own.

Trigger: an issue is triaged once per distinct title+body ("version"); editing the title or body
is a new version and gets a fresh attempt. Adding a `retriage` label forces another attempt even
if the content hasn't changed, and the label is removed once that attempt succeeds. A label or
comment the agent itself writes never changes the version, so the agent can't re-trigger itself.

Autonomy: the agent only ever adds or replaces labels and keeps one comment up to date. It never
closes an issue, assigns it, or edits its title or body. If a human has already set a dimension
label (module/type/priority/points) differently from what the agent last set, later triage runs
leave that dimension alone and record the difference as an override, rather than fighting the
human's correction.
"""

import argparse
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from sdlc.agents.github_effects import Effects
from sdlc.agents.llm import StructuredLLM
from sdlc.agents.triage import (
    AGENT,
    AGENT_VERSION,
    PROMPT_VERSION,
    SCHEMA,
    SYSTEM_PROMPT,
    assess,
    build_prompt,
)
from sdlc.agents.triage_comment import MARKER, Meta, content_version, render
from sdlc.audit import decisions_for, latest_decision, record_decision
from sdlc.config import get_settings
from sdlc.db import SessionLocal
from sdlc.github_client import GitHubClient, GitHubError
from sdlc.similarity import similar_issues
from sdlc.tiers import load_policy  # only to fail fast if the policy file is broken

DIMENSIONS = ("module", "type", "priority", "points")
NEEDS_INFO = (
    "needs-info",
    "F9A03F",
    "The triage agent needs more detail before it can classify this",
)
POSSIBLE_DUPLICATE = (
    "possible-duplicate",
    "B60205",
    "The triage agent found a similar existing issue",
)
RETRIAGE_LABEL = "retriage"

MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=5)

log = logging.getLogger("sdlc.issue_runner")


class IssueRunner:
    def __init__(self, gh: GitHubClient, llm: StructuredLLM, mode: str):
        self.gh = gh
        self.llm = llm
        self.mode = mode
        self.effects = Effects(gh, mode)

    def poll_once(self, now: datetime | None = None) -> dict:
        if self.mode == "off":
            return {"mode": "off"}
        now = now or datetime.now().replace(microsecond=0)
        summary = {"mode": self.mode, "issues": 0, "assessed": 0, "failed": 0, "errors": 0}
        for item in self.gh.get("/repos/{repo}/issues", state="open", per_page=100):
            if "pull_request" in item:  # the issues endpoint also returns PRs
                continue
            summary["issues"] += 1
            try:
                self._handle(item, now, summary)
            except (GitHubError, IntegrityError) as err:
                summary["errors"] += 1
                log.warning("Issue #%s: %s", item["number"], err)
        return summary

    def _handle(self, item: dict, now: datetime, summary: dict) -> None:
        number = item["number"]
        title, body = item["title"], item.get("body") or ""
        version = content_version(title, body)

        with SessionLocal() as db:
            labels = self.effects.read_labels(number)
            forced = RETRIAGE_LABEL in labels
            last = latest_decision(
                db, AGENT, subject_type="issue", subject_source="github", subject_id=number
            )
            attempts_here = decisions_for(
                db,
                AGENT,
                subject_type="issue",
                subject_source="github",
                subject_id=number,
                head_sha=version,
            )
            already_done = any(d.status == "ok" for d in attempts_here)
            # A retriage label is a deliberate one-time human action: it always runs, ignoring
            # both "already classified this version" and the automatic-failure backoff below,
            # which exist only to stop the agent hammering the API on its own repeated failures.
            if not forced and (already_done or not self._may_try(attempts_here, now)):
                return
            self._assess_and_publish(
                db, item, version, labels, last, len(attempts_here) + 1, now, summary, forced
            )
            db.commit()

    def _may_try(self, attempts: list, now: datetime) -> bool:
        if not attempts:
            return True
        return len(attempts) < MAX_ATTEMPTS and now - attempts[-1].created_at >= RETRY_AFTER

    def _assess_and_publish(
        self, db, item, version, labels, last, attempt, now, summary, forced
    ) -> None:
        number, title, body = item["number"], item["title"], item.get("body") or ""
        assessment = assess(db, llm=self.llm, title=title, body=body, labels=labels, number=number)
        summary["assessed"] += 1
        summary["failed"] += 0 if assessment.ok else 1

        overrides = self._overrides(labels, last)
        action_taken = {"mode": self.mode}
        if assessment.ok:
            for dim in DIMENSIONS:
                if dim in overrides:
                    continue
                value = getattr(assessment, "estimate_points" if dim == "points" else dim)
                action_taken[dim] = self.effects.set_dimension_label(number, dim, str(value))
            if assessment.needs_info:
                action_taken["needs_info"] = self.effects.add_label_if_absent(number, *NEEDS_INFO)
            if assessment.duplicate_of:
                action_taken["possible_duplicate"] = self.effects.add_label_if_absent(
                    number, *POSSIBLE_DUPLICATE
                )
            if forced:
                action_taken["retriage_label"] = self.effects.remove_label(number, RETRIAGE_LABEL)

        decision = record_decision(
            db,
            agent=AGENT,
            agent_version=AGENT_VERSION,
            subject_type="issue",
            subject_source="github",
            subject_id=number,
            trigger="retriage" if forced else ("edit" if last else "opened"),
            now=now,
            head_sha=version,
            attempt=attempt,
            model_id=self.llm.model,
            prompt_version=PROMPT_VERSION,
            output=_output_of(assessment),
            status=assessment.status,
            error=assessment.error,
            human_override={"dimensions": list(overrides)} if overrides else None,
            latency_ms=assessment.llm.latency_ms if assessment.llm else None,
            input_tokens=assessment.llm.input_tokens if assessment.llm else None,
            output_tokens=assessment.llm.output_tokens if assessment.llm else None,
        )
        meta = Meta(decision.id, version, tuple(overrides))
        body_text = render(assessment, meta)
        existing = self.effects.find_comment(number, marker=MARKER)
        action_taken["comment"] = self.effects.upsert_comment(number, body_text, existing)
        decision.action_taken = action_taken

    def _overrides(self, labels: list[str], last) -> list[str]:
        """Dimensions a human has changed since our last successful classification."""
        if last is None or not last.output:
            return []
        current = {dim: _label_value(labels, dim) for dim in DIMENSIONS}
        prior = {
            "module": last.output.get("module"),
            "type": last.output.get("type"),
            "priority": last.output.get("priority"),
            "points": (
                str(last.output["estimate_points"])
                if last.output.get("estimate_points") is not None
                else None
            ),
        }
        return [dim for dim in DIMENSIONS if prior[dim] is not None and current[dim] != prior[dim]]


def _label_value(labels: list[str], prefix: str) -> str | None:
    for name in labels:
        if name.startswith(f"{prefix}:"):
            return name.split(":", 1)[1]
    return None


def _output_of(a) -> dict | None:
    if not a.ok:
        return None
    return {
        "module": a.module,
        "type": a.type,
        "priority": a.priority,
        "estimate_points": a.estimate_points,
        "duplicate_of": a.duplicate_of,
        "confidence": a.confidence,
        "questions": list(a.questions),
        "similar_considered": len(a.similar),
    }


# --- commands that look before they leap -------------------------------------------------------


def prepare(runner: IssueRunner, number: int):
    item = runner.effects.read_issue(number)
    labels = runner.effects.read_labels(number)
    with SessionLocal() as db:
        candidates = similar_issues(
            db, item["title"], item.get("body") or "", exclude_number=number
        )
    user = build_prompt(item["title"], item.get("body") or "", labels, candidates)
    return item["title"], user


def estimate(system: str, user: str, max_tokens: int) -> str:
    tokens_in = (len(system) + len(user)) // 2
    ceiling = tokens_in * 1.0 / 1e6 + max_tokens * 5.0 / 1e6  # Haiku 4.5 rates
    return (
        f"about {tokens_in:,} input tokens; at most {max_tokens:,} output tokens; "
        f"a ceiling of roughly ${ceiling:.4f} for this one call (Haiku 4.5 rates)"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the triage agent.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("once", help="poll once")
    for name, text in (
        ("dry-run", "show the request for an issue"),
        ("try", "call Claude for an issue"),
    ):
        cmd = commands.add_parser(name, help=text)
        cmd.add_argument("number", type=int)
        if name == "try":
            cmd.add_argument("--yes", action="store_true", help="really call the API (costs money)")
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    load_policy()  # fail fast, same as sdlc.runner, even though triage doesn't gate on tiers
    try:
        runner = IssueRunner(
            GitHubClient(), StructuredLLM(model=settings.triage_model), settings.orchestrator_mode
        )
    except GitHubError as err:
        raise SystemExit(str(err)) from err

    if args.command in ("dry-run", "try"):
        _look(runner, args, settings)
    else:
        print(runner.poll_once())


def _look(runner: IssueRunner, args, settings) -> None:
    title, user = prepare(runner, args.number)
    sent = runner.llm.request_kwargs(SYSTEM_PROMPT, user, SCHEMA, "low")
    print(f"Issue #{args.number}: {title}")
    print(f"Model {sent['model']}, effort low.")
    print("Request:", estimate(SYSTEM_PROMPT, user, sent["max_tokens"]))
    if args.command == "dry-run":
        print("Dry run: nothing was sent to Claude and nothing was written to GitHub.")
        return
    if not args.yes:
        print("Not sent. Add --yes to make the real API call.")
        return
    labels = runner.effects.read_labels(args.number)
    with SessionLocal() as db:
        item = runner.effects.read_issue(args.number)
        result = assess(
            db,
            llm=runner.llm,
            title=item["title"],
            body=item.get("body") or "",
            labels=labels,
            number=args.number,
        )
    print(f"Status: {result.status}.")
    if result.ok:
        print(f"{result.module} / {result.type} ({result.priority}), {result.estimate_points}pt")
        print(f"confidence {result.confidence:.0%}: {result.rationale}")
        if result.questions:
            print("Questions:", "; ".join(result.questions))
        if result.duplicate_of:
            print(f"Possible duplicate of #{result.duplicate_of}")
    if result.llm:
        u = result.llm
        print(f"Tokens: {u.input_tokens} in, {u.output_tokens} out; {u.latency_ms} ms")
    if result.error:
        print(f"Problem: {result.error}")
    print("Nothing was written to GitHub or the audit table.")


if __name__ == "__main__":
    main()
