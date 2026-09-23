"""Run the planner agent when the saved sprint forecast shows a slip.

It runs in the shared poll loop right after the forecaster, and drafts once per slipping sprint
forecast: a new forecast (the forecaster saves one when the sprint's work or the day changes) is
a new situation and gets a fresh draft; the same one never gets two. A failed call is retried up
to three times, five minutes apart, and at most MAX_PER_DAY calls are made per sprint per day,
so a sprint whose items churn all day can't run up the API bill.

Writes only the audit table (the proposal is its `output`); never GitHub, never an issue.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.plan_runner dry-run        # the exact request for today's sprint; calls nothing
    python -m sdlc.plan_runner try --yes      # one real call; prints the proposal and records
                                              # only a "trial" audit row (its tokens)
    python -m sdlc.plan_runner once           # what the poll loop does, once
"""

import argparse
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sdlc.agents.llm import StructuredLLM
from sdlc.agents.planner import (
    AGENT,
    AGENT_VERSION,
    PROMPT_HASH,
    PROMPT_VERSION,
    SCHEMA,
    SLIP_BELOW,
    SYSTEM_PROMPT,
    Proposal,
    build_prompt,
    is_slipping,
    propose,
    sprint_items,
    team,
)
from sdlc.audit import TRIAL, decisions_for, record_decision
from sdlc.db import SessionLocal
from sdlc.forecast import current_sprint, sprint_forecast
from sdlc.forecaster import SOURCE, latest
from sdlc.tables import AgentDecision, Forecast

MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=5)
MAX_PER_DAY = 4
INPUT_RATE, OUTPUT_RATE = 2.0, 10.0  # rough Sonnet 5 dollars per million tokens, for dry runs


def output_of(p: Proposal, forecast_row: Forecast) -> dict:
    out = {
        "sprint": forecast_row.subject,
        "forecast_id": forecast_row.id,
        "on_time_probability": forecast_row.on_time_probability,
    }
    if not p.ok:
        return out
    return {
        **out,
        "summary": p.summary,
        "options": list(p.options),
        "recommended": p.recommended,
        "confidence": p.confidence,
        "dropped": list(p.dropped),
        "request_id": p.llm.request_id if p.llm else None,
        "cache_read_tokens": p.llm.cache_read_tokens if p.llm else None,
    }


class PlannerRunner:
    def __init__(self, llm: StructuredLLM, mode: str):
        self.llm = llm
        self.mode = mode

    def poll_once(self, now: datetime | None = None) -> dict:
        if self.mode == "off":
            return {"mode": "off"}
        now = (now or datetime.now()).replace(microsecond=0)
        summary = {"mode": self.mode, "assessed": 0, "failed": 0}
        with SessionLocal() as db:
            state = self._handle(db, now, summary)
            db.commit()
        summary["state"] = state
        return summary

    def _handle(self, db: Session, now: datetime, summary: dict) -> str:
        today = now.date()
        sprint = current_sprint(db, today, SOURCE)
        if sprint is None:
            return "no sprint"
        row = latest(db, "sprint", sprint.name)
        if row is None or row.as_of != today:
            return "waiting for today's forecast"
        if not row.remaining_items or (row.on_time_probability or 0) >= SLIP_BELOW:
            return "on track"

        attempts = decisions_for(
            db,
            AGENT,
            subject_type="sprint",
            subject_source=row.source,
            subject_id=row.id,
            head_sha=row.inputs_hash[:40],
        )
        if any(d.status == "ok" for d in attempts):
            return "already proposed"
        if attempts and (
            len(attempts) >= MAX_ATTEMPTS or now - attempts[-1].created_at < RETRY_AFTER
        ):
            return "waiting to retry"
        if self._calls_today(db, now, sprint.name) >= MAX_PER_DAY:
            return "daily cap reached"

        # Recomputed rather than rebuilt from the saved row: same seed and inputs, same numbers.
        forecast = sprint_forecast(db, today, sprint=sprint, source=SOURCE, runs=row.runs)
        proposal = propose(db, sprint, forecast, llm=self.llm, source=SOURCE)
        record_decision(
            db,
            agent=AGENT,
            agent_version=AGENT_VERSION,
            subject_type="sprint",
            subject_source=row.source,
            subject_id=row.id,
            trigger="slip",
            now=now,
            head_sha=row.inputs_hash[:40],
            attempt=len(attempts) + 1,
            model_id=self.llm.model,
            prompt_version=PROMPT_VERSION,
            prompt_hash=PROMPT_HASH,
            inputs_digest={
                "remaining_items": forecast.remaining_items,
                "on_time_probability": round(forecast.on_time_probability, 3),
                "at_risk": [r.number for r in forecast.at_risk],
            },
            output=output_of(proposal, row),
            action_taken={"proposed": proposal.ok, "wrote": "audit row only"},
            status=proposal.status,
            error=proposal.error,
            latency_ms=proposal.llm.latency_ms if proposal.llm else None,
            input_tokens=proposal.llm.input_tokens if proposal.llm else None,
            output_tokens=proposal.llm.output_tokens if proposal.llm else None,
        )
        summary["assessed"] += 1
        summary["failed"] += 0 if proposal.ok else 1
        return "proposed" if proposal.ok else f"failed ({proposal.status})"

    @staticmethod
    def _calls_today(db: Session, now: datetime, sprint_name: str) -> int:
        start = datetime.combine(now.date(), datetime.min.time())
        forecast_ids = select(Forecast.id).where(
            Forecast.kind == "sprint", Forecast.subject == sprint_name
        )
        return db.scalar(
            select(func.count())
            .select_from(AgentDecision)
            .where(
                AgentDecision.agent == AGENT,
                AgentDecision.trigger != TRIAL,  # manual tries don't use up the loop's calls
                AgentDecision.created_at >= start,
                AgentDecision.subject_id.in_(forecast_ids),
            )
        )


