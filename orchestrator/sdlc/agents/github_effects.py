"""Everything the agents do to GitHub, in one place, so the mode switch can stop all of it.

Reads (a PR's details, its diff, the current comment) always work. Every write goes through
`_write`, which does nothing when ORCHESTRATOR_MODE is `off` and reports what happened either way,
so the audit row records the effects. One failing write never stops the others.

Writes the agents can make, and nothing else: one comment per PR (kept up to date), one `tier:Tn`
label, and the `risk-gate` commit status. They never merge, approve, close, push or edit
branch protection.
"""

from collections.abc import Callable

from sdlc.agents.comment import MARKER
from sdlc.github_client import GitHubClient, GitHubError

STATUS_CONTEXT = "risk-gate"
TIER_LABELS = {"T0": "0E8A16", "T1": "FBCA04", "T2": "F9A03F", "T3": "B60205"}
TIER_LABEL_DESCRIPTION = "Governance tier set by the PR risk agent"


class Effects:
    def __init__(self, gh: GitHubClient, mode: str):
        self.gh = gh
        self.mode = mode

    # --- reads: always allowed ---------------------------------------------------------------

    def read_pr(self, number: int) -> dict:
        return self.gh.get(f"/repos/{{repo}}/pulls/{number}")

    def read_diff(self, number: int) -> str:
        return self.gh.get_text(f"/repos/{{repo}}/pulls/{number}", "application/vnd.github.diff")

    def find_comment(self, number: int) -> dict | None:
        """The risk agent's own comment on this PR, if it has posted one."""
        for comment in self.gh.paginate(f"/repos/{{repo}}/issues/{number}/comments"):
            if MARKER in (comment.get("body") or ""):
                return comment
        return None

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

    def set_status(self, sha: str, state: str, description: str) -> dict:
        def action() -> dict:
            self.gh.post(
                f"/repos/{{repo}}/statuses/{sha}",
                {"state": state, "context": STATUS_CONTEXT, "description": description[:140]},
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
