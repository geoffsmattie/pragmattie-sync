"""A small GitHub REST client shared by the signals collector and the backlog script.

The agents poll every 30 seconds, mostly re-reading things that haven't changed, and one hour's
API allowance is shared by every token of the same GitHub user. So reads are conditional: each
GET remembers its ETag, and GitHub's "304 Not Modified" answer doesn't count against the rate
limit. Once the limit is spent, the client refuses further requests itself until GitHub's reset
time, instead of sending requests that can only fail.
"""

from collections import OrderedDict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx

from sdlc.config import get_settings

CACHE_SIZE = 1000  # remembered GET responses, least recently used dropped first


class GitHubError(RuntimeError):
    pass


class RateLimited(GitHubError):
    """GitHub's API allowance is spent until `until` (naive UTC)."""

    def __init__(self, message: str, until: datetime):
        super().__init__(message)
        self.until = until


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
        self._cache: OrderedDict[str, tuple[str, httpx.Response]] = OrderedDict()
        self.limited_until: datetime | None = None
        self.sent = 0  # requests that reached GitHub
        self.not_modified = 0  # of those, answered 304 (free against the rate limit)

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code >= 400:
            message = response.json().get("message", "") if response.content else ""
            text = f"GitHub {response.status_code} on {response.url.path}: {message}"
            until = self._limit_reset(response)
            if until:
                self.limited_until = until
                raise RateLimited(f"{text} (paused until {until:%H:%M} UTC)", until)
            raise GitHubError(text)
        return response

    @staticmethod
    def _limit_reset(response: httpx.Response) -> datetime | None:
        """When a rate-limited response says the allowance comes back, else None."""
        if response.status_code not in (403, 429):
            return None
        headers = response.headers
        if headers.get("retry-after", "").isdigit():  # a secondary limit
            return _utcnow() + timedelta(seconds=int(headers["retry-after"]))
        if headers.get("x-ratelimit-remaining") == "0" and headers.get("x-ratelimit-reset"):
            reset = datetime.fromtimestamp(int(headers["x-ratelimit-reset"]), UTC)
            return reset.replace(tzinfo=None)
        return None

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        if self.limited_until and _utcnow() < self.limited_until:
            raise RateLimited(
                f"GitHub rate limit: paused until {self.limited_until:%H:%M} UTC",
                self.limited_until,
            )
        self.sent += 1
        return self._check(self.http.request(method, url, **kwargs))

    def _read(self, url: str, params: dict | None = None, accept: str | None = None):
        """A conditional GET: an unchanged resource comes from the cache, at no cost."""
        headers = {"Accept": accept} if accept else {}
        request = self.http.build_request("GET", url, params=params, headers=headers)
        key = f"{request.url} {accept or ''}"
        cached = self._cache.get(key)
        if cached:
            headers["If-None-Match"] = cached[0]
        response = self._send("GET", url, params=params, headers=headers)
        if response.status_code == 304 and cached:
            self.not_modified += 1
            self._cache.move_to_end(key)
            return cached[1]
        if etag := response.headers.get("etag"):
            self._cache[key] = (etag, response)
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return response

    def get(self, path: str, **params) -> dict | list:
        return self._read(self._path(path), params).json()

    def get_text(self, path: str, accept: str, **params) -> str:
        """A response that isn't JSON, such as a PR's diff (a diff, via `accept`)."""
        return self._read(self._path(path), params, accept).text

    def post(self, path: str, body: dict) -> dict:
        return self._send("POST", self._path(path), json=body).json()

    def patch(self, path: str, body: dict) -> dict:
        return self._send("PATCH", self._path(path), json=body).json()

    def put(self, path: str, body: dict) -> dict | list:
        return self._send("PUT", self._path(path), json=body).json()

    def delete(self, path: str) -> None:
        self._send("DELETE", self._path(path))

    def paginate(self, path: str, key: str | None = None, **params) -> Iterator[dict]:
        """Yield every item across pages (follows GitHub's Link: rel="next" header)."""
        url: str | None = self._path(path)
        query: dict | None = {"per_page": 100, **params}
        while url:
            response = self._read(url, query)
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
