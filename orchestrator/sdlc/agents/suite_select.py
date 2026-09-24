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
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.changes import is_docs_or_config, is_test_file
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
    suites: tuple[str, ...]  # would run, in CI_SUITES order
    reasons: dict[str, str]  # suite -> why it would run
    full: str | None = None  # why every job would run, when it would
    flaky: tuple[Flaky, ...] = field(default=())

    @property
    def skipped(self) -> tuple[str, ...]:
        return tuple(s for s in CI_SUITES if s not in self.suites)

    def as_record(self) -> dict:
        return {
            "suites": list(self.suites),
            "skipped": list(self.skipped),
            "reasons": self.reasons,
            "full": self.full,
            "flaky": [f.__dict__ for f in self.flaky],
        }


def by_paths(paths: list[str]) -> tuple[dict[str, str], str | None]:
    """(suite -> reason, why every job is needed or None) from the changed files alone."""
    reasons: dict[str, str] = {}
    for path in paths:
        if path.startswith(CI_CONFIG):
            return {}, f"it changes the CI workflow ({path})"
        rule = next((r for r in PATH_RULES if r[0].search(path)), None)
        if rule is None:
            if is_docs_or_config(path):
                continue
            return {}, f"no rule covers {path}"
        test = is_test_file(path)
        for suite in rule[2] if test else rule[1]:
            reasons.setdefault(suite, f"{'tests' if test else 'code'} changed in {path}")
    return reasons, None


def select_suites(
    paths: list[str], *, tier: str, policy: Policy, assessed: bool = True
) -> Selection:
    """What this PR would need. Flaky flags are added by `with_flaky`."""
    if not assessed:
        full = "the risk agent couldn't score this commit, so nothing is skipped"
    elif policy.tiers[tier].tests.startswith("full suite"):
        full = f"{tier} runs the full suite ({policy.tiers[tier].tests})"
    else:
        full = None
    reasons, path_full = by_paths(paths)
    full = full or path_full
    if full:
        return Selection(CI_SUITES, {s: "every job runs" for s in CI_SUITES}, full)
    return Selection(tuple(s for s in CI_SUITES if s in reasons), reasons)


def flaky_suites(db: Session, now: datetime) -> tuple[Flaky, ...]:
    """CI jobs whose runs failed and then passed on a re-run often enough to call flaky."""
    rows = db.execute(
        select(CIRun.suite, CIRun.flaky, CIRun.source).where(
            CIRun.started_at >= now - FLAKY_LOOKBACK, CIRun.suite.in_(CI_SUITES)
        )
    ).all()
    counts = {suite: [0, 0, 0] for suite in CI_SUITES}  # runs, flaky, simulated
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
    )


# --- the PR comment's Tests section ----------------------------------------------------------

TESTS_START, TESTS_END = "<!-- tests -->", "<!-- /tests -->"


def _names(suites) -> str:
    return ", ".join(SUITE_NAMES[s] for s in suites) or "none"


def section_lines(selection: Selection) -> list[str]:
    lines = [TESTS_START, "**Tests** (the test selector's recommendation; CI still runs every job)"]
    if selection.full:
        lines.append(f"- Would run every job: {selection.full}.")
    elif not selection.suites:
        lines.append("- Would run no jobs: only docs or config changed.")
    else:
        lines.append(f"- Would run: **{_names(selection.suites)}**")
        lines += [f"  - {SUITE_NAMES[s]}: {selection.reasons[s]}" for s in selection.suites]
        lines.append(f"- Would skip: {_names(selection.skipped)}")
    for f in selection.flaky:
        simulated = f", {f.simulated_runs} of them simulated" if f.simulated_runs else ""
        lines.append(
            f"- Possibly flaky: {SUITE_NAMES[f.suite]} failed and then passed on a re-run in "
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
