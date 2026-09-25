"""Stand-ins for Claude and GitHub, so the tests never spend money or touch the network."""

import json
from types import SimpleNamespace

import anthropic
import httpx2

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def answer(adjustment=0, reasons=None, gaps=None, justification="Looks routine."):
    return {
        "adjustment": adjustment,
        "justification": justification,
        "top_reasons": reasons or ["Reason one.", "Reason two.", "Reason three."],
        "test_gaps": gaps or [],
    }


def response(data=None, *, text=None, stop_reason="end_turn", tokens=(1200, 150, 900, 0)):
    """A Messages API response carrying `data` as JSON (or raw `text`)."""
    body = text if text is not None else json.dumps(data if data is not None else answer())
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=body)],
        stop_reason=stop_reason,
        model="claude-sonnet-5",
        usage=SimpleNamespace(
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            cache_read_input_tokens=tokens[2],
            cache_creation_input_tokens=tokens[3],
        ),
        _request_id="req_test",
    )


def timeout_error():
    return anthropic.APITimeoutError(request=REQUEST)


def rate_limit_error():
    return anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=REQUEST), body=None
    )


def server_error():
    return anthropic.InternalServerError(
        "boom", response=httpx2.Response(500, request=REQUEST), body=None
    )


class FakeAnthropic:
    """Plays back a list of responses (or exceptions to raise) and records every request."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# --- a fake GitHub ---------------------------------------------------------------------------

import json as _json  # noqa: E402
import re as _re  # noqa: E402

import httpx  # noqa: E402

REPO = "geoffsmattie/pragmattie-sync"


class FakeGitHub:
    """Just enough of GitHub's REST API for the risk agent, with every request recorded."""

    def __init__(self):
        self.prs: dict[int, dict] = {}
        self.issues: dict[int, dict] = {}
        self.diffs: dict[int, str] = {}
        self.files: dict[int, list[str]] = {}
        self.comments: dict[int, list[dict]] = {}
        self.labels: dict[int, set[str]] = {}
        self.statuses: list[dict] = []
        self.requests: list[tuple[str, str]] = []  # (method, path) of everything, reads too
        self.fail: set[str] = set()  # any request whose path contains one of these gets a 500
        self.runs: dict[str, list[dict]] = {}  # head sha -> Actions workflow runs
        self.jobs: dict[int, list[dict]] = {}  # run id -> its jobs, every attempt
        self.deploy_runs: list[dict] = []  # the deploy workflow's runs, newest first
        self.deployments: list[dict] = []  # {id, sha, environment, statuses: [newest first]}
        self._ids = 1000

    # -- test helpers -------------------------------------------------------------------------

    def open_pr(
        self, number, sha, *, files=None, title="Add lead filter", draft=False, body="Adds it."
    ):
        self.prs[number] = {
            "number": number,
            "title": title,
            "body": body,
            "state": "open",
            "draft": draft,
            "user": {"login": "geoff"},
            "labels": [],
            "created_at": "2026-09-21T09:00:00Z",
            "closed_at": None,
            "head": {"sha": sha},
        }
        default_files = ["apps/web/src/views/LeadsView.vue", "apps/web/tests/leads.spec.js"]
        self.files[number] = files or default_files
        self.diffs[number] = "".join(
            f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n+change\n" for f in self.files[number]
        )

    def merge(self, number, merge_sha, merged_at="2026-09-21T10:00:00Z"):
        """Merge a PR: it leaves the open list and `merge_sha` becomes its merge commit."""
        pr = self.prs[number]
        pr.update(state="closed", merged_at=merged_at, closed_at=merged_at)
        pr["merge_commit_sha"] = merge_sha

    def open_incident(self, number, module, *, state="open", created="2026-09-21T11:00:00Z"):
        """An issue labelled as a production incident in `module`."""
        self.issues[number] = {
            "number": number,
            "title": f"{module} is down",
            "body": "Customers can't load it.",
            "state": state,
            "labels": [{"name": "incident"}, {"name": f"module:{module}"}],
            "user": {"login": "geoff"},
            "created_at": created,
            "closed_at": "2026-09-21T12:00:00Z" if state == "closed" else None,
            "updated_at": created,
        }

    def deploy_run(self, sha, status="in_progress"):
        """A run of the deploy workflow on `sha` (newest first, as GitHub lists them)."""
        self.deploy_runs.insert(0, {"head_sha": sha, "status": status})

    def deployment(self, sha, environment="production", state="success", at="2026-09-21T12:00:00Z"):
        self._ids += 1
        self.deployments.append(
            {
                "id": self._ids,
                "sha": sha,
                "environment": environment,
                "statuses": [{"state": state, "created_at": at}],
            }
        )
        return self._ids

    def push(self, number, sha):
        self.prs[number]["head"]["sha"] = sha

    def open_issue(
        self,
        number,
        *,
        title="Lead import is slow",
        body="It times out on big files.",
        state="open",
    ):
        self.issues[number] = {
            "number": number,
            "title": title,
            "body": body,
            "state": state,
            "user": {"login": "someone"},
            "created_at": "2026-09-21T09:00:00Z",
            "updated_at": "2026-09-21T09:00:00Z",
        }

    def edit_issue(self, number, *, title=None, body=None):
        if title is not None:
            self.issues[number]["title"] = title
        if body is not None:
            self.issues[number]["body"] = body

    def comment_on(self, number, marker="pragmattie-risk-gate"):
        mine = [c for c in self.comments.get(number, []) if marker in c["body"]]
        return mine[0] if mine else None

    def human_comment(self, number, body, login="geoff"):
        """A comment a person leaves on the PR (e.g. a `/tier` command)."""
        self._ids += 1
        comment = {
            "id": self._ids,
            "body": body,
            "user": {"login": login},
            "html_url": f"https://github.com/{REPO}/pull/{number}#issuecomment-{self._ids}",
        }
        self.comments.setdefault(number, []).append(comment)
        return comment

    def ci(self, sha, jobs):
        """One CI run on `sha`. `jobs` maps a job name to its conclusions, one per attempt
        (None while running), e.g. {"Web (tests + build)": ["failure", "success"]}."""
        self._ids += 1
        run_id = self._ids
        self.runs.setdefault(sha, []).append(
            {"id": run_id, "head_sha": sha, "created_at": f"2026-09-21T09:{len(self.runs):02d}:00Z"}
        )
        self.jobs[run_id] = [
            {
                "name": name,
                "run_attempt": attempt,
                "conclusion": conclusion,
                "started_at": "2026-09-21T09:00:00Z",
                "completed_at": "2026-09-21T09:03:00Z" if conclusion else None,
            }
            for name, conclusions in jobs.items()
            for attempt, conclusion in enumerate(conclusions, 1)
        ]

    def tick(self, number, label):
        comment = self.comment_on(number)
        comment["body"] = comment["body"].replace(f"- [ ] **{label}", f"- [x] **{label}")

    @property
    def writes(self):
        return [(m, p) for m, p in self.requests if m != "GET"]

    def client(self):
        from sdlc.github_client import GitHubClient

        return GitHubClient(token="t", repo=REPO, transport=httpx.MockTransport(self.handle))

    def _should_fail(self, method: str, path: str) -> bool:
        """Each entry in `fail` is a bare path substring (any method) or "METHOD:substring"."""
        for rule in self.fail:
            want_method, _, want_path = rule.partition(":")
            if want_path and want_method in ("GET", "POST", "PATCH", "DELETE"):
                if method == want_method and want_path in path:
                    return True
            elif rule in path:
                return True
        return False

    # -- the API ------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests.append((method, path))
        body = _json.loads(request.content) if request.content else {}
        if self._should_fail(method, path):
            return httpx.Response(500, json={"message": "fake github: boom"})
        base = f"/repos/{REPO}"

        params = request.url.params
        if method == "GET" and path == f"{base}/pulls":
            want = params.get("state", "open")
            return httpx.Response(
                200, json=[p for p in self.prs.values() if want == "all" or p["state"] == want]
            )
        if method == "GET" and path == f"{base}/issues":
            want = params.get("state", "open")
            label = params.get("labels")
            return httpx.Response(
                200,
                json=[
                    i
                    for i in self.issues.values()
                    if (want == "all" or i["state"] == want)
                    and (not label or label in {x["name"] for x in i.get("labels", [])})
                ],
            )
        if method == "GET" and (m := _re.fullmatch(rf"{base}/commits/(\w+)/pulls", path)):
            return httpx.Response(
                200, json=[p for p in self.prs.values() if p.get("merge_commit_sha") == m[1]]
            )
        if method == "GET" and path == f"{base}/actions/workflows/deploy.yml/runs":
            return httpx.Response(200, json={"workflow_runs": self.deploy_runs})
        if method == "GET" and path == f"{base}/deployments":
            env = params.get("environment")
            rows = [d for d in self.deployments if not env or d["environment"] == env]
            return httpx.Response(
                200, json=[{k: v for k, v in d.items() if k != "statuses"} for d in rows]
            )
        if m := _re.fullmatch(rf"{base}/deployments/(\d+)/statuses", path):
            d = next(d for d in self.deployments if d["id"] == int(m[1]))
            if method == "POST":
                d["statuses"].insert(
                    0, {"state": body["state"], "created_at": "2026-09-22T00:00:00Z"}
                )
                return httpx.Response(201, json={})
            return httpx.Response(200, json=d["statuses"])
        if method == "DELETE" and (m := _re.fullmatch(rf"{base}/deployments/(\d+)", path)):
            self.deployments = [d for d in self.deployments if d["id"] != int(m[1])]
            return httpx.Response(204)
        if method == "GET" and (m := _re.fullmatch(rf"{base}/issues/(\d+)", path)):
            return httpx.Response(200, json=self.issues[int(m[1])])
        if m := _re.fullmatch(rf"{base}/pulls/(\d+)", path):
            n = int(m[1])
            if "diff" in request.headers.get("accept", ""):
                return httpx.Response(200, text=self.diffs[n])
            pr = {
                "merged_at": None,
                **self.prs[n],
                "changed_files": len(self.files[n]),
                "additions": 40,
                "deletions": 10,
                "commits": 1,
            }
            return httpx.Response(200, json=pr)
        if m := _re.fullmatch(rf"{base}/pulls/(\d+)/files", path):
            return httpx.Response(200, json=[{"filename": f} for f in self.files[int(m[1])]])
        if _re.fullmatch(rf"{base}/pulls/\d+/reviews", path):
            return httpx.Response(200, json=[])
        if m := _re.fullmatch(rf"{base}/issues/(\d+)/comments", path):
            n = int(m[1])
            if method == "POST":
                self._ids += 1
                comment = {"id": self._ids, "body": body["body"]}
                self.comments.setdefault(n, []).append(comment)
                return httpx.Response(201, json=comment)
            return httpx.Response(200, json=self.comments.get(n, []))
        if method == "PATCH" and (m := _re.fullmatch(rf"{base}/issues/comments/(\d+)", path)):
            cid = int(m[1])
            for comments in self.comments.values():
                for c in comments:
                    if c["id"] == cid:
                        c["body"] = body["body"]
                        return httpx.Response(200, json=c)
        if method == "POST" and (m := _re.fullmatch(rf"{base}/statuses/(\w+)", path)):
            self.statuses.append({"sha": m[1], **body})
            return httpx.Response(201, json={})
        if method == "GET" and path == f"{base}/actions/runs":
            runs = self.runs.get(request.url.params.get("head_sha"), [])
            return httpx.Response(200, json={"total_count": len(runs), "workflow_runs": runs})
        if method == "GET" and (m := _re.fullmatch(rf"{base}/actions/runs/(\d+)/jobs", path)):
            jobs = self.jobs.get(int(m[1]), [])
            return httpx.Response(200, json={"total_count": len(jobs), "jobs": jobs})
        if method == "POST" and path == f"{base}/labels":
            return httpx.Response(201, json={})
        if m := _re.fullmatch(rf"{base}/issues/(\d+)/labels", path):
            n = int(m[1])
            if method == "POST":
                self.labels.setdefault(n, set()).update(body["labels"])
                return httpx.Response(200, json=[])
            return httpx.Response(
                200, json=[{"name": x} for x in sorted(self.labels.get(n, set()))]
            )
        if method == "DELETE" and (m := _re.fullmatch(rf"{base}/issues/(\d+)/labels/(.+)", path)):
            self.labels.get(int(m[1]), set()).discard(m[2])
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": f"fake github: no route for {method} {path}"})

    def last_status(self, sha=None):
        rows = [s for s in self.statuses if sha is None or s["sha"] == sha]
        return rows[-1] if rows else None


def triage_answer(
    module="leads",
    type="bug",
    priority="p2",
    points=3,
    duplicate_of=0,
    confidence=0.8,
    questions=None,
    rationale="Looks like a bug in lead import.",
):
    return {
        "module": module,
        "type": type,
        "priority": priority,
        "estimate_points": points,
        "duplicate_of": duplicate_of,
        "confidence": confidence,
        "rationale": rationale,
        "questions": questions or [],
    }