def latest_proposal(db: Session, sprint_name: str) -> AgentDecision | None:
    """The newest planner decision about this sprint, successful or not (manual trials aside)."""
    forecast_ids = select(Forecast.id).where(
        Forecast.kind == "sprint", Forecast.subject == sprint_name
    )
    return db.scalar(
        select(AgentDecision)
        .where(
            AgentDecision.agent == AGENT,
            AgentDecision.trigger != TRIAL,
            AgentDecision.subject_id.in_(forecast_ids),
        )
        .order_by(AgentDecision.created_at.desc(), AgentDecision.id.desc())
        .limit(1)
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the planner agent.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("once", help="what the poll loop does, once")
    commands.add_parser("dry-run", help="show today's request; calls nothing")
    cmd = commands.add_parser("try", help="one real call; prints it, writes nothing")
    cmd.add_argument("--yes", action="store_true", help="really call the API (costs money)")
    args = parser.parse_args(argv)

    from sdlc.config import get_settings

    settings = get_settings()
    llm = StructuredLLM(model=settings.planner_model, max_tokens=settings.planner_max_output_tokens)
    if args.command == "once":
        print(PlannerRunner(llm, settings.orchestrator_mode).poll_once())
        return

    today = datetime.now().date()
    with SessionLocal() as db:
        sprint = current_sprint(db, today, SOURCE)
        if sprint is None:
            raise SystemExit("No simulated sprint is in progress today.")
        forecast = sprint_forecast(db, today, sprint=sprint, source=SOURCE)
        items = sprint_items(db, sprint, forecast)
        user = build_prompt(forecast, items, team(db, items, SOURCE))
        sent = llm.request_kwargs(SYSTEM_PROMPT, user, SCHEMA, "medium")
        tokens_in = (len(SYSTEM_PROMPT) + len(user) + len(str(SCHEMA))) // 2  # errs high
        ceiling = tokens_in * INPUT_RATE / 1e6 + sent["max_tokens"] * OUTPUT_RATE / 1e6
        print(f"{forecast.sprint}: {forecast.on_time_probability:.0%} chance on time; ", end="")
        print("slipping." if is_slipping(forecast) else "on track (the loop wouldn't call).")
        print(f"Model {sent['model']}, effort medium; about {tokens_in:,} input tokens, at most")
        print(f"{sent['max_tokens']:,} output: a ceiling of roughly ${ceiling:.3f} for this call.")
        if args.command == "dry-run":
            print("\n" + user + "\n\nDry run: nothing was sent to Claude.")
            return
        if not args.yes:
            print("Not sent. Add --yes to make the real API call.")
            return
        p = propose(db, sprint, forecast, llm=llm, source=SOURCE)
        saved = latest(db, "sprint", sprint.name)
        record_decision(
            db,
            agent=AGENT,
            agent_version=AGENT_VERSION,
            subject_type="sprint",
            subject_source=SOURCE,
            subject_id=saved.id if saved else 0,
            trigger=TRIAL,
            model_id=llm.model,
            prompt_version=PROMPT_VERSION,
            prompt_hash=PROMPT_HASH,
            output={"sprint": sprint.name, "summary": p.summary, "options": list(p.options)},
            action_taken={"trial": True},
            status=p.status,
            error=p.error,
            latency_ms=p.llm.latency_ms if p.llm else None,
            input_tokens=p.llm.input_tokens if p.llm else None,
            output_tokens=p.llm.output_tokens if p.llm else None,
        )
        db.commit()
    print(f"\nStatus: {p.status}." + (f" {p.error}" if p.error else ""))
    if p.ok:
        print(f"{p.summary}\nConfidence {p.confidence:.0%}.")
        for i, o in enumerate(p.options):
            star = "*" if i == p.recommended else " "
            to = f" -> {o['reassign_to']}" if o["reassign_to"] else ""
            print(f" {star} {o['action']}: {o['title']} (items {o['items']}{to})")
            print(f"     {o['rationale']}")
            if o["effect"]:
                e = o["effect"]
                print(
                    f"     effect: on-time {e['from']['on_time_probability']:.0%} -> "
                    f"{e['on_time_probability']:.0%}, P85 {e['from']['p85']} -> {e['p85']}"
                )
        for note in p.dropped:
            print(f"   dropped: {note}")
    if p.llm:
        print(f"Tokens: {p.llm.input_tokens} in, {p.llm.output_tokens} out; {p.llm.latency_ms} ms")
    print("Nothing was written to GitHub. The call was recorded as a trial audit row.")


if __name__ == "__main__":
    main()
