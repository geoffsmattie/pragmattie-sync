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
from sdlc.tiers import TIER_IDS, Policy

MARKER = "<!-- pragmattie-risk-gate -->"
OVERRIDES_START, OVERRIDES_END = "<!-- overrides -->", "<!-- /overrides -->"
NEEDS_HEADING = "**What this tier needs**"
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


def heading(policy: Policy, tier: str, agent_tier: str) -> str:
    by_person = ""
    if tier != agent_tier:
        moved = "raised" if TIER_IDS.index(tier) > TIER_IDS.index(agent_tier) else "lowered"
        by_person = f", {moved} from {agent_tier} by a person"
    return f"## Risk review: {tier} ({policy.tiers[tier].name}{by_person})"


def needs_lines(policy: Policy, tier: str, approvals: Approvals, approver_name: str) -> list[str]:
    need = requirements(policy, tier)
    lines = [NEEDS_HEADING]
    if not any(need.values()):
        lines.append("- Nothing. A person doesn't need to act.")
    if need["signoff"]:
        lines.append(f"- {box(approvals.signoff)} {SIGNOFF_TEXT}")
    if need["manual_qa"]:
        lines.append(f"- {box(approvals.qa_done)} {QA_TEXT}")
    if need["simulated_second"]:
        state = "approved" if approvals.simulated_approved else "waiting"
        lines.append(
            f"- Simulated second approval: **{state}** ({approver_name}, controlled by the "
            "repo owner; not a real second person)"
        )
    return lines


def overrides_block(override_lines: list[str]) -> list[str]:
    if not override_lines:
        return [OVERRIDES_START, OVERRIDES_END]
    return [
        OVERRIDES_START,
        "**Tier overrides** (raise with `/tier T3`; lower with `/tier T1 <written reason>`)",
        *override_lines,
        OVERRIDES_END,
    ]


def retier(
    body: str,
    policy: Policy,
    *,
    tier: str,
    agent_tier: str,
    approvals: Approvals,
    approver_name: str,
    override_lines: list[str],
) -> str:
    """Rewrite an existing comment's heading, tier needs and override list for the tier in force,
    keeping everything else (the review, the score, any ticks) as it is."""
    body = re.sub(
        r"^## Risk review: .*$",
        lambda _: heading(policy, tier, agent_tier),
        body,
        count=1,
        flags=re.M,
    )
    needs = "\n".join(needs_lines(policy, tier, approvals, approver_name))
    body = re.sub(
        rf"{re.escape(NEEDS_HEADING)}.*?(?=\n\n<details>)",
        lambda _: needs,
        body,
        count=1,
        flags=re.S,
    )
    block = "\n".join(overrides_block(override_lines))
    if OVERRIDES_START in body:
        return re.sub(
            rf"{re.escape(OVERRIDES_START)}.*?{re.escape(OVERRIDES_END)}",
            lambda _: block,
            body,
            count=1,
            flags=re.S,
        )
    return body.replace(NEEDS_HEADING, block + "\n\n" + NEEDS_HEADING, 1)


def render(
    assessment: Assessment,
    gate: Gate,
    approvals: Approvals,
    policy: Policy,
    meta: Meta,
    *,
    tier: str | None = None,
    override_lines: list[str] | None = None,
    tests: list[str] | None = None,
) -> str:
    """The whole comment. `tier` is the tier in force when a person has overridden the agent's;
    `tests` is the test selector's section (sdlc/agents/test_select.py)."""
    agent_tier = assessment.assignment.tier
    tier = tier or agent_tier
    lines = [
        MARKER,
        f"<!-- head:{meta.head_sha} -->",
        heading(policy, tier, agent_tier),
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
    if tests:
        lines += ["", *tests]

    lines += ["", *overrides_block(override_lines or [])]
    lines += ["", *needs_lines(policy, tier, approvals, meta.approver_name)]

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
