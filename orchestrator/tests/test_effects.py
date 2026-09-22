import pytest

from sdlc.agents.comment import MARKER
from sdlc.agents.github_effects import Effects
from tests.fakes import FakeGitHub


@pytest.fixture
def gh():
    fake = FakeGitHub()
    fake.open_pr(7, "sha1")
    return fake


def effects(fake, mode="enforce"):
    return Effects(fake.client(), mode)


def test_reads_work_in_every_mode_including_off(gh):
    for mode in ("off", "shadow", "enforce"):
        e = effects(gh, mode)
        assert e.read_pr(7)["number"] == 7
        assert "diff --git" in e.read_diff(7)
        assert e.find_comment(7) is None
    assert gh.writes == []


def test_mode_off_makes_every_write_a_no_op_and_reports_it(gh):
    e = effects(gh, "off")
    results = [
        e.upsert_comment(7, f"{MARKER} hi", None),
        e.set_status("sha1", "success", "ok"),
        e.set_tier_label(7, "T1"),
    ]
    assert results == [{"skipped": "mode is off"}] * 3
    assert gh.writes == []  # not one POST, PATCH or DELETE reached GitHub


def test_one_comment_is_created_then_updated_in_place(gh):
    e = effects(gh)
    first = e.upsert_comment(7, f"{MARKER}\nv1", None)
    assert first["created"] is True
    found = e.find_comment(7)
    assert found and "v1" in found["body"]

    second = e.upsert_comment(7, f"{MARKER}\nv2", found)
    assert second["created"] is False and second["comment_id"] == first["comment_id"]
    assert len(gh.comments[7]) == 1 and "v2" in gh.comments[7][0]["body"]


def test_the_status_uses_the_risk_gate_context_and_a_short_description(gh):
    effects(gh).set_status("sha1", "pending", "x" * 300)
    status = gh.last_status("sha1")
    assert status["context"] == "risk-gate" and status["state"] == "pending"
    assert len(status["description"]) == 140


def test_setting_a_tier_label_removes_the_old_tier_and_leaves_other_labels(gh):
    gh.labels[7] = {"tier:T3", "module:leads"}
    result = effects(gh).set_tier_label(7, "T1")
    assert result["label"] == "tier:T1"
    assert gh.labels[7] == {"tier:T1", "module:leads"}
    effects(gh).set_tier_label(7, "T1")  # again: nothing to do, nothing breaks
    assert gh.labels[7] == {"tier:T1", "module:leads"}


def test_a_github_error_is_reported_not_raised_so_other_writes_still_happen(gh):
    gh.fail = {"/statuses/"}
    e = effects(gh)
    assert "error" in e.set_status("sha1", "success", "ok")
    assert e.set_tier_label(7, "T2")["label"] == "tier:T2"  # the label write still went through
