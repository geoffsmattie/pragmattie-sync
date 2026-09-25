"""Create the PragMattie Sync backlog (orchestrator/backlog/backlog.yaml) as GitHub Issues.

Usage:
    python -m sdlc.backlog            # dry run: shows what would be created
    python -m sdlc.backlog --apply    # create missing labels and issues

Safe to re-run: labels that exist are left alone and issues are matched by exact title.
"""

import argparse
from pathlib import Path

import yaml

from sdlc.github_client import GitHubClient, GitHubError

BACKLOG = Path(__file__).resolve().parent.parent / "backlog" / "backlog.yaml"

LABEL_COLORS = {
    "module": "1B8A94",  # teal
    "type": "2E3F55",  # navy
    "priority": "E8B35A",  # gold
    "points": "C5CAD1",  # grey
    "epic": "6FBAC1",  # light teal
}
EXTRA_LABELS = {
    "caused-incident": ("B60205", "This PR caused a production incident"),
    "incident": ("D93F0B", "A production incident: the release gate holds releases touching it"),
    "demo": ("D4C5F9", "Made during a demo: the demo reset cleans it up"),
}


def load_backlog(path: Path = BACKLOG) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["issues"]


def labels_for(item: dict) -> list[str]:
    labels = [
        f"module:{item['module']}",
        f"type:{item['type']}",
        f"priority:{item['priority']}",
        f"points:{item['points']}",
    ]
    if item.get("epic"):
        labels.append(f"epic:{item['epic']}")
    return labels


def body_for(item: dict) -> str:
    lines = ["_Created from the PragMattie Sync demo backlog._", ""]
    if item.get("epic"):
        lines += [f"**Epic:** {item['epic']}", ""]
    if item.get("criteria"):
        lines += ["## Acceptance criteria", *[f"- [ ] {c}" for c in item["criteria"]]]
    return "\n".join(lines)


def plan(items: list[dict], existing_titles: set[str], existing_labels: set[str]) -> dict:
    wanted_labels = {label for item in items for label in labels_for(item)} | set(EXTRA_LABELS)
    return {
        "labels": sorted(wanted_labels - existing_labels),
        "issues": [item for item in items if item["title"] not in existing_titles],
    }


def apply(client: GitHubClient, todo: dict) -> None:
    for name in todo["labels"]:
        if name in EXTRA_LABELS:
            color, description = EXTRA_LABELS[name]
        else:
            color, description = LABEL_COLORS[name.split(":", 1)[0]], ""
        client.post(
            "/repos/{repo}/labels", {"name": name, "color": color, "description": description}
        )
    for item in todo["issues"]:
        issue = client.post(
            "/repos/{repo}/issues",
            {"title": item["title"], "body": body_for(item), "labels": labels_for(item)},
        )
        print(f"  #{issue['number']} {item['title']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the demo backlog as GitHub Issues.")
    parser.add_argument("--apply", action="store_true", help="actually create labels and issues")
    args = parser.parse_args()
    try:
        client = GitHubClient()
    except GitHubError as err:
        raise SystemExit(str(err)) from err

    items = load_backlog()
    titles = {i["title"] for i in client.paginate("/repos/{repo}/issues", state="all")}
    labels = {label["name"] for label in client.paginate("/repos/{repo}/labels")}
    todo = plan(items, titles, labels)
    print(
        f"{client.repo}: {len(todo['labels'])} labels and {len(todo['issues'])} issues to create."
    )
    if not args.apply:
        for item in todo["issues"]:
            print(f"  would create: {item['title']}  [{', '.join(labels_for(item))}]")
        print("Dry run only. Re-run with --apply to create them.")
        return
    apply(client, todo)
    print("Done.")


if __name__ == "__main__":
    main()
