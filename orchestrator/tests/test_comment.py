from sdlc.agents import comment
from sdlc.agents.gate import Approvals, evaluate
from sdlc.agents.llm import LLMResult
from sdlc.agents.pr_risk import Assessment
from sdlc.governance import Assignment
from sdlc.scoring import MAX_POINTS
from sdlc.tiers import load_policy

POLICY = load_policy()
SHA = "abc1234"


def assessment(tier="T1", *, ok=True, clamped=False):
    llm = LLMResult({}, "claude-sonnet-5", 1200, 150, 900, 0, 800, "req_1") if ok else None
    return Assessment(
        raw_score=30,
        signals=dict.fromkeys(MAX_POINTS, 3),
        adjustment=15 if ok else None,
        clamped=clamped,
        final_score=45 if ok else 30,
        assignment=Assignment(tier, "T1", (), None, ("Risk score 45 is in the T1 band.",)),
        status="ok" if ok else "timeout",
        error=None if ok else "timed out",
        justification="Touches the import path.",
        top_reasons=("Changes the import loop.", "No test for empty files.", "Small diff."),
        test_gaps=("empty CSV",),
        llm=llm,
    )


def render(tier="T1", approvals=None, mode="enforce", **kwargs):
    approvals = approvals or Approvals()
    a = assessment(tier, **kwargs)
    gate = evaluate(POLICY, tier, ok=a.ok, approvals=approvals, mode=mode)
    meta = comment.Meta(7, mode, "Simulated second approver", SHA)
    return comment.render(a, gate, approvals, POLICY, meta)


def test_the_comment_carries_the_tier_score_reasons_and_trace():
    body = render()
    assert comment.MARKER in body and f"<!-- head:{SHA} -->" in body
    assert "## Risk review: T1 (Light)" in body
    assert "Score 45/100" in body and "rubric 30" in body and "+15" in body
    assert "1. Changes the import loop." in body and "empty CSV" in body
    assert "decision 7" in body and "claude-sonnet-5" in body and "1350 tokens" in body
    assert "| change_size | 3 / 20 |" in body


def test_only_the_boxes_the_tier_needs_are_shown():
    t0 = render("T0")
    assert "[ ]" not in t0 and "doesn't need to act" in t0

    t1 = render("T1")
    assert "- [ ] **Human sign-off:**" in t1 and "Manual QA" not in t1

    t3 = render("T3")
    assert "- [ ] **Human sign-off:**" in t3 and "- [ ] **Manual QA done:**" in t3
    assert "Simulated second approval: **waiting**" in t3 and "not a real second person" in t3


def test_ticks_are_read_back_for_the_current_commit_only():
    body = render("T3")
    assert comment.read_ticks(body, SHA) == (False, False)

    ticked = body.replace("- [ ] **Human sign-off", "- [x] **Human sign-off")
    assert comment.read_ticks(ticked, SHA) == (True, False)
    both = ticked.replace("- [ ] **Manual QA done", "- [X] **Manual QA done")
    assert comment.read_ticks(both, SHA) == (True, True)

    # The same ticks on a comment written for an older commit must not count.
    assert comment.read_ticks(both, "def5678") == (False, False)
    assert comment.comment_head(both) == SHA and comment.comment_head("no marker") is None


def test_refresh_updates_the_live_parts_without_rewriting_the_review():
    body = render("T3", mode="shadow")
    assert "would do: **pending**" in body and "**waiting**" in body
    done = evaluate(POLICY, "T3", ok=True, approvals=Approvals(True, True, True), mode="shadow")
    updated = comment.refresh(body, done, simulated_approved=True)
    assert "Simulated second approval: **approved**" in updated
    assert "would do: **success**" in updated
    assert (
        updated.replace("**approved**", "**waiting**").replace("**success**", "**pending**") == body
    )


def test_a_failed_run_says_so_and_states_the_fallback():
    body = render("T2", ok=False)
    assert "could not score this PR" in body and "(timeout)" in body
    assert "fails closed" in body and "Score " not in body.split("Signal points")[0]


def test_the_model_clamp_is_disclosed():
    assert "limited to the +/-15 maximum" in render(clamped=True)
    assert "limited to" not in render(clamped=False)


def test_shadow_mode_banner_appears_only_in_shadow():
    assert "Shadow mode." in render(mode="shadow")
    assert "Shadow mode." not in render(mode="enforce")
