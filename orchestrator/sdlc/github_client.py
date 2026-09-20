"""A small GitHub REST client shared by the signals collector and the backlog script."""

from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from sdlc.config import get_settings


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        repo: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        settings = get_settings()
        self.token = token if token is not None else settings.github_token
        self.repo = repo if repo is not None else settings.github_repo
        if not self.token or not self.repo:
            raise GitHubError(
                "Set GITHUB_TOKEN and GITHUB_REPO (owner/name) in your .env file first."
            )
        self.http = httpx.Client(
            base_url=base_url or settings.github_api_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
            transport=transport,
        )

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code >= 400:
            message = response.json().get("message", "") if response.content else ""
            raise GitHubError(f"GitHub {response.status_code} on {response.url.path}: {message}")
        return response

    def get(self, path: str, **params) -> dict | list:
        return self._check(self.http.get(self._path(path), params=params)).json()

    def post(self, path: str, body: dict) -> dict:
        return self._check(self.http.post(self._path(path), json=body)).json()

    def paginate(self, path: str, key: str | None = None, **params) -> Iterator[dict]:
        """Yield every item across pages (follows GitHub's Link: rel="next" header)."""
        url: str | None = self._path(path)
        query: dict | None = {"per_page": 100, **params}
        while url:
            response = self._check(self.http.get(url, params=query))
            body = response.json()
            yield from (body[key] if key else body)
            url = response.links.get("next", {}).get("url")
            query = None  # the next URL already carries its query string; don't replace it

    def _path(self, path: str) -> str:
        return path.replace("{repo}", self.repo)


def parse_time(value: str | None) -> datetime | None:
    """GitHub timestamps ("2026-09-18T14:03:00Z") as naive UTC datetimes."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)
