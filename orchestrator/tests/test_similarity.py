from datetime import datetime

from sdlc.similarity import jaccard, similar_issues, tokens
from sdlc.tables import Issue


def make_issue(
    db, number, title, module="leads", type="feature", points=3, days=2.5, state="closed"
):
    issue = Issue(
        source="github",
        external_id=f"issue-{number}",
        number=number,
        title=title,
        module=module,
        type=type,
        estimate_points=points,
        actual_days=days,
        state=state,
        created_at=datetime(2026, 9, 1),
    )
    db.add(issue)
    db.flush()
    return issue


def test_tokens_drops_stopwords_and_short_words():
    # "add" and "fix" are stopwords here too: nearly every synthetic issue title starts with one
    # (see sdlc/synth.py's VERBS), so keeping them would make unrelated issues look similar.
    assert tokens("Add a filter to the lead import screen") == {
        "filter",
        "lead",
        "import",
        "screen",
    }
    assert tokens("Fix it") == set()
    assert tokens("") == set()


def test_jaccard_basic_cases():
    assert jaccard(set(), {"a"}) == 0.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3


def test_similar_issues_ranks_by_title_overlap(db):
    make_issue(db, 1, "Add duplicate detection for lead import")
    make_issue(db, 2, "Fix lead import performance for large CSV files")
    make_issue(db, 3, "Redesign the pipeline board")  # unrelated
    db.commit()

    results = similar_issues(db, "Duplicate detection is slow on lead import", "")
    assert [r.number for r in results] == [1, 2]  # closer title first; #3 has no overlap at all
    assert results[0].score > results[1].score


def test_similar_issues_can_exclude_the_query_issue_itself(db):
    make_issue(db, 1, "Duplicate detection for lead import")
    make_issue(db, 2, "Fix lead import performance")
    db.commit()

    with_self = similar_issues(db, "Duplicate detection for lead import", "")
    assert 1 in [r.number for r in with_self]
    without_self = similar_issues(db, "Duplicate detection for lead import", "", exclude_number=1)
    assert 1 not in [r.number for r in without_self]


def test_similar_issues_respects_the_limit(db):
    for n in range(1, 6):
        make_issue(db, n, f"Lead import issue number {n}")
    db.commit()
    assert len(similar_issues(db, "lead import", "", limit=3)) == 3


def test_similar_issues_returns_nothing_for_an_empty_query(db):
    make_issue(db, 1, "Add lead import")
    db.commit()
    assert similar_issues(db, "", "", limit=5) == []


def test_similar_issues_carries_the_fields_triage_needs(db):
    make_issue(
        db, 1, "Lead import is slow", module="leads", type="bug", points=5, days=1.5, state="open"
    )
    db.commit()
    (result,) = similar_issues(db, "Lead import is slow again", "")
    assert (
        result.module,
        result.type,
        result.estimate_points,
        result.actual_days,
        result.state,
    ) == (
        "leads",
        "bug",
        5,
        1.5,
        "open",
    )
