"""Everything the agents do to GitHub, in one place, so the mode switch can stop all of it.

Reads (a PR's details, its diff, the current comment) always work. Every write goes through
`_write`, which does nothing when ORCHESTRATOR_MODE is `off` and reports what happened either way,
so the audit row records the effects. One failing write never stops the others.

Writes the agents can make, and nothing else: one comment per PR or issue (kept up to date), a
handful of prefixed labels (`tier:Tn` on PRs; `module:`/`type:`/`priority:`/`points:` on issues),
plain add-only labels (`needs-info`, `possible-duplicate`), and two commit statuses: `risk-gate`
on PR commits and `release-gate` on release commits in `main`.
They never merge, approve, close, push, edit issue text, or edit branch protection.
"""

from collections.abc import Callable

from sdlc.agents.comment import MARKER
from sdlc.backlog import LABEL_COLORS
from sdlc.github_client import GitHubClient, GitHubError

STATUS_CONTEXT = "risk-gate"
TIER_LABELS = {"T0": "0E8A16", "T1": "FBCA04", "T2": "F9A03F", "T3": "B60205"}
TIER_LABEL_DESCRIPTION = "Governance tier set by the PR risk agent"
DIMENSION_DESCRIPTION = "Set by the triage agent"


class Effects:
    def __init__(self, gh: GitHubClient, mode: str):
        self.gh = gh
        self.mode = mode

    # --- reads: always allowed ---------------------------------------------------------------

    def read_pr(self, number: int) -> dict:
        return self.gh.get(f"/repos/{{repo}}/pulls/{number}")

    def read_diff(self, number: int) -> str:
        return self.gh.get_text(f"/repos/{{repo}}/pulls/{number}", "application/vnd.github.diff")

    def read_files(self, number: int) -> list[str]:
        return [f["filename"] for f in self.gh.paginate(f"/repos/{{repo}}/pulls/{number}/files")]

    def read_comments(self, number: int) -> list[dict]:
        """Every comment on this PR or issue, oldest first."""
        return list(self.gh.paginate(f"/repos/{{repo}}/issues/{number}/comments"))

    def find_comment(
        self, number: int, marker: str = MARKER, comments: list[dict] | None = None
    ) -> dict | None:
        """An agent's own comment on this PR or issue, found by its HTML marker."""
        for comment in comments if comments is not None else self.read_comments(number):
            if marker in (comment.get("body") or ""):
                return comment
        return None

    def read_issue(self, number: int) -> dict:
        return self.gh.get(f"/repos/{{repo}}/issues/{number}")

    def read_labels(self, number: int) -> list[str]:
        return [label["name"] for label in self.gh.get(f"/repos/{{repo}}/issues/{number}/labels")]

    # --- writes: gated by the mode -----------------------------------------------------------

    def _write(self, name: str, action: Callable[[], dict]) -> dict:
        if self.mode == "off":
            return {"skipped": "mode is off"}
        try:
            return {"done": name, **action()}
        except GitHubError as err:
            return {"error": str(err)[:300]}

    def upsert_comment(self, number: int, body: str, existing: dict | None) -> dict:
        def action() -> dict:
            if existing:
                self.gh.patch(f"/repos/{{repo}}/issues/comments/{existing['id']}", {"body": body})
                return {"comment_id": existing["id"], "created": False}
            created = self.gh.post(f"/repos/{{repo}}/issues/{number}/comments", {"body": body})
            return {"comment_id": created["id"], "created": True}

        return self._write("comment", action)

    def set_status(
        self, sha: str, state: str, description: str, context: str = STATUS_CONTEXT
    ) -> dict:
        def action() -> dict:
            self.gh.post(
                f"/repos/{{repo}}/statuses/{sha}",
                {"state": state, "context": context, "description": description[:140]},
            )
            return {"state": state}

        return self._write("status", action)

    def set_tier_label(self, number: int, tier: str) -> dict:
        wanted = f"tier:{tier}"

        def action() -> dict:
            current = [
                label["name"] for label in self.gh.get(f"/repos/{{repo}}/issues/{number}/labels")
            ]
            for name in current:
                if name.startswith("tier:") and name != wanted:
                    self.gh.delete(f"/repos/{{repo}}/issues/{number}/labels/{name}")
            if wanted not in current:
                try:
                    self.gh.post(
                        "/repos/{repo}/labels",
                        {
                            "name": wanted,
                            "color": TIER_LABELS[tier],
                            "description": TIER_LABEL_DESCRIPTION,
                        },
                    )
                except GitHubError:
                    pass  # it already exists
                self.gh.post(f"/repos/{{repo}}/issues/{number}/labels", {"labels": [wanted]})
            return {"label": wanted}

        return self._write("label", action)

    def set_dimension_label(self, number: int, prefix: str, value: str) -> dict:
        """Replace whatever `<prefix>:*` label an issue has with `<prefix>:<value>`.

        Same shape as `set_tier_label`, generalised for the triage agent's four dimensions
        (module, type, priority, points), whose colours already exist in sdlc/backlog.py.
        """
        wanted = f"{prefix}:{value}"

        def action() -> dict:
            current = self.read_labels(number)
            for name in current:
                if name.startswith(f"{prefix}:") and name != wanted:
                    self.gh.delete(f"/repos/{{repo}}/issues/{number}/labels/{name}")
            if wanted not in current:
                try:
                    self.gh.post(
                        "/repos/{repo}/labels",
                        {
                            "name": wanted,
                            "color": LABEL_COLORS[prefix],
                            "description": DIMENSION_DESCRIPTION,
                        },
                    )
                except GitHubError:
                    pass  # it already exists
                self.gh.post(f"/repos/{{repo}}/issues/{number}/labels", {"labels": [wanted]})
            return {"label": wanted}

        return self._write("label", action)

    def add_label_if_absent(self, number: int, name: str, color: str, description: str) -> dict:
        """Add a plain flag label (needs-info, possible-duplicate). Never removed automatically:
        a human clears it once they've dealt with it."""

        def action() -> dict:
            if name in self.read_labels(number):
                return {"label": name, "already_present": True}
            try:
                self.gh.post(
                    "/repos/{repo}/labels",
                    {"name": name, "color": color, "description": description},
                )
            except GitHubError:
                pass
            self.gh.post(f"/repos/{{repo}}/issues/{number}/labels", {"labels": [name]})
            return {"label": name}

        return self._write("label", action)

    def remove_label(self, number: int, name: str) -> dict:
        def action() -> dict:
            self.gh.delete(f"/repos/{{repo}}/issues/{number}/labels/{name}")
            return {"removed": name}

        return self._write("label", action)
