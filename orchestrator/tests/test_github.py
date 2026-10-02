"""The GitHub collector, against a fake GitHub served by httpx.MockTransport."""

import httpx
import pytest
from sqlalchemy import func, select

from sdlc.github_client import GitHubClient, GitHubError, RateLimited, parse_time
from sdlc.signals.github import Collector, infer_module, labels_of
from sdlc.tables import CIRun, Engineer, Issue, PullRequest

REPO = "acme/pragmattie-sync"
T0 = "2026-09-01T10:00:00Z"


def label(name):
    return {"name": name}


ROUTES = {
    f"/repos/{REPO}/issues": [
        {
            "number": 1,
            "title": "Drag and drop deals",
            "state": "closed",
            "created_at": T0,
            "closed_at": "2026-09-03T10:00:00Z",
            "labels": [
                label("module:pipeline"),
                label("type:feature"),
                label("points:5"),
                label("epic:AI lead scoring"),
            ],
            "assignee": {"login": "geoff"},
        },
        {"number": 2, "title": "a PR, not an issue", "pull_request": {}, "labels": []},
    ],
    f"/repos/{REPO}/pulls": [
        {
            "number": 2,
            "title": "Drag and drop on the pipeline board",
            "state": "closed",
            "created_at": T0,
            "closed_at": "2026-09-02T10:00:00Z",
            "body": "Closes #1",
            "labels": [],
            "user": {"login": "geoff"},
        }
    ],
    f"/repos/{REPO}/pulls/2": {
        "merged_at": "2026-09-02T10:00:00Z",
        "changed_files": 3,
        "additions": 120,
        "deletions": 10,
        "commits": 3,
    },
    f"/repos/{REPO}/pulls/2/files": [
        {"filename": "apps/web/src/views/PipelineView.vue"},
        {"filename": "apps/api/app/api/opportunities.py"},
        {"filename": "apps/api/alembic/versions/0003_stage_history.py"},
    ],
    f"/repos/{REPO}/pulls/2/reviews": [{"submitted_at": "2026-09-01T16:00:00Z"}],
    f"/repos/{REPO}/actions/runs": {
        "workflow_runs": [{"id": 99, "pull_requests": [{"number": 2}], "run_attempt": 2}]
    },
    f"/repos/{REPO}/actions/runs/99/jobs": {
        "jobs": [
            {
                "id": 1,
                "name": "Web (tests + build)",
                "conclusion": "failure",
                "run_attempt": 1,
                "started_at": T0,
                "completed_at": "2026-09-01T10:02:00Z",
            },
            {
                "id": 2,
                "name": "Web (tests + build)",
                "conclusion": "success",
                "run_attempt": 2,
                "started_at": T0,
                "completed_at": "2026-09-01T10:02:30Z",
            },
            {
                "id": 3,
                "name": "API (lint + tests)",
                "conclusion": "failure",
                "run_attempt": 1,
                "started_at": T0,
                "completed_at": "2026-09-01T10:01:00Z",
            },
        ]
    },
}


