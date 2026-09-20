"""Turn a risk score into a governance tier: the score's band, raised by floors, capped for docs.

Rules (from policies/tiers.yaml, so they change without code):
  - the score falls in a band (0-19 T0, 20-49 T1, 50-79 T2, 80-100 T3);
  - floors set a minimum tier whatever the score says, and the highest match wins;
  - a docs-or-config-only PR is capped at T0 unless a floor applies.
If the agent fails, `fallback_assignment` gives the floor tier, or the fallback tier (T2).
Raising a tier is always allowed; lowering one is a human override recorded elsewhere.
"""

from dataclasses import dataclass

from sdlc.tiers import TIER_IDS, Policy, Rule


@dataclass(frozen=True)
class Facts:
    """What the floors and caps look at."""

    module: str | None
    touches_migration: bool
    docs_only: bool


@dataclass(frozen=True)
class Assignment:
    tier: str
    score_tier: str | None  # the band the score alone gives; None when there was no score
    floors: tuple[str, ...]  # names of the floors that matched
    capped_by: str | None  # name of the cap that lowered the tier, if any
    reasons: tuple[str, ...]  # plain English, for the PR comment and the audit row


def matches(rule: Rule, facts: Facts) -> bool:
    checks = {
        "modules": lambda wanted: facts.module in wanted,
        "touches_migration": lambda wanted: facts.touches_migration == wanted,
        "docs_only": lambda wanted: facts.docs_only == wanted,
    }
    return all(checks[key](wanted) for key, wanted in rule.when.items())


def _highest(tiers: list[str]) -> str:
    return max(tiers, key=TIER_IDS.index)


def band_for(policy: Policy, score: int) -> str:
    tier = policy.bands[0][1]
    for minimum, band_tier in policy.bands:
        if score >= minimum:
            tier = band_tier
    return tier


def assign_tier(policy: Policy, score: int, facts: Facts) -> Assignment:
    score_tier = band_for(policy, score)
    floors = [r for r in policy.floors if matches(r, facts)]
    tier = _highest([score_tier, *(r.tier for r in floors)])
    reasons = [f"Risk score {score} is in the {score_tier} band."]
    reasons += [f"Floor '{r.name}' sets a minimum of {r.tier}." for r in floors]

    capped_by = None
    if not floors:
        for cap in policy.caps:
            if matches(cap, facts) and TIER_IDS.index(cap.tier) < TIER_IDS.index(tier):
                tier, capped_by = cap.tier, cap.name
                reasons.append(f"Cap '{cap.name}' limits it to {cap.tier}.")
    return Assignment(tier, score_tier, tuple(r.name for r in floors), capped_by, tuple(reasons))


def fallback_assignment(policy: Policy, facts: Facts, why: str) -> Assignment:
    """The tier to use when the agent errors or times out: never fail open."""
    floors = [r for r in policy.floors if matches(r, facts)]
    tier = _highest([r.tier for r in floors]) if floors else policy.fallback_tier
    reasons = (f"{why} Falling back to {tier}.",)
    return Assignment(tier, None, tuple(r.name for r in floors), None, reasons)
