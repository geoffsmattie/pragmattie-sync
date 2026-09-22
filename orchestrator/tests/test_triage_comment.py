from sdlc.agents import triage_comment
from sdlc.agents.llm import LLMResult
from sdlc.agents.triage import Assessment
from sdlc.similarity import SimilarIssue


def assessment(
    *,
    ok=True,
    module="leads",
    type="bug",
    priority="p2",
    points=3,
    confidence=0.85,
    duplicate_of=None,
    questions=(),
    similar=(),
):
    return Assessment(
        module=module if ok else None,
        type=type if ok else None,
        priority=priority if ok else None,
        estimate_points=points if ok else None,
        duplicate_of=duplicate_of,
        confidence=confidence if ok else None,
        needs_info=bool(questions),
        status="ok" if ok else "timeout",
        error=None if ok else "timed out",
        rationale="Looks like duplicates after CSV import." if ok else "",
        questions=questions,
        similar=similar,
        llm=LLMResult({}, "claude-haiku-4-5", 900, 120, 0, 0, 400, "req_1") if ok else None,
    )


def test_content_version_changes_with_the_text_and_only_the_text():
    v1 = triage_comment.content_version("Fix lead import", "It crashes")
    assert v1 == triage_comment.content_version("Fix lead import", "It crashes")  # deterministic
    assert v1 != triage_comment.content_version("Fix lead import", "It crashes now")  # body changed
    assert v1 != triage_comment.content_version("Fix Lead Import", "It crashes")  # title changed


def test_render_shows_the_classification_and_footer():
    meta = triage_comment.Meta(9, "abc123", ())
    body = triage_comment.render(assessment(), meta)
    assert triage_comment.MARKER in body and "<!-- version:abc123 -->" in body
    assert "## Triage: leads / bug (p2)" in body
    assert "Estimate 3 points" in body and "confidence 85%" in body
    assert "decision 9" in body and "claude-haiku-4-5" in body and "1020 tokens" in body


def test_render_shows_questions_and_duplicate_note():
    body = triage_comment.render(
        assessment(duplicate_of=5, questions=("Which screen?", "How many records?")),
        triage_comment.Meta(1, "v1", ()),
    )
    assert "Possibly a duplicate of #5" in body and "not closed" in body
    assert "Which screen?" in body and "How many records?" in body


def test_render_lists_similar_issues():
    similar = (
        SimilarIssue(5, "Duplicate leads", "leads", "bug", 3, 2.0, "open", 0.8),
        SimilarIssue(6, "Unrelated", "pipeline", "chore", 1, None, "closed", 0.1),
    )
    body = triage_comment.render(assessment(similar=similar), triage_comment.Meta(1, "v1", ()))
    assert "#5 [open] leads/bug, 3pt, 2.0d" in body
    assert "#6 [closed] pipeline/chore, 1pt, ?" in body


def test_render_notes_overrides_without_repeating_the_dimension_value():
    body = triage_comment.render(assessment(), triage_comment.Meta(1, "v1", ("module", "type")))
    assert "A human has already set module, type; left as-is." in body


def test_render_on_failure_is_short_and_says_it_will_retry():
    body = triage_comment.render(assessment(ok=False), triage_comment.Meta(None, "v1", ()))
    assert "Could not triage this issue yet" in body and "(timeout)" in body
    assert "will try again shortly" in body
    assert "Estimate" not in body  # nothing about a classification that doesn't exist
    assert "not recorded" not in body  # failure return path doesn't reach the footer at all


def test_comment_version_round_trips_through_render():
    body = triage_comment.render(assessment(), triage_comment.Meta(1, "xyz789", ()))
    assert triage_comment.comment_version(body) == "xyz789"
    assert triage_comment.comment_version("no marker here") is None
