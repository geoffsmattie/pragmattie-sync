"""Small, deliberate writes to the agentic repo's issues, for writing specs and tidying the plan.

Uses GITHUB_TOKEN_AGENTIC from the repo's .env and never prints it. Only issues: never code,
branches, pull requests or settings.

    python scripts/ghwrite.py body N FILE          # replace issue N's body with FILE's text
    python scripts/ghwrite.py title N TEXT...      # rename issue N
    python scripts/ghwrite.py comment N FILE       # add a comment from FILE
    python scripts/ghwrite.py close N [not_planned] # close issue N (completed by default)
    python scripts/ghwrite.py label N +NAME -NAME  # add (+) or remove (-) labels
    python scripts/ghwrite.py bodies DIR NAME=N ... # replace several bodies: DIR/NAME.md -> #N
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghread import REPOS, env  # noqa: E402

TOKEN_NAME, REPO = REPOS["agentic"]


def call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {env(TOKEN_NAME)}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as r:
        text = r.read()
        return json.loads(text) if text else None


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    if argv[0] == "bodies":
        for pair in argv[2:]:
            name, number = pair.split("=")
            main(["body", number, str(Path(argv[1]) / f"{name}.md")])
        return
    cmd, number, rest = argv[0], int(argv[1]), argv[2:]
    if cmd == "body":
        call("PATCH", f"/issues/{number}", {"body": Path(rest[0]).read_text(encoding="utf-8")})
        print(f"#{number}: body replaced")
    elif cmd == "title":
        call("PATCH", f"/issues/{number}", {"title": " ".join(rest)})
        print(f"#{number}: title set")
    elif cmd == "comment":
        c = call("POST", f"/issues/{number}/comments", {"body": Path(rest[0]).read_text("utf-8")})
        print(f"#{number}: commented {c['html_url']}")
    elif cmd == "close":
        reason = rest[0] if rest else "completed"
        call("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": reason})
        print(f"#{number}: closed ({reason})")
    elif cmd == "label":
        for item in rest:
            name = item[1:]
            if item.startswith("+"):
                call("POST", f"/issues/{number}/labels", {"labels": [name]})
            elif item.startswith("-"):
                try:
                    call("DELETE", f"/issues/{number}/labels/{urllib.parse.quote(name)}")
                except urllib.error.HTTPError as err:
                    if err.code != 404:
                        raise
        print(f"#{number}: labels {' '.join(rest)}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
