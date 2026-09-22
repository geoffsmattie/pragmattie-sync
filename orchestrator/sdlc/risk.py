"""Look at the risk score: explain one PR's score and tier, or grade the rubric on the history.

Usage:
    python -m sdlc.risk explain 485 [--source synthetic] [--record]
    python -m sdlc.risk calibrate                 # grade this database's history
    python -m sdlc.risk calibrate --generated 30  # grade 30 generated histories, pooled

`explain --record` appends the decision to the audit table (sdlc_agent_decisions). Nothing here
changes a pull request or GitHub; it only reads, and records when asked.
"""

import argparse

from sdlc.approver import ApproverError, find_pull_request
from sdlc.audit import record_decision
from sdlc.calibration import calibrate, calibrate_many, facts_of, format_many, format_report
from sdlc.db import SessionLocal
from sdlc.governance import assign_tier
from sdlc.scoring import MAX_POINTS, compute_features, features_digest, score_features
from sdlc.tables import SOURCES
from sdlc.tiers import load_policy

AGENT = "pr_risk_rubric"  # stage one only; the Claude adjustment arrives with the agent
AGENT_VERSION = "rubric-v1"


def explain(db, number: int, source: str | None, record: bool) -> str:
    pr = find_pull_request(db, number, source)
    policy = load_policy()
    features = compute_features(db, pr)
    score = score_features(features)
    assignment = assign_tier(policy, score.total, facts_of(pr))

    lines = [f"PR #{pr.number} [{pr.source}] {pr.title[:70]}", "", "Signal               Points"]
    for name, points in score.signals.items():
        lines.append(f"{name:<20} {points:>3} / {MAX_POINTS[name]}")
    lines += ["", f"Score {score.total}/100 -> tier {assignment.tier}", *assignment.reasons]
    if record:
        decision = record_decision(
            db,
            agent=AGENT,
            agent_version=AGENT_VERSION,
            pr=pr,
            trigger="manual",
            inputs_digest=features_digest(features),
            raw_score=score.total,
            final_score=score.total,
            tier=assignment.tier,
            signals=score.signals,
            output={"reasons": list(assignment.reasons), "floors": list(assignment.floors)},
            status="ok",
        )
        db.commit()
        lines.append(f"Recorded as decision {decision.id} (audit table).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Explain and calibrate the PR risk score.")
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("explain", help="show one PR's score, tier and why")
    one.add_argument("number", type=int, help="pull request number")
    one.add_argument("--source", choices=SOURCES, help="needed if the number is ambiguous")
    one.add_argument("--record", action="store_true", help="append the decision to the audit table")
    grade = commands.add_parser(
        "calibrate", help="score every merged PR in the history and grade the rubric"
    )
    grade.add_argument(
        "--generated",
        type=int,
        metavar="N",
        help="instead grade N freshly generated histories, pooled (no database needed)",
    )
    args = parser.parse_args(argv)

    try:
        with SessionLocal() as db:
            if args.command == "explain":
                print(explain(db, args.number, args.source, args.record))
            elif args.generated:
                print(format_many(calibrate_many(load_policy(), args.generated)))
            else:
                print(format_report(calibrate(db, load_policy())))
    except ApproverError as err:
        raise SystemExit(str(err)) from err


if __name__ == "__main__":
    main()
