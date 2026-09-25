import json
import re
from datetime import datetime

import httpx
import pytest

from sdlc.audit import record_decision
from sdlc.demo_check import Check, _mode, describe
from sdlc.demo_reset import apply_plan, load_baseline, plan, reset_database, save_baseline, snapshot
from sdlc.github_client import GitHubClient
from sdlc.tables import AgentDecision, Approval, PullRequest

REPO = "geoffsmattie/pragmattie-sync"
RISK = "<!-- pragmattie-risk-gate -->"


class Repo:
    """A tiny GitHub: issues, PRs, comments and branches, with every write recorded."""

    def __init__(self):
        self.issues = {
            6: {
                "state": "open",
                "labels": ["module:leads", "type:feature"],
                "title": "Score leads",
            },
            7: {"state": "open", "labels": ["module:leads"], "title": "Explain score"},
        }
        self.prs = {3: {"state": "closed", "merged": True, "ref": "phase-4-agents", "labels": []}}
        self.comments: dict[int, list[dict]] = {}
        self.branches = {"main", "phase-4-agents"}
        self.deployments: dict[int, dict] = {}  # id -> {"sha", "state"}
        self.writes: list[tuple[str, str]] = []

    def client(self):
        return GitHubClient(token="t", repo=REPO, transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        base = f"/repos/{REPO}"
        body = json.loads(request.content) if request.content else {}
        if method != "GET":
            self.writes.append((method, path))
        if path == base:
            return httpx.Response(200, json={"default_branch": "main", "full_name": REPO})
        if path == f"{base}/deployments":
            return httpx.Response(
                200,
                json=[
                    {"id": i, "sha": d["sha"], "environment": "production"}
                    for i, d in sorted(self.deployments.items())
                ],
            )
        if method == "POST" and (m := re.fullmatch(rf"{base}/deployments/(\d+)/statuses", path)):
            self.deployments[int(m[1])]["state"] = body["state"]
            return httpx.Response(201, json={})
        if method == "DELETE" and (m := re.fullmatch(rf"{base}/deployments/(\d+)", path)):
            assert self.deployments.pop(int(m[1]))["state"] == "inactive"  # GitHub's rule
            return httpx.Response(204)
        if path == f"{base}/branches":
            return httpx.Response(200, json=[{"name": b} for b in sorted(self.branches)])
        if path == f"{base}/issues":
            items = [
                {
                    "number": n,
                    "state": i["state"],
                    "title": i["title"],
                    "labels": [{"name": x} for x in i["labels"]],
                }
                for n, i in self.issues.items()
            ] + [
                {"number": n, "state": p["state"], "title": "pr", "labels": [], "pull_request": {}}
                for n, p in self.prs.items()
            ]
            return httpx.Response(200, json=items)
        if path == f"{base}/pulls":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": n,
                        "state": p["state"],
                        "title": f"PR {n}",
                        "merged_at": "2026-09-24T10:00:00Z" if p["merged"] else None,
                        "merge_commit_sha": f"merge-{n}" if p["merged"] else None,
                        "labels": [{"name": x} for x in p["labels"]],
                        "head": {"ref": p["ref"], "repo": {"full_name": REPO}},
                    }
                    for n, p in self.prs.items()
                ],
            )
        if m := re.fullmatch(rf"{base}/issues/(\d+)/comments", path):
            return httpx.Response(200, json=self.comments.get(int(m[1]), []))
        if method == "PATCH" and (m := re.fullmatch(rf"{base}/(issues|pulls)/(\d+)", path)):
            n = int(m[2])
            target = self.issues if m[1] == "issues" and n in self.issues else self.prs
            target[n]["state"] = body["state"]
            return httpx.Response(200, json={})
        if method == "PUT" and (m := re.fullmatch(rf"{base}/issues/(\d+)/labels", path)):
            self.issues[int(m[1])]["labels"] = body["labels"]
            return httpx.Response(200, json=[])
        if method == "DELETE" and (m := re.fullmatch(rf"{base}/issues/(\d+)/labels/(.+)", path)):
            n = int(m[1])
            (self.issues if n in self.issues else self.prs)[n]["labels"].remove(
                httpx.URL(path).path.split("/")[-1].replace("%3A", ":")
            )
            return httpx.Response(200, json=[])
        if method == "DELETE" and (m := re.fullmatch(rf"{base}/issues/comments/(\d+)", path)):
            for comments in self.comments.values():
                comments[:] = [c for c in comments if c["id"] != int(m[1])]
            return httpx.Response(204)
        if method == "DELETE" and (m := re.fullmatch(rf"{base}/git/refs/heads/(.+)", path)):
            self.branches.discard(m[1])
            return httpx.Response(204)
        return httpx.Response(404, json={"message": f"no route {method} {path}"})


