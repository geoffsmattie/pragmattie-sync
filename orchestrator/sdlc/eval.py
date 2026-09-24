"""Grade the triage agent against Geoff's own labels (orchestrator/eval/triage_eval_set.json).

The acceptance bars were fixed before the first run (see the blueprint's Phase 4 criteria):
module 85%, type 90%, points within one step 70%. Priority is reported but not gated, since it
depends on context the agent can't see. It grades the agent's latest successful decision on each
issue, already in the audit table, so grading costs nothing and calls no API.

Disagreements are read, not just counted: the report groups them into patterns (for example,
forecasting work repeatedly labelled "platform"), because a pattern is a prompt or
module-description fix, never a reason to lower a bar.

Blind re-runs. The agent's prompt shows an issue's existing labels, and the 40 backlog issues were
created carrying Cowork's module/type/points labels, so the smoke-test decisions largely echo
Cowork (they matched it on 39/40 modules and 40/40 types). A fair grade needs `--fresh`: it re-runs
the agent on each issue's saved text (eval/_issues.json) with no labels shown and with similar
past issues drawn from the simulated history only (so no other eval issue, with its Cowork labels,
can appear as an example), records each call as a `trial` audit row (tokens counted, nothing
written to GitHub), and grades those answers.

Holdout set. The 40 backlog issues were used to tune the prompt (triage-v2), so they can no
longer judge a later prompt fairly. `--set holdout` grades against invented issues
(eval/holdout_issues.json) that Geoff labelled blind before any agent saw them
(eval/triage_holdout_set.json), with the same bars. Holdout issues exist nowhere else, so they are
always graded fresh; their trial rows are recorded as simulated (source `synthetic`, numbers from
9001) so the decision log never shows them as real GitHub issues.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.eval                  # grade the stored decisions
    python -m sdlc.eval --fresh          # what a blind re-run would send and cost; calls nothing
    python -m sdlc.eval --fresh --yes    # re-run blind (about 40 Haiku calls) and grade that
    python -m sdlc.eval --set holdout --fresh --yes   # grade blind on the holdout set
    python -m sdlc.eval --json           # any of the above, as JSON
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

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
EVAL_SET = EVAL_DIR / "triage_eval_set.json"
ISSUE_TEXT = EVAL_DIR / "_issues.json"  # each issue's title and body, as the agent saw them
HOLDOUT_SET = EVAL_DIR / "triage_holdout_set.json"
HOLDOUT_TEXT = EVAL_DIR / "holdout_issues.json"
SETS = {  # name -> (labels, issue text, audit source of its trial rows)
    "backlog": (EVAL_SET, ISSUE_TEXT, "github"),
    "holdout": (HOLDOUT_SET, HOLDOUT_TEXT, "synthetic"),
}
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


def grade(
    db: Session,
    labels: list[dict] | None = None,
    answers: dict | None = None,
    titles: dict[int, str] | None = None,
) -> dict:
    labels = labels if labels is not None else load_eval_set()
    answers = answers if answers is not None else agent_answers(db)
    if titles is None:
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


def run_blind(
    db: Session,
    llm,
    *,
    labels: list[dict],
    texts: dict[int, dict],
    subject_source: str = "github",
) -> dict[int, dict]:
    """Re-run the agent on each eval issue with no labels shown, recording trial rows."""
    from sdlc.agents.triage import AGENT_VERSION, PROMPT_VERSION, assess
    from sdlc.audit import TRIAL, record_decision

    answers: dict[int, dict] = {}
    for h in labels:
        text = texts[h["issue"]]
        a = assess(
            db,
            llm=llm,
            title=text["title"],
            body=text["body"],
            labels=[],
            number=None,
            candidate_source="synthetic",
        )
        decision = record_decision(
            db,
            agent=AGENT,
            agent_version=AGENT_VERSION,
            subject_type="issue",
            subject_source=subject_source,
            subject_id=h["issue"],
            trigger=TRIAL,
            model_id=llm.model,
            prompt_version=PROMPT_VERSION,
            output={
                "module": a.module,
                "type": a.type,
                "priority": a.priority,
                "estimate_points": a.estimate_points,
                "confidence": a.confidence,
                "eval": "blind",
            }
            if a.ok
            else None,
            action_taken={"trial": True, "eval": "blind"},
            status=a.status,
            error=a.error,
            latency_ms=a.llm.latency_ms if a.llm else None,
            input_tokens=a.llm.input_tokens if a.llm else None,
            output_tokens=a.llm.output_tokens if a.llm else None,
        )
        db.commit()
        if a.ok:
            answers[h["issue"]] = {
                "module": a.module,
                "type": a.type,
                "points": a.estimate_points,
                "priority": a.priority,
                "confidence": a.confidence,
                "prompt_version": PROMPT_VERSION,
                "decision_id": decision.id,
                "tokens": (a.llm.input_tokens, a.llm.output_tokens) if a.llm else (0, 0),
            }
    return answers


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
    parser.add_argument("--fresh", action="store_true", help="re-run the agent blind")
    parser.add_argument("--yes", action="store_true", help="really call the API (costs money)")
    parser.add_argument(
        "--set", choices=sorted(SETS), default="backlog", help="which labelled issues to grade"
    )
    args = parser.parse_args(argv)
    labels_path, text_path, source = SETS[args.set]
    if args.set == "holdout" and not args.fresh:
        parser.error("the holdout set has no stored decisions: grade it with --fresh")

    from sdlc.db import SessionLocal

    if not args.fresh:
        with SessionLocal() as db:
            report = grade(db)
        print(json.dumps(report, indent=2) if args.json else describe(report))
        return

    from sdlc.agents.llm import StructuredLLM
    from sdlc.agents.triage import SIMILAR_ISSUES_SHOWN, SYSTEM_PROMPT, build_prompt
    from sdlc.config import get_settings
    from sdlc.similarity import similar_issues

    settings = get_settings()
    llm = StructuredLLM(model=settings.triage_model, max_tokens=settings.triage_max_output_tokens)
    labels = load_eval_set(labels_path)
    texts = {i["n"]: i for i in json.loads(text_path.read_text(encoding="utf-8"))}
    with SessionLocal() as db:
        if not args.yes:
            chars = 0
            for h in labels:
                t = texts[h["issue"]]
                shown = similar_issues(
                    db, t["title"], t["body"], limit=SIMILAR_ISSUES_SHOWN, source="synthetic"
                )
                chars += len(SYSTEM_PROMPT) + len(build_prompt(t["title"], t["body"], [], shown))
            tokens_in = chars // 2  # errs high, as the agents' own dry runs do
            ceiling = tokens_in * 1.0 / 1e6 + len(labels) * llm.max_tokens * 5.0 / 1e6
            print(
                f"A blind re-run is {len(labels)} calls to {llm.model}: about {tokens_in:,} input "
                f"tokens in all, a ceiling of roughly ${ceiling:.2f} (Haiku 4.5 rates). "
                "Add --yes to run it."
            )
            return
        answers = run_blind(db, llm, labels=labels, texts=texts, subject_source=source)
        report = grade(db, labels, answers, titles={n: t["title"] for n, t in texts.items()})
    report["set"] = args.set
    spent_in = sum(a["tokens"][0] for a in answers.values())
    spent_out = sum(a["tokens"][1] for a in answers.values())
    report["blind_run"] = {
        "calls": len(labels),
        "input_tokens": spent_in,
        "output_tokens": spent_out,
        "cost_usd": round(spent_in * 1.0 / 1e6 + spent_out * 5.0 / 1e6, 4),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"BLIND RE-RUN on the {args.set} set: no labels shown; "
            "similar issues from simulated history only."
        )
        print(describe(report))
        b = report["blind_run"]
        cost = f"about ${b['cost_usd']}"
        print(f"\nCost: {b['input_tokens']:,} in / {b['output_tokens']:,} out, {cost}.")


if __name__ == "__main__":
    main()
