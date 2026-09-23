from datetime import datetime

from sdlc.audit import record_decision
from sdlc.eval import BARS, grade, load_eval_set, points_step

T = datetime(2026, 9, 23, 10)


def decide(db, number, *, module, type, points, priority="p2", status="ok", trigger="opened"):
    record_decision(
        db,
        agent="triage",
        agent_version="v1",
        subject_type="issue",
        subject_source="github",
        subject_id=number,
        trigger=trigger,
        now=T,
        head_sha=f"v-{number}-{trigger}-{status}",
        prompt_version="triage-v1",
        output={"module": module, "type": type, "estimate_points": points, "priority": priority}
        if status == "ok"
        else None,
        status=status,
    )


def label(issue, module="leads", type="feature", points=3, priority="p2", note=None):
    return dict(issue=issue, module=module, type=type, points=points, priority=priority, note=note)


def test_points_steps_on_the_scale():
    assert points_step(3, 3) == 0
    assert points_step(2, 3) == 1 and points_step(3, 5) == 1
    assert points_step(1, 8) == 4
    assert points_step(4, 3) == 5  # off the scale counts as far


def test_grading_scores_patterns_and_disagreements(db):
    labels = [
        label(1),
        label(2, type="chore"),
        label(3, points=1),
        label(4, module="forecasting"),
        label(5, note="unsure"),
    ]
    decide(db, 1, module="leads", type="feature", points=3)
    decide(db, 2, module="leads", type="feature", points=3)  # type miss: chore -> feature
    decide(db, 3, module="leads", type="feature", points=5)  # points two steps out
    decide(db, 4, module="platform", type="feature", points=2)  # module miss; points within one
    # issue 5: only a failed run and a manual trial, so the agent has no graded answer
    decide(db, 5, module="leads", type="feature", points=3, status="timeout")
    decide(db, 5, module="leads", type="feature", points=3, trigger="trial")
    db.commit()

    report = grade(db, labels)
    assert (report["issues"], report["graded"], report["missing"]) == (5, 4, [5])
    s = report["scores"]
    assert (s["module"], s["type"], s["points_within_one"]) == (0.6, 0.6, 0.6)
    assert report["passed"] == {k: False for k in BARS}
    assert report["patterns"]["type"] == [{"human": "chore", "agent": "feature", "count": 1}]
    assert report["patterns"]["module"] == [
        {"human": "forecasting", "agent": "platform", "count": 1}
    ]
    assert report["patterns"]["points"] == {"agent_higher": 1, "agent_lower": 1, "same": 2}
    by_issue = {d["issue"]: d for d in report["disagreements"]}
    assert set(by_issue) == {2, 3, 4, 5}
    assert by_issue[3]["misses"] == ["points_within_one"]
    assert by_issue[5]["agent"] is None and by_issue[5]["note"] == "unsure"


def test_the_latest_successful_decision_is_the_one_graded(db):
    decide(db, 1, module="platform", type="feature", points=3)
    db.commit()
    record_decision(
        db,
        agent="triage",
        agent_version="v1",
        subject_type="issue",
        subject_source="github",
        subject_id=1,
        trigger="edit",
        now=datetime(2026, 9, 23, 11),
        head_sha="v2",
        output={"module": "leads", "type": "feature", "estimate_points": 3},
        status="ok",
    )
    db.commit()
    assert grade(db, [label(1)])["scores"]["module"] == 1.0


def test_the_committed_eval_set_is_complete_and_on_the_vocabulary():
    from sdlc.agents.triage import POINTS, TYPES
    from sdlc.tables import MODULES

    rows = load_eval_set()
    assert [r["issue"] for r in rows] == list(range(6, 46))
    for r in rows:
        assert r["module"] in MODULES and r["type"] in TYPES and r["points"] in POINTS


def test_a_blind_rerun_shows_no_labels_uses_only_simulated_examples_and_records_trials(db, history):
    from sqlalchemy import select

    from sdlc.agents.llm import StructuredLLM
    from sdlc.eval import run_blind
    from sdlc.tables import AgentDecision, Issue
    from tests.fakes import FakeAnthropic, response, triage_answer

    # A real issue with Cowork-style labels must never be shown as an example.
    db.add(
        Issue(
            source="github",
            external_id="issue-7",
            number=7,
            title="Lead scoring explanations on the lead row",
            module="leads",
            type="feature",
            estimate_points=8,
            state="open",
            created_at=datetime(2026, 9, 1),
        )
    )
    db.commit()
    labels = [label(6), label(8, type="chore")]
    texts = {
        6: {"title": "Score leads with a model", "body": "Lead scoring from engagement."},
        8: {"title": "Detect duplicate leads", "body": "Match on email domain."},
    }
    llm = FakeAnthropic(
        response(triage_answer(module="leads", type="feature", points=3)),
        response(triage_answer(module="leads", type="feature", points=2)),
    )
    answers = run_blind(db, StructuredLLM(client=llm), labels=labels, texts=texts)

    sent = [c["messages"][0]["content"] for c in llm.calls]
    assert all("Existing labels: (none)" in s for s in sent)  # blind
    assert all("Lead scoring explanations on the lead row" not in s for s in sent)
    rows = list(db.scalars(select(AgentDecision).where(AgentDecision.agent == "triage")))
    assert [(r.trigger, r.subject_id) for r in rows] == [("trial", 6), ("trial", 8)]
    report = grade(db, labels, answers)
    assert report["scores"]["type"] == 0.5
    assert report["patterns"]["type"] == [{"human": "chore", "agent": "feature", "count": 1}]
    assert grade(db, labels)["graded"] == 0  # trial rows never count as the agent's decisions
