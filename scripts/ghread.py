"""Read-only GitHub lookups for the two repositories, so they can run without a prompt each time.

Only ever sends GET requests. Uses GITHUB_TOKEN (v1) or GITHUB_TOKEN_AGENTIC (the rebuild) from
the repo's .env and never prints them.

    python scripts/ghread.py [--v1] runs [N]              # recent workflow runs
    python scripts/ghread.py [--v1] jobs RUN_ID           # a run's jobs and steps
    python scripts/ghread.py [--v1] log JOB_ID [TEXT]     # a job's log (lines containing TEXT)
    python scripts/ghread.py [--v1] issue N               # an issue: labels, state, body
    python scripts/ghread.py [--v1] comments N [LAST]     # an issue's comments (the last LAST)
    python scripts/ghread.py [--v1] issues [STATE]        # issues: number, state, title, labels
    python scripts/ghread.py [--v1] pulls [STATE]         # pull requests
    python scripts/ghread.py [--v1] commits PR            # a PR's commits: author, committer, message
    python scripts/ghread.py [--v1] files PR [--patch]    # a PR's changed files (and their diffs)
    python scripts/ghread.py [--v1] wait [MINUTES]        # wait for the newest run to finish (default 15)
    python scripts/ghread.py ratelimit                   # API calls left this hour (both tokens share it)
Without --v1 it reads pragmattie/pragmattie-sync-agentic (the rebuild).
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"
REPOS = {"v1": ("GITHUB_TOKEN", None), "agentic": ("GITHUB_TOKEN_AGENTIC", "pragmattie/pragmattie-sync-agentic")}


def env(name: str) -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{name} is not set in .env")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(repo: str, token: str, path: str, raw: bool = False):
    url = f"https://api.github.com/repos/{repo}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    if not raw:
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as err:
            reason = err.read().decode("utf-8", "replace")[:300]
            left = err.headers.get("X-RateLimit-Remaining")
            raise SystemExit(f"GitHub {err.code} on {path}: {reason} (rate limit left: {left})")
    try:  # logs redirect to storage that must not receive the GitHub token
        urllib.request.build_opener(_NoRedirect).open(req)
    except urllib.error.HTTPError as err:
        if err.code in (301, 302, 307):
            with urllib.request.urlopen(err.headers["Location"]) as r:
                return r.read().decode("utf-8", "replace")
        raise
    raise SystemExit("expected a redirect to the log")


def main(argv: list[str]) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    which = "v1" if argv and argv[0] == "--v1" else "agentic"
    args = argv[1:] if which == "v1" else argv
    if not args:
        raise SystemExit(__doc__)
    token_name, repo = REPOS[which]
    repo = repo or env("GITHUB_REPO")
    token = env(token_name)
    cmd, rest = args[0], args[1:]
    if cmd == "ratelimit":
        req = urllib.request.Request(
            "https://api.github.com/rate_limit", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req) as r:
            core = json.loads(r.read())["resources"]["core"]
        print(f"{core['remaining']} of {core['limit']} left, used {core['used']}, resets {core['reset']}")
        return
    if cmd == "runs":
        for r in get(repo, token, f"/actions/runs?per_page={rest[0] if rest else 10}")["workflow_runs"]:
            print(r["id"], r["name"], r["event"], r["status"], r["conclusion"], r["head_branch"], r["created_at"])
    elif cmd == "wait":
        deadline = time.time() + 60 * float(rest[0] if rest else 15)
        while True:
            r = get(repo, token, "/actions/runs?per_page=1")["workflow_runs"][0]
            if r["status"] == "completed" or time.time() > deadline:
                break
            time.sleep(20)
        print(r["id"], r["name"], r["event"], r["status"], r["conclusion"], r["head_branch"], r["created_at"])
    elif cmd == "jobs":
        for j in get(repo, token, f"/actions/runs/{rest[0]}/jobs")["jobs"]:
            print("job", j["id"], j["name"], j["conclusion"])
            for s in j["steps"]:
                print("   ", s["number"], s["name"], s["conclusion"])
    elif cmd == "log":
        text = rest[1] if len(rest) > 1 else None
        for line in get(repo, token, f"/actions/jobs/{rest[0]}/logs", raw=True).splitlines():
            line = re.sub(r"^\S+Z ", "", line)
            if text is None or text.lower() in line.lower():
                print(line[:400])
    elif cmd == "issue":
        i = get(repo, token, f"/issues/{rest[0]}")
        print(f"#{i['number']} [{i['state']}] {i['title']}")
        print("labels:", ", ".join(label["name"] for label in i["labels"]))
        print(i.get("body") or "")
    elif cmd == "comments":
        comments = get(repo, token, f"/issues/{rest[0]}/comments?per_page=100")
        for c in comments[-int(rest[1]):] if len(rest) > 1 else comments:
            print(f"--- {c['user']['login']} {c['created_at']}\n{c['body']}")
    elif cmd == "pull":
        p = get(repo, token, f"/pulls/{rest[0]}")
        print(f"#{p['number']} [{p['state']}] merged={p['merged']} mergeable={p['mergeable']} "
              f"state={p['mergeable_state']} merged_at={p['merged_at']} head={p['head']['ref']} {p['title']}")
    elif cmd == "rules":
        for rule in get(repo, token, f"/rules/branches/{rest[0] if rest else 'main'}"):
            params = rule.get("parameters") or {}
            checks = [c["context"] for c in params.get("required_status_checks", [])]
            print(rule["type"], checks or {k: v for k, v in params.items() if not isinstance(v, list)})
    elif cmd == "commits":
        for c in get(repo, token, f"/pulls/{rest[0]}/commits?per_page=100"):
            author = (c.get("author") or {}).get("login") or c["commit"]["author"]["name"]
            committer = (c.get("committer") or {}).get("login") or c["commit"]["committer"]["name"]
            print(c["sha"][:8], f"author={author} committer={committer}", c["commit"]["message"].splitlines()[0])
    elif cmd == "files":
        for f in get(repo, token, f"/pulls/{rest[0]}/files?per_page=100"):
            print(f"{f['status']:<9} +{f['additions']:<4} -{f['deletions']:<4} {f['filename']}")
            if "--patch" in rest:
                print(f.get("patch") or "(no diff shown)")
    elif cmd in ("issues", "pulls"):
        state = rest[0] if rest else "open"
        for i in get(repo, token, f"/{cmd}?state={state}&per_page=100"):
            if cmd == "issues" and "pull_request" in i:
                continue
            labels = ", ".join(label["name"] for label in i.get("labels", []))
            print(f"#{i['number']} [{i['state']}] {i['title'][:70]}  ({labels})")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
