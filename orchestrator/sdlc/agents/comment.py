"""The single PR comment the risk agent keeps up to date, and the sign-off boxes inside it.

The boxes are the human's half of the gate. GitHub won't let a PR's author approve their own PR,
so with one human on the repo the sign-off is a tick-box in this comment, read back on every poll.
The comment is written by the token's owner, so only that account (or a repo admin) can edit it.
A new commit gets a fresh comment body with the boxes cleared: a stale tick never carries over.
"""

import re
from dataclasses import dataclass

from sdlc.agents.gate import Approvals, Gate, requirements
from sdlc.agents.pr_risk import Assessment
from sdlc.scoring import MAX_POINTS
from sdlc.tiers import Policy

MARKER = "<!-- pragmattie-risk-gate -->"
SIGNOFF_TEXT = "**Human sign-off:** I have reviewed this change"
QA_TEXT = "**Manual QA done:** I have exercised this change by hand"


def comment_head(body: str) -> str | None:
    """The commit a comment was written for."""
    match = re.search(r"<!-- head:(\w+) -->", body)
    return match.group(1) if match else None


def read_ticks(body: str, head_sha: str) -> tuple[bool, bool]:
    """(sign-off ticked, manual QA ticked) for `head_sha`. Ticks on an older commit don't count."""
    if comment_head(body) != head_sha:
        return False, False

    def ticked(label: str) -> bool:
        return bool(re.search(rf"- \[[xX]\] \*\*{re.escape(label)}", body))

    return ticked("Human sign-off"), ticked("Manual QA done")


def refresh(body: str, gate: Gate, simulated_approved: bool) -> str:
    """Bring the live parts of an existing comment up to date without rewriting the review."""
    state = "approved" if simulated_approved else "waiting"
    body = re.sub(
        r"(- Simulated second approval: \*\*)(approved|waiting)(\*\*)", rf"\g<1>{state}\g<3>", body
    )
    return re.sub(r"(would do: \*\*)\w+(\*\*)", rf"\g<1>{gate.would_be}\g<2>", body)


def box(checked: bool) -> str:
    return "[x]" if checked else "[ ]"


@dataclass(frozen=True)
class Meta:
    decision_id: int | None
    mode: str
    approver_name: str
    head_sha: str


def render(
    assessment: Assessment,
    gate: Gate,
    approvals: Approvals,
    policy: Policy,
    meta: Meta,
) -> str:
    tier = assessment.assignment.tier
    need = requirements(policy, tier)
    lines = [
        MARKER,
        f"<!-- head:{meta.head_sha} -->",
        f"## Risk review: {tier} ({policy.tiers[tier].name})",
    ]

    if meta.mode == "shadow":
        lines += [
            "",
            f"> **Shadow mode.** This check always passes for now. It shows what enforce mode "
            f"would do: **{gate.would_be}**.",
        ]

    if assessment.ok:
        moved = assessment.adjustment or 0
        clamp_note = " (limited to the +/-15 maximum)" if assessment.clamped else ""
        lines += [
            "",
            f"**Score {assessment.final_score}/100**: rubric {assessment.raw_score}, "
            f"model adjustment {moved:+d}{clamp_note}.",
            "",
            "**Why**",
            *[f"{i}. {reason}" for i, reason in enumerate(assessment.top_reasons, 1)],
        ]
        if assessment.justification:
            lines += ["", f"_{assessment.justification}_"]
        if assessment.test_gaps:
            lines += ["", "**Tests that look missing**", *[f"- {g}" for g in assessment.test_gaps]]
    else:
        lines += [
            "",
            f"**The risk agent could not score this PR** ({assessment.status}). "
            f"It is treated as {tier} and the check fails closed. It will try again shortly.",
        ]
    if assessment.assignment.reasons:
        lines += ["", *[f"- {reason}" for reason in assessment.assignment.reasons]]

    lines += ["", "**What this tier needs**"]
    if not any(need.values()):
        lines.append("- Nothing. A person doesn't need to act.")
    if need["signoff"]:
        lines.append(f"- {box(approvals.signoff)} {SIGNOFF_TEXT}")
    if need["manual_qa"]:
        lines.append(f"- {box(approvals.qa_done)} {QA_TEXT}")
    if need["simulated_second"]:
        state = "approved" if approvals.simulated_approved else "waiting"
        lines.append(
            f"- Simulated second approval: **{state}** ({meta.approver_name}, controlled by the "
            "repo owner; not a real second person)"
        )

    lines += [
        "",
        "<details><summary>Signal points</summary>",
        "",
        "| Signal | Points |",
        "| --- | --- |",
    ]
    lines += [
        f"| {name} | {points} / {MAX_POINTS[name]} |" for name, points in assessment.signals.items()
    ]
    lines += ["", "</details>"]

    footer = [f"decision {meta.decision_id}" if meta.decision_id else "not recorded"]
    if assessment.llm:
        footer += [
            assessment.llm.model,
            f"{assessment.llm.input_tokens + assessment.llm.output_tokens} tokens",
        ]
    lines += ["", "<sub>" + " · ".join(footer) + " · PragMattie Sync demo</sub>"]
    return "\n".join(lines)
