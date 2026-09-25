"""Collect issues, pull requests, reviews and CI runs from the GitHub repository.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.signals.github

Re-running is safe: rows are matched on (source="github", external_id) and updated in place.

Label conventions (created by `python -m sdlc.backlog`):
    module:<name>    leads, accounts, pipeline, forecasting, integrations, billing_auth, ...
    type:<kind>      feature, bug, chore
    priority:<p>     p1, p2, p3
    points:<n>       story-point estimate
    epic:<name>      the epic a story belongs to (e.g. epic:AI lead scoring)
    caused-incident  set on a PR after it caused a production incident
    incident         an issue that reports a production incident (with module:<name> and,
                     optionally, sev1/sev2/sev3). It is stored as an incident, not as work:
                     open means ongoing, closed means resolved. The release gate holds a release
                     that touches the module of an open one.

Deployments come from GitHub's own deployment records (the deploy workflow creates them in the
release gate's environments); only ones that reached `success` are stored.
"""

import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.changes import classify_files, infer_module
from sdlc.db import SessionLocal
from sdlc.github_client import GitHubClient, GitHubError, parse_time
from sdlc.tables import CIRun, Deployment, Engineer, Incident, Issue, PullRequest

SOURCE = "github"
INCIDENT_LABEL = "incident"
DEPLOY_WORKFLOW_PATH = ".github/workflows/deploy.yml"
SEVERITIES = ("sev1", "sev2", "sev3")
INCIDENT_AFTER_DEPLOY = timedelta(hours=24)  # an incident this soon after a deploy is its fault

# Map CI job names (from .github/workflows/ci.yml) to suite names used in the metrics.
JOB_SUITES = {
    "API (lint + tests)": "api",
    "API (migrations on MySQL)": "migrations",
    "Web (tests + build)": "web",
    "Orchestrator (lint + tests)": "orchestrator",
}


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
            if is_incident(item):
                continue  # an incident, not work: see collect_incidents
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
                epic=labels.get("epic"),
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
            self.collect_pull_request(item)
            count += 1
        return count

    def collect_pull_request(self, item: dict) -> PullRequest:
        """Store one PR, given its entry from the pulls list (or the PR object itself)."""
        number = item["number"]
        detail = self.gh.get(f"/repos/{{repo}}/pulls/{number}")
        files = [f["filename"] for f in self.gh.paginate(f"/repos/{{repo}}/pulls/{number}/files")]
        reviews = list(self.gh.paginate(f"/repos/{{repo}}/pulls/{number}/reviews"))
        created = parse_time(item["created_at"])
        submitted = sorted(parse_time(r["submitted_at"]) for r in reviews if r.get("submitted_at"))
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
        facts = classify_files(files)
        return self._upsert(
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
            touches_migration=facts.touches_migration,
            test_files_changed=facts.test_files_changed,
            docs_only=facts.docs_only,
            modules_touched=facts.modules_touched,
            review_count=len(reviews),
            first_review_hours=round((submitted[0] - created).total_seconds() / 3600, 1)
            if submitted
            else None,
            rework_commits=max(0, detail.get("commits", 1) - 1),
            state="merged" if merged_at else item["state"],
            created_at=created,
            merged_at=merged_at,
            merge_commit_sha=detail.get("merge_commit_sha") if merged_at else None,
            closed_at=parse_time(item.get("closed_at")),
            caused_incident="caused-incident" in labels,
            reverted=item["title"].lower().startswith("revert"),
        )

    def collect_ci_runs(self) -> int:
        count = 0
        for run in self.gh.paginate("/repos/{repo}/actions/runs", key="workflow_runs"):
            if run.get("path", "").endswith(DEPLOY_WORKFLOW_PATH):
                continue  # deploys, not tests: the release gate reads those
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

    def collect_deployments(self, environments: tuple[str, ...]) -> int:
        """GitHub deployments to these environments that succeeded, as Deployment rows.

        Rows for deployments GitHub no longer has (the demo reset deletes them) are removed."""
        seen = set()
        for env in environments:
            for item in self.gh.paginate("/repos/{repo}/deployments", environment=env):
                external_id = f"deployment-{item['id']}"
                seen.add(external_id)
                known = self.db.scalar(
                    select(Deployment).where(
                        Deployment.source == SOURCE, Deployment.external_id == external_id
                    )
                )
                if known:
                    continue  # stored once it succeeded; that never changes
                statuses = self.gh.get(f"/repos/{{repo}}/deployments/{item['id']}/statuses")
                done = next((st for st in statuses if st.get("state") == "success"), None)
                if done:
                    self._upsert(
                        Deployment,
                        external_id,
                        version=item["sha"][:7],
                        sha=item["sha"],
                        deployed_at=parse_time(done["created_at"]),
                        pr_count=0,
                        status="success",
                    )
        gone = [
            d
            for d in self.db.scalars(select(Deployment).where(Deployment.source == SOURCE))
            if d.external_id not in seen
        ]
        for d in gone:
            for incident in self.db.scalars(select(Incident).where(Incident.deployment_id == d.id)):
                incident.deployment_id = None
            self.db.delete(d)
        self.db.flush()
        return len(seen)

    def collect_incidents(self) -> int:
        """Issues labelled `incident`, as Incident rows (open = ongoing, closed = resolved).

        An incident opened within a day of a real deploy is counted against that deploy, which is
        what the release gate's failure rate reads."""
        count = 0
        deploys = sorted(
            self.db.scalars(
                select(Deployment).where(
                    Deployment.source == SOURCE, Deployment.status == "success"
                )
            ),
            key=lambda d: d.deployed_at,
        )
        for item in self.gh.paginate("/repos/{repo}/issues", state="all", labels=INCIDENT_LABEL):
            if "pull_request" in item or not is_incident(item):
                continue
            labels = labels_of(item)
            opened = parse_time(item["created_at"])
            before = [d for d in deploys if d.deployed_at <= opened]
            cause = (
                before[-1]
                if before and opened - before[-1].deployed_at <= INCIDENT_AFTER_DEPLOY
                else None
            )
            self._upsert(
                Incident,
                f"issue-{item['number']}",
                title=item["title"][:200],
                severity=next((s for s in SEVERITIES if s in labels), "sev2"),
                module=labels.get("module"),
                opened_at=opened,
                resolved_at=parse_time(item.get("closed_at")),
                deployment_id=cause.id if cause else None,
            )
            count += 1
        return count

    def run(self, environments: tuple[str, ...] = ()) -> dict[str, int]:
        counts = {
            "issues": self.collect_issues(),
            "pull_requests": self.collect_pull_requests(),
            "ci_jobs": self.collect_ci_runs(),
        }
        if environments:
            counts["deployments"] = self.collect_deployments(environments)
        counts["incidents"] = self.collect_incidents()
        self.db.commit()
        return counts


def is_incident(item: dict) -> bool:
    return INCIDENT_LABEL in labels_of(item)


def main() -> None:
    from sdlc.tiers import load_policy

    try:
        client = GitHubClient()
    except GitHubError as err:
        raise SystemExit(str(err)) from err
    rules = load_policy().release
    with SessionLocal() as db:
        counts = Collector(db, client).run((rules.environment, rules.signoff_environment))
    print(f"Collected from {client.repo}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
