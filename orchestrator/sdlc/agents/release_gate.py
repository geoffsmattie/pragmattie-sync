"""The release gate: may this release deploy now? Decided by code from the tier policy, no Claude.

Pure functions, no I/O. The simulated history (sdlc/synth.py) and the real release runner
(sdlc/release_runner.py) gather the facts their own way and both ask `evaluate`.

A release is everything merged since the last deploy (you deploy `main`, not single PRs), so it
takes the highest tier among its PRs, and the tier's `release` setting in policies/tiers.yaml
decides what it needs:
  automatic   nothing: it deploys
  checks      CI passed on the release commit, no open incident in a module the release touches,
              and recent deploys' failure rate under the policy's maximum
  signoff     the checks, then a person signs off. For real releases that is GitHub's own
              "Approve deployment" button on the sign-off environment; in the simulated history
              it is a simulated sign-off, always labelled as such.

Verdicts: release (post `success`), hold (post `pending`: it clears by itself once the incident
closes, CI finishes or the sign-off arrives) and blocked (post `failure`: CI failed on the release
commit, so only a new commit can release). A PR's risk-gate isn't re-checked here: it is the merge
gate, and once a PR is merged its sign-off can't change.

Modes, as for risk-gate: in shadow mode the status always passes and says what enforce mode
would do. The description always starts with the tier ("T2 · ..."), which the deploy workflow
reads to pick the environment.
"""

from dataclasses import dataclass

from sdlc.tiers import TIER_IDS, Policy

AGENT = "release_gate"
AGENT_VERSION = "v1"
STATUS_CONTEXT = "release-gate"
DESCRIPTION_LIMIT = 140
STATES = {"release": "success", "hold": "pending", "blocked": "failure"}


@dataclass(frozen=True)
class OpenIncident:
    module: str
    number: int | None = None  # the GitHub issue, for real incidents
    title: str = ""


@dataclass(frozen=True)
class ReleaseFacts:
    tier: str
    prs: tuple[int, ...]
    modules: tuple[str, ...]
    ci: str = "passed"  # passed | failed | running
    open_incidents: tuple[OpenIncident, ...] = ()  # already limited to the release's modules
    recent_deploys: int = 0  # in the policy's failure-rate window
    failed_deploys: int = 0  # of those, how many caused an incident
    # Sign-off, for tiers that need it: True/False when the caller knows (the simulated
    # history), None when a person gives it outside the orchestrator (GitHub's environment
    # approval, which the deploy workflow waits for after this gate passes).
    signoff: bool | None = None


@dataclass(frozen=True)
class Verdict:
    verdict: str  # release | hold | blocked
    state: str  # what to post
    would_be: str  # what enforce mode would post
    reasons: tuple[str, ...]
    environment: str
    description: str


def release_tier(tiers: list[str | None], fallback: str) -> str:
    """The highest tier in the release; a PR with no tier counts as the fallback (fail closed)."""
    known = [t if t in TIER_IDS else fallback for t in tiers] or [fallback]
    return max(known, key=TIER_IDS.index)


def evaluate(policy: Policy, facts: ReleaseFacts, *, mode: str) -> Verdict:
    rules = policy.release
    need = policy.tiers[facts.tier].release
    environment = rules.signoff_environment if need == "signoff" else rules.environment
    reasons: list[str] = []
    verdict = "release"

    if need == "automatic":
        text = "Release: deploys automatically"
    else:
        if facts.ci == "failed":
            verdict = "blocked"
            reasons.append("CI failed on the release commit")
        elif facts.ci == "running":
            verdict = "hold"
            reasons.append("waiting for CI on the release commit")
        for incident in facts.open_incidents:
            verdict = "hold" if verdict == "release" else verdict
            ref = f" (#{incident.number})" if incident.number else ""
            reasons.append(f"open incident in {incident.module}{ref}")
        if (
            facts.recent_deploys >= rules.failure_min_deploys
            and facts.failed_deploys / facts.recent_deploys > rules.failure_max
        ):
            verdict = "hold" if verdict == "release" else verdict
            reasons.append(
                f"{facts.failed_deploys} of {facts.recent_deploys} deploys in "
                f"{rules.failure_window_days} days caused incidents "
                f"(over {rules.failure_max:.0%})"
            )
        if need == "signoff" and facts.signoff is False:
            verdict = "hold" if verdict == "release" else verdict
            reasons.append("waiting for sign-off (simulated)")

        if verdict == "blocked":
            text = "Blocked: " + "; ".join(reasons)
        elif verdict == "hold":
            text = "Held: " + "; ".join(reasons)
        elif need == "signoff" and facts.signoff is None:
            text = "Release: checks passed; approve the deployment in GitHub"
        else:
            text = "Release: checks passed" + (
                " and signed off (simulated)" if facts.signoff else ""
            )

    would_be = STATES[verdict]
    if mode == "shadow":
        state, description = "success", f"{facts.tier} · Shadow (would be {would_be}). {text}"
    else:
        state, description = would_be, f"{facts.tier} · {text}"
    return Verdict(
        verdict=verdict,
        state=state,
        would_be=would_be,
        reasons=tuple(reasons),
        environment=environment,
        description=description[:DESCRIPTION_LIMIT],
    )


def output_of(facts: ReleaseFacts, v: Verdict, **extra) -> dict:
    """The audit row's `output`: the verdict and everything it was decided from."""
    return {
        "verdict": v.verdict,
        "would_be": v.would_be,
        "reasons": list(v.reasons),
        "environment": v.environment,
        "prs": list(facts.prs),
        "modules": list(facts.modules),
        "ci": facts.ci,
        "open_incidents": [
            {"module": i.module, "number": i.number, "title": i.title} for i in facts.open_incidents
        ],
        "recent_deploys": facts.recent_deploys,
        "failed_deploys": facts.failed_deploys,
        "signoff": facts.signoff,
        **extra,
    }
