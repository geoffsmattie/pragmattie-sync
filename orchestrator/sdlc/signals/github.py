"""Collect issues, pull requests, reviews and CI runs from the GitHub repository.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.signals.github

Re-running is safe: rows are matched on (source="github", external_id) and updated in place.

Label conventions (created by `python -m sdlc.backlog`):
    module:<name>    leads, accounts, pipeline, forecasting, integrations, billing_auth, ...
    type:<kind>      feature, bug, chore
    priority:<p>     p1, p2, p3
    points:<n>       story-point estimate
    caused-incident  set on a PR after it caused a production incident
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.db import SessionLocal
from sdlc.github_client import GitHubClient, GitHubError, parse_time
from sdlc.tables import CIRun, Engineer, Issue, PullRequest

SOURCE = "github"

# Map CI job names (from .github/workflows/ci.yml) to suite names used in the metrics.
JOB_SUITES = {
    "API (lint + tests)": "api",
    "API (migrations on MySQL)": "migrations",
    "Web (tests + build)": "web",
    "Orchestrator (lint + tests)": "orchestrator",
}

# Infer a module from file paths when a PR has no module: label.
PATH_MODULES = [
    (re.compile(r"(^|/)(leads|lead)[^/]*\b"), "leads"),
    (re.compile(r"(^|/)accounts?[^/]*\b|AccountDetail"), "accounts"),
    (re.compile(r"(^|/)(opportunities|pipeline)[^/]*|PipelineView"), "pipeline"),
    (re.compile(r"forecast", re.I), "forecasting"),
    (re.compile(r"^orchestrator/"), "orchestrator"),
]


def labels_of(item: dict) -> dict[str, str]:
    """{"module": "leads", "type": "bug", ...} from labels like "module:leads"."""
    out = {}
    for label in item.get("labels", []):
        name = label["name"] if isinstance(label, dict) else label
        if ":" in name:
            key, value = name.split(":", 1)
            out[key.strip()] = value.strip()
        else:
            out[name] = "true"
    return out


def infer_module(paths: list[str]) -> str:
    votes: dict[str, int] = {}
    for path in paths:
        for pattern, module in PATH_MODULES:
            if pattern.search(path):
                votes[module] = votes.get(module, 0) + 1
                break
    return max(votes, key=votes.get) if votes else "platform"


class Collector:
    def __init__(self, db: Session, client: GitHubClient):
        self.db = db
        self.gh = client
        self._engineers: dict[str, Engineer] = {}

    def engineer(self, user: dict | None) -> Engineer | None:
        if not user:
            return None
        login = user["login"]
        if login not in self._engineers:
            found = self.db.scalar(
                select(Engineer).where(Engineer.source == SOURCE, Engineer.login == login)
            )
            if not found:
                found = Engineer(login=login, name=login, source=SOURCE)
                self.db.add(found)
                self.db.flush()
            self._engineers[login] = found
        return self._engineers[login]

    def _upsert(self, model, external_id: str, **values):
        row = self.db.scalar(
            select(model).where(model.source == SOURCE, model.external_id == external_id)
        )
        if row is None:
            row = model(source=SOURCE, external_id=external_id)
            self.db.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        self.db.flush()
        return row

    def collect_issues(self) -> int:
        count = 0
        for item in self.gh.paginate("/repos/{repo}/issues", state="all"):
            if "pull_request" in item:  # the issues endpoint also returns PRs
                continue
            labels = labels_of(item)
            assignee = self.engineer(item.get("assignee"))
            points = labels.get("points")
            created, closed = parse_time(item["created_at"]), parse_time(item.get("closed_at"))
            self._upsert(
                Issue,
                f"issue-{item['number']}",
                number=item["number"],
                title=item["title"][:300],
                module=labels.get("module"),
                type=labels.get("type", "feature"),
                priority=labels.get("priority"),
                estimate_points=int(points) if points and points.isdigit() else None,
                state=item["state"],
                created_at=created,
                closed_at=closed,
                actual_days=round((closed - created).total_seconds() / 86400, 1)
                if closed
                else None,
                assignee_id=assignee.id if assignee else None,
            )
            count += 1
        return count

    def collect_pull_requests(self) -> int:
        count = 0
        for item in self.gh.paginate("/repos/{repo}/pulls", state="all"):
            number = item["number"]
            detail = self.gh.get(f"/repos/{{repo}}/pulls/{number}")
            files = [
                f["filename"] for f in self.gh.paginate(f"/repos/{{repo}}/pulls/{number}/files")
            ]
            reviews = list(self.gh.paginate(f"/repos/{{repo}}/pulls/{number}/reviews"))
            created = parse_time(item["created_at"])
            submitted = sorted(
                parse_time(r["submitted_at"]) for r in reviews if r.get("submitted_at")
            )
            labels = labels_of(item)
            linked = re.search(
                r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #(\d+)", item.get("body") or "", re.I
            )
            issue = None
            if linked:
                issue = self.db.scalar(
                    select(Issue).where(
                        Issue.source == SOURCE, Issue.external_id == f"issue-{linked[1]}"
                    )
                )
            merged_at = parse_time(detail.get("merged_at"))
            author = self.engineer(item.get("user"))
            self._upsert(
                PullRequest,
                f"pr-{number}",
                number=number,
                title=item["title"][:300],
                author_id=author.id if author else None,
                issue_id=issue.id if issue else None,
                module=labels.get("module") or infer_module(files),
                files_changed=detail.get("changed_files", len(files)),
                additions=detail.get("additions", 0),
                deletions=detail.get("deletions", 0),
                touches_migration=any("alembic/versions/" in f for f in files),
                review_count=len(reviews),
                first_review_hours=round((submitted[0] - created).total_seconds() / 3600, 1)
                if submitted
                else None,
                rework_commits=max(0, detail.get("commits", 1) - 1),
                state="merged" if merged_at else item["state"],
                created_at=created,
                merged_at=merged_at,
                closed_at=parse_time(item.get("closed_at")),
                caused_incident="caused-incident" in labels,
                reverted=item["title"].lower().startswith("revert"),
            )
            count += 1
        return count

    def collect_ci_runs(self) -> int:
        count = 0
        for run in self.gh.paginate("/repos/{repo}/actions/runs", key="workflow_runs"):
            pr = None
            if run.get("pull_requests"):
                pr = self.db.scalar(
                    select(PullRequest).where(
                        PullRequest.source == SOURCE,
                        PullRequest.external_id == f"pr-{run['pull_requests'][0]['number']}",
                    )
                )
            jobs = list(
                self.gh.paginate(
                    f"/repos/{{repo}}/actions/runs/{run['id']}/jobs", key="jobs", filter="all"
                )
            )
            # A job that failed and then passed on a re-run of the same commit is flaky.
            passed_later = {
                (j["name"], j.get("run_attempt", 1))
                for j in jobs
                if j.get("conclusion") == "success"
            }
            for job in jobs:
                if not job.get("conclusion"):
                    continue  # still running
                attempt = job.get("run_attempt", 1)
                flaky = job["conclusion"] == "failure" and any(
                    name == job["name"] and later > attempt for name, later in passed_later
                )
                started, finished = parse_time(job["started_at"]), parse_time(job["completed_at"])
                self._upsert(
                    CIRun,
                    f"job-{job['id']}",
                    pull_request_id=pr.id if pr else None,
                    suite=JOB_SUITES.get(job["name"], job["name"][:40]),
                    conclusion=job["conclusion"],
                    flaky=flaky,
                    started_at=started,
                    duration_seconds=int((finished - started).total_seconds())
                    if started and finished
                    else 0,
                )
                count += 1
        return count

    def run(self) -> dict[str, int]:
        counts = {
            "issues": self.collect_issues(),
            "pull_requests": self.collect_pull_requests(),
            "ci_jobs": self.collect_ci_runs(),
        }
        self.db.commit()
        return counts


def main() -> None:
    try:
        client = GitHubClient()
    except GitHubError as err:
        raise SystemExit(str(err)) from err
    with SessionLocal() as db:
        counts = Collector(db, client).run()
    print(f"Collected from {client.repo}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