def after_a_demo(repo: Repo) -> dict:
    """Baseline the clean repo, then play out a demo on it."""
    baseline = snapshot(repo.client())
    repo.issues[46] = {
        "state": "open",
        "labels": ["module:leads", "demo"],
        "title": "Vague live issue",
    }
    repo.issues[7]["state"] = "closed"  # a backlog issue closed during the demo
    repo.issues[6]["labels"] = ["module:platform", "type:feature", "needs-info"]
    repo.prs[47] = {"state": "open", "merged": False, "ref": "demo-copy-fix", "labels": ["tier:T0"]}
    repo.prs[48] = {"state": "closed", "merged": True, "ref": "demo-merged", "labels": []}
    repo.branches |= {"demo-copy-fix", "demo-merged", "scratch"}
    repo.comments[47] = [
        {"id": 1, "body": f"{RISK}\n## Risk review: T0"},
        {"id": 2, "body": "Geoff: looks good"},
    ]
    repo.issues[49] = {
        "state": "open",
        "labels": ["incident", "module:pipeline", "demo"],
        "title": "Down",
    }
    repo.deployments[501] = {"sha": "merge-48", "state": "success"}  # the demo PR's release
    # Real development in the same weeks: unmarked, so the reset keeps all of it.
    repo.issues[50] = {"state": "open", "labels": ["module:platform"], "title": "Real bug"}
    repo.prs[51] = {"state": "closed", "merged": True, "ref": "phase-6-accuracy", "labels": []}
    repo.prs[52] = {"state": "open", "merged": False, "ref": "phase-6-more", "labels": []}
    repo.branches |= {"phase-6-accuracy", "phase-6-more"}
    repo.deployments[502] = {"sha": "merge-51", "state": "success"}
    return baseline


def test_a_reset_undoes_the_demo_and_never_touches_the_baseline(tmp_path):
    repo = Repo()
    baseline = after_a_demo(repo)
    save_baseline(baseline, tmp_path / "baseline.json")
    assert load_baseline(tmp_path / "baseline.json") == baseline

    p = plan(repo.client(), baseline)
    assert (p.demo_issues, sorted(p.demo_prs), p.demo_deployments) == ([46, 49], [47, 48], 1)
    done, failed = apply_plan(repo.client(), p)
    assert failed == []

    assert repo.issues[46]["state"] == "closed"  # opened live: closed (can't be deleted)
    # A demo incident is closed and stops being an incident; the demo's deployment is deleted.
    assert (repo.issues[49]["state"], repo.issues[49]["labels"]) == (
        "closed",
        ["module:pipeline", "demo"],
    )
    # Real work is never touched: its issue, PRs, branches and release all stay.
    assert repo.issues[50]["state"] == "open"
    assert repo.prs[52]["state"] == "open"
    assert list(repo.deployments) == [502]
    assert {"phase-6-accuracy", "phase-6-more"} <= repo.branches
    assert (p.real_issues, sorted(p.real_prs)) == ([50], [51, 52])
    assert any("Kept as real work" in x for x in p.left_behind)
    assert repo.issues[7]["state"] == "open"  # the backlog is back as it was
    assert repo.issues[6]["labels"] == ["module:leads", "type:feature"]
    assert repo.prs[47]["state"] == "closed" and repo.prs[47]["labels"] == []
    assert [c["id"] for c in repo.comments[47]] == [2]  # a person's comment stays
    # The open demo PR's branch goes; the merged one's too (it was the demo's); "scratch" has no PR.
    assert repo.branches == {
        "main",
        "phase-4-agents",
        "scratch",
        "phase-6-accuracy",
        "phase-6-more",
    }
    assert "phase-4-agents" in repo.branches and "main" in repo.branches  # baseline untouched
    assert any("PR #48 was merged" in x for x in p.left_behind)
    assert any("scratch" in x and "no PR" in x for x in p.left_behind)
    assert not any("/pulls/3" in path or "phase-4-agents" in path for _, path in repo.writes)
    real = ("/issues/50", "/pulls/51", "/pulls/52", "/issues/52", "phase-6", "deployments/502")
    assert not any(r in path for _, path in repo.writes for r in real)

    assert plan(repo.client(), baseline).actions == []  # a second reset has nothing to do


def test_a_reset_refuses_another_repositorys_baseline():
    repo = Repo()
    baseline = {**snapshot(repo.client()), "repo": "someone/else"}
    with pytest.raises(SystemExit, match="baseline is for someone/else"):
        plan(repo.client(), baseline)


def test_the_database_forgets_demo_items_and_keeps_the_rest(db):
    for n in (5, 47):
        db.add(
            PullRequest(
                source="github",
                external_id=f"pr-{n}",
                number=n,
                title=f"PR {n}",
                state="open",
                created_at=datetime(2026, 9, 24, 9),
            )
        )
    db.commit()
    for n, kind in ((5, "pr"), (47, "pr"), (46, "issue"), (8, "issue"), (47, "release")):
        record_decision(
            db,
            agent={"pr": "pr_risk", "issue": "triage", "release": "release_gate"}[kind],
            agent_version="v1",
            subject_type=kind,
            subject_source="github",
            subject_id=n,
            trigger="poll",
            head_sha=f"s{n}",
            status="ok",
        )
    demo_pr = db.query(PullRequest).filter_by(number=47).one()
    db.add(
        Approval(
            pull_request_id=demo_pr.id,
            approver_id="simulated-second",
            tier="T3",
            status="pending",
            requested_at=datetime(2026, 9, 24, 9),
        )
    )
    db.commit()

    result = reset_database(db, demo_issues=[46], demo_prs=[47])
    assert result["audit_rows_forgotten"] == 3
    left = sorted(
        (d.subject_type, d.subject_id)
        for d in db.query(AgentDecision).filter_by(subject_source="github")
    )
    assert left == [("issue", 8), ("pr", 5)]
    assert db.query(Approval).count() == 0
    assert result["history"]["sprints"] == 13  # and the simulated history is fresh


def test_the_checklist_flags_mode_off_and_sums_up():
    assert _mode("off").state == "FAIL" and _mode("shadow").state == "WARN"
    assert _mode("enforce").state == "PASS"
    text = describe([Check("A", "PASS", "ok"), Check("B", "FAIL", "fix it")])
    assert text.endswith("Not ready: 1 check(s) failed.")
    assert describe([Check("A", "PASS", "ok")]).endswith("Ready for the demo.")
