"""Load and validate the governance tier policy (orchestrator/policies/tiers.yaml).

The policy is data, so thresholds, floors and approvals can change without code. Loading fails
loudly on a mistake (an unknown tier, bands out of order) rather than gating PRs on a bad file.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

POLICY = Path(__file__).resolve().parent.parent / "policies" / "tiers.yaml"
TIER_IDS = ("T0", "T1", "T2", "T3")  # lowest to highest
AGENT_CHECKS = ("passes_alone", "passes_after_approvals", "reports_only")
RELEASE_MODES = ("automatic", "checks", "signoff")  # what the release gate asks of a tier
WHEN_KEYS = {"modules", "touches_migration", "docs_only"}


class PolicyError(Exception):
    """The tier policy file is missing something or contradicts itself."""


@dataclass(frozen=True)
class Tier:
    id: str
    name: str
    humans: int
    senior_human: bool
    code_owner: bool
    tests: str
    deploy: str
    agent_check: str
    release: str  # automatic | checks | signoff


@dataclass(frozen=True)
class ReleaseRules:
    environment: str
    signoff_environment: str
    failure_window_days: int
    failure_max: float
    failure_min_deploys: int
    synthetic_signoff_hours: float


@dataclass(frozen=True)
class Rule:
    """A floor or a cap: `tier` applies when every condition in `when` holds."""

    name: str
    tier: str
    when: dict


@dataclass(frozen=True)
class Policy:
    bands: tuple[tuple[int, str], ...]  # (minimum score, tier), ascending
    floors: tuple[Rule, ...]
    caps: tuple[Rule, ...]
    fallback_tier: str
    tiers: dict[str, Tier]
    release: ReleaseRules


def _tier_id(value, where: str) -> str:
    if value not in TIER_IDS:
        raise PolicyError(f"{where}: unknown tier {value!r}; expected one of {TIER_IDS}")
    return value


def _rules(items, kind: str) -> tuple[Rule, ...]:
    rules = []
    for item in items or []:
        where = f"{kind} {item.get('name', '?')!r}"
        when = item.get("when") or {}
        if not when or not set(when) <= WHEN_KEYS:
            raise PolicyError(f"{where}: `when` must use only {sorted(WHEN_KEYS)}")
        rules.append(Rule(item["name"], _tier_id(item.get("tier"), where), when))
    return tuple(rules)


def load_policy(path: Path = POLICY) -> Policy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    bands = tuple((int(b["min"]), _tier_id(b["tier"], "score_bands")) for b in raw["score_bands"])
    minimums = [minimum for minimum, _ in bands]
    if minimums[0] != 0 or minimums != sorted(set(minimums)) or minimums[-1] > 100:
        raise PolicyError("score_bands: minimums must start at 0 and rise strictly, up to 100")
    if [tier for _, tier in bands] != list(TIER_IDS):
        raise PolicyError(f"score_bands: list each of {TIER_IDS} once, rising with the score")

    tiers = {}
    for tier_id in TIER_IDS:
        if tier_id not in raw["tiers"]:
            raise PolicyError(f"tiers: {tier_id} is not defined")
        t = raw["tiers"][tier_id]
        if t["agent_check"] not in AGENT_CHECKS:
            raise PolicyError(f"tiers.{tier_id}: agent_check must be one of {AGENT_CHECKS}")
        if not isinstance(t["humans"], int) or t["humans"] < 0:
            raise PolicyError(f"tiers.{tier_id}: humans must be a whole number, 0 or more")
        if t.get("release") not in RELEASE_MODES:
            raise PolicyError(f"tiers.{tier_id}: release must be one of {RELEASE_MODES}")
        tiers[tier_id] = Tier(
            id=tier_id,
            name=t["name"],
            humans=t["humans"],
            senior_human=bool(t["senior_human"]),
            code_owner=bool(t["code_owner"]),
            tests=t["tests"],
            deploy=t["deploy"],
            agent_check=t["agent_check"],
            release=t["release"],
        )
    if [tiers[t].release for t in TIER_IDS] != sorted(
        (tiers[t].release for t in TIER_IDS), key=RELEASE_MODES.index
    ):
        raise PolicyError("tiers: a higher tier can't ask less of a release than a lower one")

    gate = raw.get("release_gate") or {}
    rate = gate.get("failure_rate") or {}
    try:
        release = ReleaseRules(
            environment=str(gate["environment"]),
            signoff_environment=str(gate["signoff_environment"]),
            failure_window_days=int(rate["window_days"]),
            failure_max=float(rate["max"]),
            failure_min_deploys=int(rate["min_deploys"]),
            synthetic_signoff_hours=float(gate["synthetic_signoff_hours"]),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise PolicyError(f"release_gate: missing or invalid setting ({err})") from err
    if release.environment == release.signoff_environment:
        raise PolicyError("release_gate: the sign-off environment must be a separate environment")
    if not 0 <= release.failure_max <= 1 or release.failure_window_days < 1:
        raise PolicyError("release_gate: failure_rate needs window_days >= 1 and max from 0 to 1")

    return Policy(
        bands=bands,
        floors=_rules(raw.get("floors"), "floor"),
        caps=_rules(raw.get("caps"), "cap"),
        fallback_tier=_tier_id(raw["fallback_tier"], "fallback_tier"),
        tiers=tiers,
        release=release,
    )
