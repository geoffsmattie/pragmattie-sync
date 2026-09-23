"""Grade the triage agent against Geoff's own labels (orchestrator/eval/triage_eval_set.json).

The acceptance bars were fixed before the first run (see the blueprint's Phase 4 criteria):
module 85%, type 90%, points within one step 70%. Priority is reported but not gated, since it
depends on context the agent can't see. It grades the agent's latest successful decision on each
issue, already in the audit table, so grading costs nothing and calls no API.

Disagreements are read, not just counted: the report groups them into patterns (for example,
forecasting work repeatedly labelled "platform"), because a pattern is a prompt or
module-description fix, never a reason to lower a bar.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.eval              # the report
    python -m sdlc.eval --json       # the same, as JSON
"""

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.agents.triage import AGENT, POINTS
from sdlc.tables import AgentDecision, Issue

EVAL_SET = Path(__file__).resolve().parents[1] / "eval" / "triage_eval_set.json"
BARS = {"module": 0.85, "type": 0.90, "points_within_one": 0.70}


@dataclass(frozen=True)
class Row:
    issue: int
    title: str
    human: dict
    agent: dict | None  # None: the agent has no successful decision on this issue

    def agrees(self, dimension: str) -> bool:
        if self.agent is None:
            return False
        if dimension == "points_within_one":
            return points_step(self.human["points"], self.agent["points"]) <= 1
        if dimension == "points":
            return self.human["points"] == self.agent["points"]
        return self.human[dimension] == self.agent[dimension]


def points_step(a: int, b: int) -> int:
    """How many steps apart two estimates are on the 1-2-3-5-8 scale (off-scale counts as far)."""
    if a not in POINTS or b not in POINTS:
        return len(POINTS)
    return abs(POINTS.index(a) - POINTS.index(b))


def load_eval_set(path: Path = EVAL_SET) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["issues"]


def agent_answers(db: Session) -> dict[int, dict]:
    """The agent's latest successful classification per real issue (manual trials excluded)."""
    answers: dict[int, dict] = {}
    rows = db.scalars(
        select(AgentDecision)
        .where(
            AgentDecision.agent == AGENT,
            AgentDecision.subject_type == "issue",
            AgentDecision.subject_source == "github",
            AgentDecision.status == "ok",
            AgentDecision.trigger != "trial",
        )
        .order_by(AgentDecision.created_at, AgentDecision.id)
    )
    for d in rows:
        out = d.output or {}
        answers[d.subject_id] = {
            "module": out.get("module"),
            "type": out.get("type"),
            "points": out.get("estimate_points"),
            "priority": out.get("priority"),
            "confidence": out.get("confidence"),
            "prompt_version": d.prompt_version,
            "decision_id": d.id,
        }
    return answers


def grade(db: Session, labels: list[dict] | None = None) -> dict:
    labels = labels if labels is not None else load_eval_set()
    answers = agent_answers(db)
    titles = dict(
        db.execute(select(Issue.number, Issue.title).where(Issue.source == "github")).all()
    )
    rows = [
        Row(
            issue=h["issue"],
            title=titles.get(h["issue"], ""),
            human=h,
            agent=answers.get(h["issue"]),
        )
        for h in labels
    ]
    total = len(rows)

    def rate(dimension: str) -> float:
        return sum(r.agrees(dimension) for r in rows) / total if total else 0.0

    scores = {
        "module": rate("module"),
        "type": rate("type"),
        "points_within_one": rate("points_within_one"),
        "points_exact": rate("points"),
        "priority": rate("priority"),  # reported, not gated
    }
    graded = [r for r in rows if r.agent]
    patterns = {
        "module": Counter(
            (r.human["module"], r.agent["module"]) for r in graded if not r.agrees("module")
        ).most_common(),
        "type": Counter(
            (r.human["type"], r.agent["type"]) for r in graded if not r.agrees("type")
        ).most_common(),
    }
    higher = sum(1 for r in graded if r.agent["points"] and r.agent["points"] > r.human["points"])
    lower = sum(1 for r in graded if r.agent["points"] and r.agent["points"] < r.human["points"])
    return {
        "issues": total,
        "graded": len(graded),
        "missing": [r.issue for r in rows if r.agent is None],
        "scores": scores,
        "bars": BARS,
        "passed": {k: scores[k] >= bar for k, bar in BARS.items()},
        "patterns": {
            "module": [{"human": h, "agent": a, "count": n} for (h, a), n in patterns["module"]],
            "type": [{"human": h, "agent": a, "count": n} for (h, a), n in patterns["type"]],
            "points": {
                "agent_higher": higher,
                "agent_lower": lower,
                "same": len(graded) - higher - lower,
            },
        },
        "prompt_versions": sorted(
            {r.agent["prompt_version"] for r in graded if r.agent["prompt_version"]}
        ),
        "disagreements": [
            {
                "issue": r.issue,
                "title": r.title,
                "human": {k: r.human[k] for k in ("module", "type", "points", "priority")},
                "agent": {k: r.agent[k] for k in ("module", "type", "points", "priority")}
                if r.agent
                else None,
                "misses": [d for d in ("module", "type", "points_within_one") if not r.agrees(d)],
                "note": r.human.get("note"),
                "decision_id": r.agent["decision_id"] if r.agent else None,
            }
            for r in rows
            if not all(r.agrees(d) for d in ("module", "type", "points_within_one"))
        ],
    }


def describe(report: dict) -> str:
    s, bars, passed = report["scores"], report["bars"], report["passed"]

    def line(key: str, label: str) -> str:
        mark = "PASS" if passed[key] else "FAIL"
        return f"  {label:<24} {s[key]:>5.0%}  (bar {bars[key]:.0%})  {mark}"

    out = [
        f"Triage agent vs Geoff's labels: {report['graded']} of {report['issues']} issues graded"
        + (f"; no decision for {report['missing']}" if report["missing"] else "")
        + f" (prompt {', '.join(report['prompt_versions']) or 'unknown'}).",
        line("module", "Module"),
        line("type", "Type"),
        line("points_within_one", "Points within one step"),
        f"  {'Points exact':<24} {s['points_exact']:>5.0%}  (reported)",
        f"  {'Priority':<24} {s['priority']:>5.0%}  (reported, not gated)",
        "",
        "Patterns (human -> agent):",
    ]
    for kind in ("module", "type"):
        for p in report["patterns"][kind]:
            out.append(f"  {kind}: {p['human']} -> {p['agent']} x{p['count']}")
    pts = report["patterns"]["points"]
    out.append(
        f"  points: agent higher on {pts['agent_higher']}, lower on {pts['agent_lower']}, "
        f"same on {pts['same']}"
    )
    out += ["", f"Disagreements ({len(report['disagreements'])}):"]
    for d in report["disagreements"]:
        a = d["agent"] or {}
        h = d["human"]
        diffs = []
        for dim, key in (("module", "module"), ("type", "type"), ("points_within_one", "points")):
            if dim in d["misses"]:
                diffs.append(f"{key} {h[key]} vs {a.get(key)}")
        note = f"  [note: {d['note']}]" if d["note"] else ""
        out.append(f"  #{d['issue']} {d['title'][:55]}: {'; '.join(diffs)}{note}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Grade the triage agent against the eval set.")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    from sdlc.db import SessionLocal

    with SessionLocal() as db:
        report = grade(db)
    print(json.dumps(report, indent=2) if args.json else describe(report))


if __name__ == "__main__":
    main()
