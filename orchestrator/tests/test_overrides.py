from datetime import timedelta

from sqlalchemy import select

from sdlc.agents.overrides import Command, Ruling, effective_tier, parse_commands, rule
from sdlc.tables import AgentDecision
from tests.fakes import answer, response
from tests.test_runner import NOW, PIPELINE, decisions, setup


def cmd(tier, reason="", cid=1):
    return Command(comment_id=cid, actor="geoff", tier=tier, reason=reason, url=None)


# --- the rules, as pure functions ----------------------------------------------------------------


def test_parsing_finds_commands_in_peoples_comments_only():
    comments = [
        {"id": 1, "body": "Looks risky.\n/tier T3", "user": {"login": "geoff"}},
        {"id": 2, "body": "/tier t1: copy-only change, checked locally", "user": {"login": "dana"}},
        {"id": 3, "body": "<!-- pragmattie-risk-gate -->\n/tier T0", "user": {"login": "geoff"}},
        {"id": 4, "body": "raise with `/tier T3` in a sentence doesn't count", "user": {}},
    ]
    found = parse_commands(comments, ("<!-- pragmattie-risk-gate -->",))
    assert [(c.comment_id, c.tier, c.reason, c.actor) for c in found] == [
        (1, "T3", "", "geoff"),
        (2, "T1", "copy-only change, checked locally", "dana"),
    ]


def test_raising_is_always_accepted_and_needs_no_reason():
    r = rule(cmd("T3"), current="T1", floor="T0", head_sha="a")
    assert (r.direction, r.accepted) == ("raise", True)


def test_lowering_needs_a_written_reason():
    r = rule(cmd("T0", "ok"), current="T1", floor="T0", head_sha="a")
    assert (r.direction, r.accepted) == ("lower", False)
    assert "written reason" in r.why
    ok = rule(
        cmd("T0", "copy-only change, checked locally"), current="T1", floor="T0", head_sha="a"
    )
    assert ok.accepted


def test_nothing_goes_below_a_policy_floor_whatever_the_reason():
    r = rule(cmd("T1", "it is only a rename, promise"), current="T2", floor="T2", head_sha="a")
    assert not r.accepted and "policy floor" in r.why


def test_raises_stick_across_commits_and_lowerings_do_not():
    raised = Ruling(1, "geoff", "", "T1", "T3", "raise", True, "", head_sha="a")
    lowered = Ruling(2, "geoff", "copy only, checked", "T1", "T0", "lower", True, "", head_sha="a")
    rejected = Ruling(3, "geoff", "", "T1", "T0", "lower", False, "", head_sha="b")
    assert effective_tier("T1", "T0", [raised], "b") == "T3"
    assert effective_tier("T1", "T0", [lowered], "a") == "T0"
    assert effective_tier("T1", "T0", [lowered], "b") == "T1"  # a new push is new risk
    assert effective_tier("T1", "T0", [rejected], "b") == "T1"
    assert effective_tier("T0", "T2", [lowered], "a") == "T2"  # never below the floor


# --- end to end through the PR risk agent's poll -------------------------------------------------


def overrides(db):
    return list(
        db.scalars(
            select(AgentDecision)
            .where(AgentDecision.agent == "tier_override")
            .order_by(AgentDecision.id)
        )
    )


def test_a_person_raises_a_tier_and_everything_follows(db):
    runner, gh, _ = setup("enforce", adjustment=10)  # rubric 15 + 10 = 25 -> T1
    runner.poll_once(NOW)
    gh.human_comment(7, "Touches the import path customers rely on.\n/tier T3")
    runner.poll_once(NOW + timedelta(minutes=1))

    assert gh.labels[7] == {"tier:T3"}
    body = gh.comment_on(7)["body"]
    assert "## Risk review: T3 (Critical, raised from T1 by a person)" in body
    assert "- [ ] **Manual QA done:**" in body and "Simulated second approval: **waiting**" in body
    assert "`/tier T3` by @geoff: Raised from T1 to T3." in body
    status = gh.last_status("sha1")
    assert status["state"] == "pending" and "T3" in status["description"]

    (row,) = overrides(db)
    assert (row.status, row.tier, row.trigger, row.subject_id) == ("ok", "T3", "human", 7)
    assert row.human_override["from"] == "T1" and row.human_override["actor"] == "geoff"
    assert decisions(db)[0].tier == "T1"  # the agent's own decision is left as it was


def test_lowering_without_a_reason_is_rejected_and_shown(db):
    runner, gh, _ = setup("enforce", adjustment=10)
    runner.poll_once(NOW)
    gh.human_comment(7, "/tier T0")
    runner.poll_once(NOW + timedelta(minutes=1))

    assert gh.labels[7] == {"tier:T1"}
    assert "Rejected: lowering a tier needs a written reason" in gh.comment_on(7)["body"]
    (row,) = overrides(db)
    assert (row.status, row.tier) == ("rejected", None)
    assert row.human_override["accepted"] is False


def test_a_reasoned_lowering_holds_for_this_commit_only(db):
    runner, gh, _ = setup(
        "enforce", response(answer(adjustment=10)), response(answer(adjustment=10))
    )
    runner.poll_once(NOW)
    gh.human_comment(7, "/tier T0 copy-only change, checked it locally")
    runner.poll_once(NOW + timedelta(minutes=1))
    assert gh.labels[7] == {"tier:T0"}
    assert gh.last_status("sha1")["state"] == "success"  # T0 needs nobody

    gh.push(7, "sha2")
    runner.poll_once(NOW + timedelta(minutes=2))
    assert gh.labels[7] == {"tier:T1"}  # a new push is new risk
    assert gh.last_status("sha2")["state"] == "pending"


def test_a_raise_sticks_when_new_commits_arrive(db):
    runner, gh, _ = setup("enforce", response(answer()), response(answer()))  # 15 -> T0
    runner.poll_once(NOW)
    gh.human_comment(7, "/tier T2")
    runner.poll_once(NOW + timedelta(minutes=1))
    gh.push(7, "sha2")
    runner.poll_once(NOW + timedelta(minutes=2))
    assert gh.labels[7] == {"tier:T2"}
    assert "raised from T0 by a person" in gh.comment_on(7)["body"]  # the fresh comment too


def test_a_floor_cannot_be_argued_down(db):
    runner, gh, _ = setup("enforce", files=PIPELINE)  # pipeline floor: T2
    runner.poll_once(NOW)
    gh.human_comment(7, "/tier T1 it's only a rename of a variable")
    runner.poll_once(NOW + timedelta(minutes=1))
    assert gh.labels[7] == {"tier:T2"}
    assert "policy floor" in gh.comment_on(7)["body"]
    assert overrides(db)[0].status == "rejected"


def test_each_command_is_ruled_on_once(db):
    runner, gh, _ = setup("enforce", adjustment=10)
    runner.poll_once(NOW)
    gh.human_comment(7, "/tier T3")
    for n in range(1, 4):
        runner.poll_once(NOW + timedelta(minutes=n))
    assert len(overrides(db)) == 1
