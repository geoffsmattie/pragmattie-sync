"""Grade the risk rubric against the engineering history before it is allowed to gate anything.

Every merged PR is scored as it would have been, then compared with what happened. The blueprint's
two bars: the T0 band contains no PR that caused an incident, and the top decile by score captures
a clear majority of the PRs that did. Precision and recall are reported at each tier threshold.

If a bar fails, the fix is to tune the weights and record the change, never to change the outcomes.
"""

import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.governance import Facts, assign_tier
from sdlc.scoring import score_pull_request
from sdlc.tables import PullRequest
from sdlc.tiers import TIER_IDS, Policy


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
