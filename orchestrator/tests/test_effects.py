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


def test_set_dimension_label_replaces_only_its_own_prefix(gh):
    gh.open_issue(12)
    gh.labels[12] = {"needs-info", "module:pipeline"}
    result = effects(gh).set_dimension_label(12, "module", "leads")
    assert result["label"] == "module:leads"
    assert gh.labels[12] == {"needs-info", "module:leads"}  # other labels untouched
    effects(gh).set_dimension_label(12, "module", "leads")  # already correct: no-op, no crash
    assert gh.labels[12] == {"needs-info", "module:leads"}


def test_add_label_if_absent_never_overwrites_or_removes(gh):
    gh.open_issue(12)
    first = effects(gh).add_label_if_absent(12, "needs-info", "F9A03F", "desc")
    assert first["label"] == "needs-info" and "already_present" not in first
    assert gh.labels[12] == {"needs-info"}

    second = effects(gh).add_label_if_absent(12, "needs-info", "F9A03F", "desc")
    assert second["already_present"] is True
    assert gh.labels[12] == {"needs-info"}  # still just one


def test_remove_label_deletes_exactly_that_label(gh):
    gh.open_issue(12)
    gh.labels[12] = {"retriage", "module:leads"}
    effects(gh).remove_label(12, "retriage")
    assert gh.labels[12] == {"module:leads"}


def test_dimension_and_flag_labels_are_no_ops_in_off_mode(gh):
    gh.open_issue(12)
    e = effects(gh, "off")
    assert e.set_dimension_label(12, "module", "leads") == {"skipped": "mode is off"}
    assert e.add_label_if_absent(12, "needs-info", "F9A03F", "desc") == {"skipped": "mode is off"}
    assert e.remove_label(12, "retriage") == {"skipped": "mode is off"}
    assert gh.writes == []


def test_read_issue_and_read_labels(gh):
    gh.open_issue(12, title="Lead import is slow")
    gh.labels[12] = {"module:leads"}
    e = effects(gh)
    assert e.read_issue(12)["title"] == "Lead import is slow"
    assert e.read_labels(12) == ["module:leads"]


def test_find_comment_uses_the_marker_given_not_a_hardcoded_one(gh):
    gh.open_issue(12)
    e = effects(gh)
    e.upsert_comment(12, "<!-- pragmattie-triage -->\nhi", None)
    assert e.find_comment(12) is None  # the default marker is the PR risk one
    found = e.find_comment(12, marker="<!-- pragmattie-triage -->")
    assert found and "hi" in found["body"]
