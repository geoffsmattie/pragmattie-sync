import pytest

from sdlc.governance import Facts, assign_tier, band_for, fallback_assignment
from sdlc.tiers import load_policy

POLICY = load_policy()


def facts(module="leads", migration=False, docs=False) -> Facts:
    return Facts(module=module, touches_migration=migration, docs_only=docs)


@pytest.mark.parametrize(
    ("score", "tier"),
    [
        (0, "T0"),
        (19, "T0"),
        (20, "T1"),
        (49, "T1"),
        (50, "T2"),
        (79, "T2"),
        (80, "T3"),
        (100, "T3"),
    ],
)
def test_score_bands(score, tier):
    assert band_for(POLICY, score) == tier


def test_a_plain_pr_gets_its_score_band():
    result = assign_tier(POLICY, 35, facts())
    assert (result.tier, result.floors, result.capped_by) == ("T1", (), None)


@pytest.mark.parametrize(
    ("kwargs", "tier", "floor"),
    [
        ({"module": "billing_auth"}, "T3", "billing_auth"),
        ({"migration": True}, "T3", "schema_migration"),
        ({"module": "pipeline"}, "T2", "pipeline_or_forecasting"),
        ({"module": "forecasting"}, "T2", "pipeline_or_forecasting"),
    ],
)
def test_floors_raise_a_low_score(kwargs, tier, floor):
    result = assign_tier(POLICY, 3, facts(**kwargs))
    assert result.tier == tier and floor in result.floors
    assert result.score_tier == "T0"
    assert any(floor in reason for reason in result.reasons)


def test_the_highest_match_wins():
    result = assign_tier(POLICY, 30, facts(module="pipeline", migration=True))
    assert result.tier == "T3"
    assert set(result.floors) == {"schema_migration", "pipeline_or_forecasting"}
    # A high score beats a lower floor.
    assert assign_tier(POLICY, 90, facts(module="pipeline")).tier == "T3"


def test_docs_only_is_capped_at_t0_unless_a_floor_applies():
    capped = assign_tier(POLICY, 60, facts(docs=True))
    assert (capped.tier, capped.capped_by) == ("T0", "docs_or_config_only")
    with_floor = assign_tier(POLICY, 60, facts(docs=True, migration=True))
    assert with_floor.tier == "T3" and with_floor.capped_by is None


def test_fallback_is_the_floor_tier_or_t2_and_never_lower():
    assert fallback_assignment(POLICY, facts(), "Agent timed out.").tier == "T2"
    assert fallback_assignment(POLICY, facts(migration=True), "Agent timed out.").tier == "T3"
    # Even a docs-only PR doesn't get the cap when the agent failed.
    assert fallback_assignment(POLICY, facts(docs=True), "Bad output.").tier == "T2"
    assert "Agent timed out." in fallback_assignment(POLICY, facts(), "Agent timed out.").reasons[0]
