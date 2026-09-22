"""The `risk-gate` status: what state a PR's check should show, decided by code from the tier.

Pure functions, no I/O. The states are GitHub commit-status states: success, pending, failure.

What each tier needs comes from policies/tiers.yaml:
  humans >= 1   a human sign-off (Geoff ticks the box in the risk comment)
  humans >= 2   also the simulated second approver (approvers.yaml); both are Geoff, but the
                second is recorded as simulated and never presented as a real second person
  manual QA     a second box, ticked when the tier's tests say "manual QA"
The agent never passes a check on its own judgment above T0: for the other tiers it only relays
the humans' sign-off once it is present.

Modes: in shadow mode the check always passes and only says what enforce mode would do, so a
stopped or misbehaving agent can't block a merge while it is being proven.
"""

from dataclasses import dataclass

from sdlc.tiers import Policy

DESCRIPTION_LIMIT = 140  # GitHub truncates a status description beyond this


@dataclass(frozen=True)
class Approvals:
    signoff: bool = False  # the human sign-off box is ticked
    qa_done: bool = False  # the manual QA box is ticked
    simulated_approved: bool = False  # the simulated second approver has approved


@dataclass(frozen=True)
class Gate:
    state: str  # what to post: success | pending | failure
    would_be: str  # what enforce mode would post
    missing: tuple[str, ...]
    description: str


def requirements(policy: Policy, tier: str) -> dict[str, bool]:
    """What this tier needs from people, as booleans the comment and the gate both read."""
    t = policy.tiers[tier]
    return {
        "signoff": t.humans >= 1,
        "simulated_second": t.humans >= 2,
        "manual_qa": "manual QA" in t.tests,
    }


def missing_for(policy: Policy, tier: str, approvals: Approvals) -> tuple[str, ...]:
    need = requirements(policy, tier)
    missing = []
    if need["signoff"] and not approvals.signoff:
        missing.append("human sign-off")
    if need["manual_qa"] and not approvals.qa_done:
        missing.append("manual QA")
    if need["simulated_second"] and not approvals.simulated_approved:
        missing.append("simulated second approval")
    return tuple(missing)


def evaluate(policy: Policy, tier: str, *, ok: bool, approvals: Approvals, mode: str) -> Gate:
    """The status for a PR at `tier`. `ok` is False when the risk agent failed: fail closed."""
    if not ok:
        would_be, missing = "failure", ("a successful risk assessment",)
        note = f"{tier} fallback: the risk agent failed, so this fails closed"
    else:
        missing = missing_for(policy, tier, approvals)
        would_be = "pending" if missing else "success"
        need = ", ".join(missing)
        note = f"{tier}: waiting for {need}" if missing else f"{tier}: requirements met"

    if mode == "shadow":
        state = "success"
        description = f"Shadow mode (would be {would_be}). {note}"
    else:
        state = would_be
        description = note
    return Gate(state, would_be, missing, description[:DESCRIPTION_LIMIT])
