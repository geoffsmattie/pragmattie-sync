"""The test selector: which CI jobs a PR would need, and which of them look flaky.

Recommendation only (decided 2026-09-24). CI still runs every job on every PR; the selector says
what it would have run, and sdlc/suite_selector.py later reads the real CI result for that commit
to record whether a skipped job would have caught a failure. That record is its track record.

No Claude call: the choice is plain rules, so it costs nothing, repeats exactly in a demo and
explains every job in one line.
  - Changed paths map to the jobs in .github/workflows/ci.yml. Source code under apps/api or
    orchestrator also selects the migrations job, which runs `alembic check` and the seed/synth
    against MySQL, so a model change without a migration fails there.
  - A test-only change selects only its own service's job; docs and config select nothing.
  - Anything the rules don't recognise, and anything under .github/workflows, selects every job.
  - A tier whose policy says "full suite" (T2, T3), or a failed risk assessment, selects every job.
Flaky flags come from past CI runs, real and simulated; the flag says how much was simulated.

Each repository has its own CI jobs and folders (a `CIProfile`): v1's own repository and its
simulated history use `V1`; the agentic rebuild, which v1 also governs, uses `REBUILD`, whose
ci.yml has five jobs with different names. `profile_for(source)` picks one.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.changes import is_docs_or_config, is_test_file
from sdlc.signals.github import JOB_SUITES
from sdlc.tables import CIRun
from sdlc.tiers import Policy

AGENT = "test_selector"
AGENT_VERSION = "v1"

# The jobs in .github/workflows/ci.yml, by the suite names the collector stores them under.
CI_SUITES = ("api", "orchestrator", "migrations", "web")
SUITE_NAMES = {
    "api": "API",
    "orchestrator": "Orchestrator",
    "migrations": "Migrations",
    "web": "Web",
}

# (pattern, suites for source files, suites for test files), first match wins.
PATH_RULES = [
    (re.compile(r"^apps/api/alembic/"), ("api", "migrations"), ("api", "migrations")),
    (re.compile(r"^orchestrator/alembic/"), ("orchestrator", "migrations"), ("orchestrator",)),
    (re.compile(r"^apps/api/"), ("api", "migrations"), ("api",)),
    (re.compile(r"^orchestrator/"), ("orchestrator", "migrations"), ("orchestrator",)),
    (re.compile(r"^apps/web/"), ("web",), ("web",)),
]
CI_CONFIG = ".github/workflows/"


@dataclass(frozen=True)
class CIProfile:
    """One repository's CI: its suites in order, their display names, the ci.yml job name behind
    each suite, and the path rules ((pattern, source-file suites, test-file suites), first match
    wins)."""

    suites: tuple[str, ...]
    names: dict[str, str]
    jobs: dict[str, str]  # CI job name -> suite
    path_rules: tuple


V1 = CIProfile(CI_SUITES, SUITE_NAMES, JOB_SUITES, tuple(PATH_RULES))

# The agentic rebuild (pragmattie/pragmattie-sync-agentic): its .github/workflows/ci.yml jobs, and
# its folders (apps/crm-web and apps/insights-web, migrations under migrations/).
REBUILD = CIProfile(
    suites=("api", "orchestrator", "migrations", "web", "insights-web"),
    names={
        "api": "CRM API",
        "orchestrator": "Orchestrator",
        "migrations": "Migrations",
        "web": "CRM web",
        "insights-web": "Insights web",
    },
    jobs={
        "CRM API (lint + tests)": "api",
        "Orchestrator (lint + tests)": "orchestrator",
        "Migrations on MySQL": "migrations",
        "CRM web (tests + build)": "web",
        "Insights web (tests + build)": "insights-web",
    },
    path_rules=(
        (re.compile(r"^apps/api/migrations/"), ("api", "migrations"), ("api", "migrations")),
        (
            re.compile(r"^orchestrator/migrations/"),
            ("orchestrator", "migrations"),
            ("orchestrator",),
        ),
        (re.compile(r"^apps/api/"), ("api", "migrations"), ("api",)),
        (re.compile(r"^orchestrator/"), ("orchestrator", "migrations"), ("orchestrator",)),
        (re.compile(r"^apps/crm-web/"), ("web",), ("web",)),
        (re.compile(r"^apps/insights-web/"), ("insights-web",), ("insights-web",)),
    ),
)
PROFILES = {"agentic": REBUILD}


def profile_for(source: str) -> CIProfile:
    """The CI profile for a repository's rows: the rebuild's, or v1's (github and synthetic)."""
    return PROFILES.get(source, V1)


FLAKY_LOOKBACK = timedelta(days=60)
FLAKY_MIN_RUNS = 20
FLAKY_RATE = 0.03  # a flaky failure on at least 3% of runs


@dataclass(frozen=True)
class Flaky:
    suite: str
    rate: float
    runs: int
    simulated_runs: int


