import pytest

from sdlc.agents.gate import Approvals, evaluate, requirements
from sdlc.tiers import load_policy

POLICY = load_policy()
NOBODY = Approvals()
SIGNED = Approvals(signoff=True)
EVERYONE = Approvals(signoff=True, qa_done=True, simulated_approved=True)


def gate(tier, approvals=NOBODY, *, ok=True, mode="enforce"):
    return evaluate(POLICY, tier, ok=ok, approvals=approvals, mode=mode)


def test_what_each_tier_needs_comes_from_the_policy_file():
    assert requirements(POLICY, "T0") == {
        "signoff": False,
        "simulated_second": False,
        "manual_qa": False,
    }
    assert requirements(POLICY, "T1")["signoff"] and not requirements(POLICY, "T1")["manual_qa"]
    assert requirements(POLICY, "T2")["signoff"]
    assert requirements(POLICY, "T3") == {
        "signoff": True,
        "simulated_second": True,
        "manual_qa": True,
    }


def test_t0_passes_with_nobody():
    result = gate("T0")
    assert (result.state, result.missing) == ("success", ())


@pytest.mark.parametrize("tier", ["T1", "T2"])
def test_t1_and_t2_wait_for_the_human_signoff_then_pass(tier):
    waiting = gate(tier)
    assert (waiting.state, waiting.missing) == ("pending", ("human sign-off",))
    assert gate(tier, SIGNED).state == "success"


def test_t3_needs_signoff_qa_and_the_simulated_second_approval():
    assert gate("T3").missing == ("human sign-off", "manual QA", "simulated second approval")
    assert gate("T3", SIGNED).state == "pending"
    almost = Approvals(signoff=True, qa_done=True)
    assert gate("T3", almost).missing == ("simulated second approval",)
    assert gate("T3", EVERYONE).state == "success"


def test_a_failed_agent_run_fails_closed_whoever_has_signed():
    result = gate("T2", EVERYONE, ok=False)
    assert result.state == "failure" and "fails closed" in result.description


def test_shadow_mode_always_passes_but_says_what_enforce_would_do():
    assert gate("T3", mode="shadow").state == "success"
    shadow = gate("T3", mode="shadow")
    assert shadow.would_be == "pending" and "would be pending" in shadow.description
    failed = gate("T2", ok=False, mode="shadow")
    assert failed.state == "success" and failed.would_be == "failure"


def test_descriptions_fit_githubs_limit():
    assert all(
        len(gate(t, mode=m).description) <= 140 for t in POLICY.tiers for m in ("shadow", "enforce")
    )
