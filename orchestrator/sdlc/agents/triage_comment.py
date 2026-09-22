"""The single comment the triage agent keeps on an issue.

The marker carries a content hash of the title and body, not a git SHA (issues have none): a
label or comment write doesn't change that hash, only an actual edit to the title or body does,
so the agent's own writes can never make it re-trigger itself on the next poll.
"""

import hashlib
import re
from dataclasses import dataclass

from sdlc.agents.triage import Assessment

MARKER = "<!-- pragmattie-triage -->"


def content_version(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Meta:
    decision_id: int | None
    version: str
    overrides: tuple[str, ...] = ()  # dimensions a human has already corrected, left alone


def render(assessment: Assessment, meta: Meta) -> str:
    lines = [MARKER, f"<!-- version:{meta.version} -->"]

    if not assessment.ok:
        lines += [
            "## Triage",
            "",
            f"**Could not triage this issue yet** ({assessment.status}). "
            "It will try again shortly.",
        ]
        return "\n".join(lines)

    lines += [f"## Triage: {assessment.module} / {assessment.type} ({assessment.priority})"]
    lines += [
        "",
        f"**Estimate {assessment.estimate_points} points**, "
        f"confidence {assessment.confidence:.0%}.",
    ]
    if assessment.rationale:
        lines += ["", assessment.rationale]

    if assessment.duplicate_of:
        lines += ["", f"Possibly a duplicate of #{assessment.duplicate_of} — linked, not closed."]

    if assessment.questions:
        lines += ["", "**Before this is ready to work on:**"]
        lines += [f"- {q}" for q in assessment.questions]

    if meta.overrides:
        dims = ", ".join(meta.overrides)
        lines += ["", f"_A human has already set {dims}; left as-is._"]

    if assessment.similar:
        lines += ["", "<details><summary>Similar past issues</summary>", ""]
        for s in assessment.similar[:5]:
            days = "?" if s.actual_days is None else f"{s.actual_days}d"
            lines.append(
                f"- #{s.number} [{s.state}] {s.module or '?'}/{s.type}, "
                f"{s.estimate_points}pt, {days} — {s.title}"
            )
        lines += ["", "</details>"]

    footer = [f"decision {meta.decision_id}" if meta.decision_id else "not recorded"]
    if assessment.llm:
        footer += [
            assessment.llm.model,
            f"{assessment.llm.input_tokens + assessment.llm.output_tokens} tokens",
        ]
    lines += ["", "<sub>" + " · ".join(footer) + " · PragMattie Sync demo</sub>"]
    return "\n".join(lines)


def comment_version(body: str) -> str | None:
    match = re.search(r"<!-- version:(\w+) -->", body)
    return match.group(1) if match else None