@dataclass(frozen=True)
class Selection:
    suites: tuple[str, ...]  # would run, in the profile's suite order
    reasons: dict[str, str]  # suite -> why it would run
    full: str | None = None  # why every job would run, when it would
    flaky: tuple[Flaky, ...] = field(default=())
    profile: CIProfile = field(default=V1, compare=False)

    @property
    def skipped(self) -> tuple[str, ...]:
        return tuple(s for s in self.profile.suites if s not in self.suites)

    def as_record(self) -> dict:
        return {
            "suites": list(self.suites),
            "skipped": list(self.skipped),
            "reasons": self.reasons,
            "full": self.full,
            "flaky": [f.__dict__ for f in self.flaky],
        }


def by_paths(paths: list[str], profile: CIProfile = V1) -> tuple[dict[str, str], str | None]:
    """(suite -> reason, why every job is needed or None) from the changed files alone."""
    reasons: dict[str, str] = {}
    for path in paths:
        if path.startswith(CI_CONFIG):
            return {}, f"it changes the CI workflow ({path})"
        rule = next((r for r in profile.path_rules if r[0].search(path)), None)
        if rule is None:
            if is_docs_or_config(path):
                continue
            return {}, f"no rule covers {path}"
        test = is_test_file(path)
        for suite in rule[2] if test else rule[1]:
            reasons.setdefault(suite, f"{'tests' if test else 'code'} changed in {path}")
    return reasons, None


def select_suites(
    paths: list[str],
    *,
    tier: str,
    policy: Policy,
    assessed: bool = True,
    profile: CIProfile = V1,
) -> Selection:
    """What this PR would need. Flaky flags are added by `with_flaky`."""
    if not assessed:
        full = "the risk agent couldn't score this commit, so nothing is skipped"
    elif policy.tiers[tier].tests.startswith("full suite"):
        full = f"{tier} runs the full suite ({policy.tiers[tier].tests})"
    else:
        full = None
    reasons, path_full = by_paths(paths, profile)
    full = full or path_full
    every = profile.suites
    if full:
        return Selection(every, {s: "every job runs" for s in every}, full, profile=profile)
    return Selection(tuple(s for s in every if s in reasons), reasons, profile=profile)


def flaky_suites(db: Session, now: datetime, profile: CIProfile = V1) -> tuple[Flaky, ...]:
    """CI jobs whose runs failed and then passed on a re-run often enough to call flaky."""
    rows = db.execute(
        select(CIRun.suite, CIRun.flaky, CIRun.source).where(
            CIRun.started_at >= now - FLAKY_LOOKBACK, CIRun.suite.in_(profile.suites)
        )
    ).all()
    counts = {suite: [0, 0, 0] for suite in profile.suites}  # runs, flaky, simulated
    for suite, flaky, source in rows:
        counts[suite][0] += 1
        counts[suite][1] += bool(flaky)
        counts[suite][2] += source == "synthetic"
    found = []
    for suite, (runs, flaky, simulated) in counts.items():
        if runs >= FLAKY_MIN_RUNS and flaky / runs >= FLAKY_RATE:
            found.append(Flaky(suite, round(flaky / runs, 3), runs, simulated))
    return tuple(found)


def with_flaky(selection: Selection, flaky: tuple[Flaky, ...]) -> Selection:
    """Keep the flags for the jobs this PR would run; a skipped job's flakiness doesn't matter."""
    return Selection(
        selection.suites,
        selection.reasons,
        selection.full,
        tuple(f for f in flaky if f.suite in selection.suites),
        selection.profile,
    )


# --- the PR comment's Tests section ----------------------------------------------------------

TESTS_START, TESTS_END = "<!-- tests -->", "<!-- /tests -->"


def _names(suites, names: dict[str, str]) -> str:
    return ", ".join(names[s] for s in suites) or "none"


def section_lines(selection: Selection) -> list[str]:
    names = selection.profile.names
    lines = [TESTS_START, "**Tests** (the test selector's recommendation; CI still runs every job)"]
    if selection.full:
        lines.append(f"- Would run every job: {selection.full}.")
    elif not selection.suites:
        lines.append("- Would run no jobs: only docs or config changed.")
    else:
        lines.append(f"- Would run: **{_names(selection.suites, names)}**")
        lines += [f"  - {names[s]}: {selection.reasons[s]}" for s in selection.suites]
        lines.append(f"- Would skip: {_names(selection.skipped, names)}")
    for f in selection.flaky:
        simulated = f", {f.simulated_runs} of them simulated" if f.simulated_runs else ""
        lines.append(
            f"- Possibly flaky: {names[f.suite]} failed and then passed on a re-run in "
            f"{f.rate:.0%} of {f.runs} recent runs{simulated}. Re-run it before assuming a real "
            "failure."
        )
    return [*lines, TESTS_END]


def replace_section(body: str, selection: Selection) -> str:
    """Swap the Tests section of an existing comment (after a person changes the tier)."""
    block = "\n".join(section_lines(selection))
    if TESTS_START not in body:
        return body
    return re.sub(
        rf"{re.escape(TESTS_START)}.*?{re.escape(TESTS_END)}",
        lambda _: block,
        body,
        count=1,
        flags=re.S,
    )