def fake_github(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer test-token"
    body = ROUTES.get(request.url.path)
    if body is None:
        return httpx.Response(404, json={"message": "Not Found"})
    return httpx.Response(200, json=body)


@pytest.fixture
def client():
    return GitHubClient(
        token="test-token",
        repo=REPO,
        base_url="https://api.github.test",
        transport=httpx.MockTransport(fake_github),
    )


def test_collects_issues_prs_and_ci_jobs(db, client):
    counts = Collector(db, client).run()
    assert counts == {"issues": 1, "pull_requests": 1, "ci_jobs": 3, "incidents": 0}

    issue = db.scalar(select(Issue).where(Issue.source == "github"))
    assert (issue.module, issue.estimate_points, issue.actual_days) == ("pipeline", 5, 2.0)
    assert issue.epic == "AI lead scoring"  # a story under its epic

    pr = db.scalar(select(PullRequest).where(PullRequest.source == "github"))
    assert pr.state == "merged"
    assert pr.issue_id == issue.id  # linked through "Closes #1"
    assert pr.module == "pipeline"  # inferred from file paths
    assert pr.touches_migration
    assert (pr.test_files_changed, pr.docs_only, pr.modules_touched) == (0, False, 1)
    assert pr.first_review_hours == 6.0
    assert pr.rework_commits == 2

    runs = {r.external_id: r for r in db.scalars(select(CIRun))}
    assert runs["job-1"].flaky  # failed, then passed on re-run
    assert not runs["job-3"].flaky  # failed and never re-passed: a real failure
    assert runs["job-2"].suite == "web"
    assert runs["job-2"].pull_request_id == pr.id


def test_rerunning_updates_instead_of_duplicating(db, client):
    Collector(db, client).run()
    Collector(db, client).run()
    assert db.scalar(select(func.count()).select_from(PullRequest)) == 1
    assert db.scalar(select(func.count()).select_from(CIRun)) == 3
    assert db.scalar(select(func.count()).select_from(Engineer)) == 1


def test_missing_settings_and_http_errors_are_clear():
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        GitHubClient(token="", repo="")
    broken = GitHubClient(
        token="test-token",
        repo="acme/missing",
        base_url="https://api.github.test",
        transport=httpx.MockTransport(fake_github),
    )
    with pytest.raises(GitHubError, match="404"):
        broken.get("/repos/{repo}/pulls/1")


def test_helpers():
    assert labels_of({"labels": [label("module:leads"), label("caused-incident")]}) == {
        "module": "leads",
        "caused-incident": "true",
    }
    assert infer_module(["orchestrator/sdlc/api.py"]) == "orchestrator"
    assert infer_module(["README.md"]) == "platform"
    assert parse_time("2026-09-01T10:00:00Z").isoformat() == "2026-09-01T10:00:00"


def test_paginate_follows_next_links():
    def pages(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        headers = {}
        if page < 3:
            headers["Link"] = (
                f'<https://api.github.test/repos/{REPO}/labels?page={page + 1}>; rel="next"'
            )
        return httpx.Response(200, json=[{"name": f"label-{page}"}], headers=headers)

    gh = GitHubClient(
        token="t",
        repo=REPO,
        base_url="https://api.github.test",
        transport=httpx.MockTransport(pages),
    )
    assert [x["name"] for x in gh.paginate("/repos/{repo}/labels")] == [
        "label-1",
        "label-2",
        "label-3",
    ]


def counting_client(handler):
    sent = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    gh = GitHubClient(
        token="t",
        repo=REPO,
        base_url="https://api.github.test",
        transport=httpx.MockTransport(record),
    )
    return gh, sent


def test_an_unchanged_resource_is_read_conditionally_and_comes_from_the_cache():
    def etagged(request: httpx.Request) -> httpx.Response:
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json=[{"number": 7}], headers={"ETag": '"v1"'})

    gh, sent = counting_client(etagged)
    assert gh.get("/repos/{repo}/pulls", state="open") == [{"number": 7}]
    assert gh.get("/repos/{repo}/pulls", state="open") == [{"number": 7}]  # 304: the cached body
    assert list(gh.paginate("/repos/{repo}/pulls")) == [{"number": 7}]
    assert "If-None-Match" not in sent[0].headers
    assert sent[1].headers["If-None-Match"] == '"v1"'
    assert (gh.sent, gh.not_modified) == (3, 1)  # other parameters are a different resource
    assert gh.get_text("/repos/{repo}/pulls", "application/vnd.github.diff")  # keyed by Accept too
    assert "If-None-Match" not in sent[-1].headers


def test_a_spent_rate_limit_pauses_the_client_until_github_resets_it():
    reset = 4102444800  # 2100-01-01 00:00 UTC

    def spent(request: httpx.Request) -> httpx.Response:
        headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)}
        return httpx.Response(403, json={"message": "API rate limit exceeded"}, headers=headers)

    gh, sent = counting_client(spent)
    with pytest.raises(RateLimited) as err:
        gh.get("/repos/{repo}/pulls")
    assert err.value.until.isoformat() == "2100-01-01T00:00:00"
    with pytest.raises(RateLimited, match="paused until 00:00 UTC"):
        gh.post("/repos/{repo}/issues", {"title": "x"})
    assert len(sent) == 1  # the second call never reached GitHub


def test_a_secondary_limit_pauses_for_its_retry_after_and_other_errors_dont_pause():
    def secondary(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/missing"):
            return httpx.Response(403, json={"message": "Resource not accessible"})
        return httpx.Response(429, json={"message": "slow down"}, headers={"retry-after": "60"})

    gh, _ = counting_client(secondary)
    with pytest.raises(GitHubError) as err:
        gh.get("/repos/{repo}/missing")
    assert not isinstance(err.value, RateLimited) and gh.limited_until is None
    with pytest.raises(RateLimited):
        gh.get("/repos/{repo}/pulls")
    assert gh.limited_until is not None
