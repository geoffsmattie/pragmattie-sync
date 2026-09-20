from sdlc.backlog import body_for, labels_for, load_backlog, plan
from sdlc.tables import MODULES


def test_backlog_file_is_valid():
    items = load_backlog()
    assert len(items) >= 40
    titles = [i["title"] for i in items]
    assert len(titles) == len(set(titles)), "duplicate titles"
    for item in items:
        assert item["module"] in MODULES
        assert item["type"] in {"feature", "bug", "chore"}
        assert item["priority"] in {"p1", "p2", "p3"}
        assert item["points"] in {1, 2, 3, 5, 8}
        assert all(len(label) <= 50 for label in labels_for(item))


def test_plan_skips_existing_titles_and_labels():
    items = [
        {"title": "A", "module": "leads", "type": "bug", "priority": "p1", "points": 2},
        {"title": "B", "module": "leads", "type": "feature", "priority": "p2", "points": 3},
    ]
    todo = plan(items, existing_titles={"A"}, existing_labels={"module:leads", "type:bug"})
    assert [i["title"] for i in todo["issues"]] == ["B"]
    assert "module:leads" not in todo["labels"]
    assert "type:feature" in todo["labels"]
    assert "caused-incident" in todo["labels"]


def test_body_lists_acceptance_criteria():
    body = body_for({"title": "x", "epic": "E", "criteria": ["one", "two"]})
    assert "**Epic:** E" in body
    assert "- [ ] two" in body
