import pytest
import yaml

from sdlc.tiers import POLICY, PolicyError, load_policy


def test_policy_matches_the_blueprint_and_claude_md():
    policy = load_policy()
    assert policy.bands == ((0, "T0"), (20, "T1"), (50, "T2"), (80, "T3"))
    assert policy.fallback_tier == "T2"

    floors = {r.name: r.tier for r in policy.floors}
    assert floors == {
        "billing_auth": "T3",
        "schema_migration": "T3",
        "pipeline_or_forecasting": "T2",
    }
    assert [(r.name, r.tier) for r in policy.caps] == [("docs_or_config_only", "T0")]

    humans = {t.id: (t.humans, t.senior_human, t.code_owner) for t in policy.tiers.values()}
    assert humans == {
        "T0": (0, False, False),
        "T1": (1, False, False),
        "T2": (1, True, False),
        "T3": (2, True, True),
    }
    assert policy.tiers["T3"].tests == "full suite + manual QA"
    assert policy.tiers["T3"].agent_check == "reports_only"  # an agent never passes T3 alone


def test_t3_is_the_tier_the_simulated_approver_covers():
    approvers = yaml.safe_load((POLICY.parent / "approvers.yaml").read_text(encoding="utf-8"))
    covered = {t for a in approvers["approvers"] for t in a["applies_to_tiers"]}
    needs_a_second_human = {t.id for t in load_policy().tiers.values() if t.humans >= 2}
    assert covered == needs_a_second_human == {"T3"}


def write_variant(tmp_path, change):
    data = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "tiers.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["score_bands"].pop(), "list each of"),
        (lambda d: d["score_bands"][1].update(min=0), "minimums must start at 0"),
        (lambda d: d["score_bands"][0].update(tier="T9"), "unknown tier"),
        (lambda d: d["floors"][0].update(tier="T7"), "unknown tier"),
        (lambda d: d["floors"][0].update(when={"colour": "red"}), "`when` must use only"),
        (lambda d: d.update(fallback_tier="none"), "unknown tier"),
        (lambda d: d["tiers"].pop("T2"), "T2 is not defined"),
        (lambda d: d["tiers"]["T1"].update(agent_check="always"), "agent_check must be one of"),
        (lambda d: d["tiers"]["T1"].update(humans=-1), "humans must be a whole number"),
    ],
)
def test_a_broken_policy_is_rejected(tmp_path, change, message):
    with pytest.raises(PolicyError, match=message):
        load_policy(write_variant(tmp_path, change))
