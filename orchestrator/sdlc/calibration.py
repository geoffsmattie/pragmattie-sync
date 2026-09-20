"""Grade the risk rubric against the engineering history before it is allowed to gate anything.

Every merged PR is scored as it would have been, then compared with what happened. The blueprint's
two bars: the T0 band contains no PR that caused an incident, and the top decile by score captures
a clear majority of the PRs that did. Precision and recall are reported at each tier threshold.

If a bar fails, the fix is to tune the weights and record the change, never to change the outcomes.

One history is a noisy judge: with about 14 incident PRs, the top decile caught anywhere from 4 to
10 of them depending only on the clock. So the rubric is also graded across many generated
histories (`calibrate_many`), where the bars are read on the pooled totals. Those thresholds were
fixed on 2026-09-20 before the first pooled run, so they can't be bent to fit the answer.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sdlc.db import Base
from sdlc.governance import Facts, assign_tier
from sdlc.scoring import score_pull_request
from sdlc.synth import build
from sdlc.tables import PullRequest
from sdlc.tiers import TIER_IDS, Policy

GENERATED_NOW = datetime(2026, 9, 18, 12, 0)  # fixed clock, so a pooled report is reproducible
T0_RATE_LIMIT = 0.25  # T0's incident rate must be at most this share of the overall rate
TOP_DECILE_CAPTURE = 0.5  # the top decile must catch more than this share, pooled


@dataclass(frozen=True)
class Scored:
    number: int
    score: int
    tier: str
    incident: bool


def facts_of(pr: PullRequest) -> Facts:
    return Facts(module=pr.module, touches_migration=pr.touches_migration, docs_only=pr.docs_only)


def score_history(db: Session, policy: Policy) -> list[Scored]:
    scored = []
    for pr in db.scalars(select(PullRequest).where(PullRequest.state == "merged")):
        score = score_pull_request(db, pr)
        tier = assign_tier(policy, score.total, facts_of(pr)).tier
        scored.append(Scored(pr.number, score.total, tier, pr.caused_incident))
    return scored


def calibrate(db: Session, policy: Policy) -> dict:
    scored = score_history(db, policy)
    incidents = [s for s in scored if s.incident]

    by_tier = {
        tier: {
            "prs": sum(s.tier == tier for s in scored),
            "incidents": sum(s.tier == tier and s.incident for s in scored),
        }
        for tier in TIER_IDS
    }

    decile = math.ceil(len(scored) / 10)
    top = sorted(scored, key=lambda s: (-s.score, s.number))[:decile]
    captured = sum(s.incident for s in top)

    thresholds = {}
    for tier in TIER_IDS[1:]:
        flagged = [s for s in scored if TIER_IDS.index(s.tier) >= TIER_IDS.index(tier)]
        hits = sum(s.incident for s in flagged)
        thresholds[tier] = {
            "flagged": len(flagged),
            "hits": hits,
            "precision": hits / len(flagged) if flagged else 0.0,
            "recall": hits / len(incidents) if incidents else 0.0,
        }

    return {
        "merged_prs": len(scored),
        "incident_prs": len(incidents),
        "by_tier": by_tier,
        "top_decile": {"prs": decile, "incidents_captured": captured},
        "thresholds": thresholds,
        "bars": {
            "t0_has_no_incidents": by_tier["T0"]["incidents"] == 0,
            "top_decile_captures_majority": bool(incidents) and captured > len(incidents) / 2,
        },
    }


def calibrate_many(policy: Policy, histories: int = 30, now: datetime = GENERATED_NOW) -> dict:
    """Grade the rubric on many generated histories (seeds 1..N) and pool the results."""
    runs = []
    for seed in range(1, histories + 1):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            build(db, now=now, seed=seed)
            runs.append(calibrate(db, policy))
        engine.dispose()
    return pool(runs)


def pool(runs: list[dict]) -> dict:
    prs = sum(r["merged_prs"] for r in runs)
    incidents = sum(r["incident_prs"] for r in runs)
    by_tier = {
        tier: {
            "prs": sum(r["by_tier"][tier]["prs"] for r in runs),
            "incidents": sum(r["by_tier"][tier]["incidents"] for r in runs),
        }
        for tier in TIER_IDS
    }
    captured = sum(r["top_decile"]["incidents_captured"] for r in runs)
    per_run = [
        r["top_decile"]["incidents_captured"] / r["incident_prs"] for r in runs if r["incident_prs"]
    ]

    thresholds = {}
    for tier in TIER_IDS[1:]:
        flagged = sum(r["thresholds"][tier]["flagged"] for r in runs)
        hits = sum(r["thresholds"][tier]["hits"] for r in runs)
        thresholds[tier] = {
            "flagged": flagged,
            "precision": hits / flagged if flagged else 0.0,
            "recall": hits / incidents if incidents else 0.0,
        }

    overall_rate = incidents / prs if prs else 0.0
    t0 = by_tier["T0"]
    t0_rate = t0["incidents"] / t0["prs"] if t0["prs"] else 0.0
    capture = captured / incidents if incidents else 0.0
    return {
        "histories": len(runs),
        "merged_prs": prs,
        "incident_prs": incidents,
        "by_tier": by_tier,
        "overall_rate": overall_rate,
        "t0_rate": t0_rate,
        "histories_with_no_t0_incident": sum(r["by_tier"]["T0"]["incidents"] == 0 for r in runs),
        "top_decile_capture": capture,
        "top_decile_capture_min": min(per_run, default=0.0),
        "top_decile_capture_max": max(per_run, default=0.0),
        "histories_where_top_decile_wins": sum(c > TOP_DECILE_CAPTURE for c in per_run),
        "thresholds": thresholds,
        "bars": {
            "t0_rate_at_most_a_quarter_of_overall": t0_rate <= T0_RATE_LIMIT * overall_rate,
            "top_decile_captures_majority_pooled": capture > TOP_DECILE_CAPTURE,
        },
    }


def _mark(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def format_many(report: dict) -> str:
    n = report["histories"]
    lines = [
        f"{n} generated histories pooled: {report['merged_prs']} merged PRs, "
        f"{report['incident_prs']} caused an incident ({report['overall_rate']:.1%}).",
        "",
        "Tier    PRs  Incidents   Rate",
    ]
    for tier, row in report["by_tier"].items():
        rate = row["incidents"] / row["prs"] if row["prs"] else 0.0
        lines.append(f"{tier}  {row['prs']:>5}  {row['incidents']:>9}  {rate:>6.2%}")
    lines += [
        "",
        f"T0 had no incident PR in {report['histories_with_no_t0_incident']} of {n} histories.",
        f"Top decile catches {report['top_decile_capture']:.0%} of incident PRs pooled "
        f"(one history ranged {report['top_decile_capture_min']:.0%} to "
        f"{report['top_decile_capture_max']:.0%}; it caught a majority in "
        f"{report['histories_where_top_decile_wins']} of {n}).",
        "",
        "Threshold  Flagged  Precision  Recall",
    ]
    for tier, row in report["thresholds"].items():
        flagged, precision, recall = row["flagged"], row["precision"], row["recall"]
        lines.append(f"{tier}+       {flagged:>6}     {precision:>6.1%}  {recall:>6.1%}")
    bars = report["bars"]
    quarter = _mark(bars["t0_rate_at_most_a_quarter_of_overall"])
    majority = _mark(bars["top_decile_captures_majority_pooled"])
    lines += [
        "",
        f"Bar 1 - T0 incident rate at most {T0_RATE_LIMIT:.0%} of the overall rate "
        f"({report['t0_rate']:.2%} vs {report['overall_rate']:.2%}): {quarter}",
        f"Bar 2 - top decile catches more than {TOP_DECILE_CAPTURE:.0%} of incident PRs: "
        f"{majority}",
    ]
    return "\n".join(lines)


def format_report(report: dict) -> str:
    def mark(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    lines = [
        f"Scored {report['merged_prs']} merged PRs; {report['incident_prs']} caused an incident.",
        "",
        "Tier   PRs  Incidents",
    ]
    for tier, row in report["by_tier"].items():
        lines.append(f"{tier}   {row['prs']:>4}  {row['incidents']:>4}")
    top = report["top_decile"]
    lines += [
        "",
        f"Top decile ({top['prs']} PRs) captures {top['incidents_captured']} of "
        f"{report['incident_prs']} incident PRs.",
        "",
        "Threshold  Flagged  Precision  Recall",
    ]
    for tier, row in report["thresholds"].items():
        flagged, precision, recall = row["flagged"], row["precision"], row["recall"]
        lines.append(f"{tier}+        {flagged:>4}     {precision:>6.1%}  {recall:>6.1%}")
    bars = report["bars"]
    no_t0 = mark(bars["t0_has_no_incidents"])
    majority = mark(bars["top_decile_captures_majority"])
    lines += [
        "",
        f"Bar 1 - no incident PR in the T0 band: {no_t0}",
        f"Bar 2 - top decile captures most incident PRs: {majority}",
    ]
    return "\n".join(lines)
