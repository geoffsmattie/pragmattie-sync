"""Human tier overrides: a person raises or lowers a PR's tier with a `/tier` comment.

    /tier T3
    /tier T1 copy-only change, checked locally

Rules (the blueprint's governance mechanics):
  - Raising is always accepted, reason optional, and sticks for the PR: later commits keep it.
  - Lowering needs a written reason (at least MIN_REASON characters), or it's rejected. An
    accepted lowering covers the commit it was made on only: a new push is new risk.
  - Nothing goes below a policy floor (Billing & Auth, schema migrations, pipeline/forecasting):
    floors are rules in policies/tiers.yaml, changed there, not argued down in a comment.
  - Every command, accepted or rejected, is an audit row with who, from, to and why.

Pure functions, no I/O: the runner reads the comments and records the rulings.
"""

import re
from dataclasses import dataclass

from sdlc.tiers import TIER_IDS

AGENT = "tier_override"  # the audit rows' agent name (a person acted; code ruled on it)
MIN_REASON = 10
COMMAND = re.compile(r"^[ \t]*/tier[ \t]+(T[0-3])\b[ \t]*[:\-–—]?[ \t]*(.*)$", re.I | re.M)


@dataclass(frozen=True)
class Command:
    comment_id: int
    actor: str
    tier: str
    reason: str
    url: str | None


@dataclass(frozen=True)
class Ruling:
    comment_id: int
    actor: str
    reason: str
    from_tier: str
    to_tier: str
    direction: str  # raise | lower | same
    accepted: bool
    why: str  # plain English, for the PR comment and the audit row
    head_sha: str  # the commit it was made on

    def as_record(self) -> dict:
        return {
            "comment_id": self.comment_id,
            "actor": self.actor,
            "reason": self.reason,
            "from": self.from_tier,
            "to": self.to_tier,
            "direction": self.direction,
            "accepted": self.accepted,
            "why": self.why,
            "head_sha": self.head_sha,
        }

    @classmethod
    def from_record(cls, r: dict) -> "Ruling":
        return cls(
            comment_id=r["comment_id"],
            actor=r["actor"],
            reason=r["reason"],
            from_tier=r["from"],
            to_tier=r["to"],
            direction=r["direction"],
            accepted=r["accepted"],
            why=r["why"],
            head_sha=r["head_sha"],
        )


def rank(tier: str) -> int:
    return TIER_IDS.index(tier)


def parse_commands(comments: list[dict], agent_markers: tuple[str, ...]) -> list[Command]:
    """The `/tier` commands in people's comments, oldest first. The agents' own comments (found
    by their markers) never count, even though they're written by the same account."""
    out = []
    for c in comments:
        body = c.get("body") or ""
        if any(marker in body for marker in agent_markers):
            continue
        match = COMMAND.search(body)
        if not match:
            continue
        out.append(
            Command(
                comment_id=c["id"],
                actor=(c.get("user") or {}).get("login") or "unknown",
                tier=match[1].upper(),
                reason=match[2].strip()[:500],
                url=c.get("html_url"),
            )
        )
    return out


def rule(command: Command, *, current: str, floor: str, head_sha: str) -> Ruling:
    """Accept or reject one command against the tier in force and the policy floor."""
    to = command.tier
    if rank(to) > rank(current):
        direction, accepted, why = "raise", True, f"Raised from {current} to {to}."
    elif rank(to) == rank(current):
        direction, accepted, why = "same", True, f"Already {to}; nothing changed."
    elif rank(to) < rank(floor):
        direction, accepted = "lower", False
        why = (
            f"Rejected: a policy floor keeps this PR at {floor} or above. Floors are set in "
            "policies/tiers.yaml, not by comment."
        )
    elif len(command.reason) < MIN_REASON:
        direction, accepted = "lower", False
        why = f"Rejected: lowering a tier needs a written reason, e.g. `/tier {to} <why>`."
    else:
        direction, accepted = "lower", True
        why = f"Lowered from {current} to {to}, for this commit only."
    return Ruling(
        comment_id=command.comment_id,
        actor=command.actor,
        reason=command.reason,
        from_tier=current,
        to_tier=to,
        direction=direction,
        accepted=accepted,
        why=why,
        head_sha=head_sha,
    )


def effective_tier(agent_tier: str, floor: str, rulings: list[Ruling], head_sha: str) -> str:
    """The tier in force for this commit: the agent's, then each accepted ruling in order (raises
    stick across commits, lowerings only on the commit they were made on), never below the floor."""
    tier = agent_tier
    for r in rulings:
        if not r.accepted:
            continue
        if r.direction == "raise" and rank(r.to_tier) > rank(tier):
            tier = r.to_tier
        elif r.direction == "lower" and r.head_sha == head_sha:
            tier = r.to_tier
    return tier if rank(tier) >= rank(floor) else floor


def describe(r: Ruling) -> str:
    """One line for the PR comment's override list."""
    said = f' "{r.reason}"' if r.reason else ""
    return f"- `/tier {r.to_tier}` by @{r.actor}{said}: {r.why}"
