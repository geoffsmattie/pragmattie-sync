"""Find past issues similar to a new one: for the triage agent's duplicate detection and
estimate anchoring, and nothing else. Deterministic word-overlap in Python, computed once and
handed to the model — a nearest-neighbour lookup, not a judgment call, so it isn't the LLM's job.

No embeddings: the dataset is a few hundred issues, plain word overlap is cheap, exact and easy
to explain, and it's what the blueprint asks for ("nearest-neighbour lookup over past issue text").
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.tables import Issue

STOPWORDS = frozenset(
    "a an the to of for in on with and or but is are be as at by from into "
    "this that it its we our add adds fix fixes support supports allow allows".split()
)
WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SimilarIssue:
    number: int
    title: str
    module: str | None
    type: str
    estimate_points: int | None
    actual_days: float | None
    state: str
    score: float


def tokens(text: str) -> set[str]:
    words = WORD.findall(text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similar_issues(
    db: Session,
    title: str,
    body: str,
    *,
    exclude_number: int | None = None,
    limit: int = 10,
    source: str | None = None,
) -> list[SimilarIssue]:
    """The `limit` most similar past issues (any state), title weighted over body, best first.
    `source` limits them to one source (the blind evaluation uses only simulated history, so
    no other eval issue, with its labels, can be shown as an example)."""
    query_tokens = tokens(title) | tokens(body[:500])
    if not query_tokens:
        return []

    query = select(Issue).where(Issue.number.is_not(None))
    if exclude_number is not None:
        query = query.where(Issue.number != exclude_number)
    if source is not None:
        query = query.where(Issue.source == source)

    scored = []
    for issue in db.scalars(query):
        # sdlc_issues only stores a title, not a body, so past issues are matched on title alone.
        score = jaccard(query_tokens, tokens(issue.title))
        if score > 0:
            scored.append((score, issue))

    scored.sort(key=lambda pair: (-pair[0], pair[1].number or 0))
    return [
        SimilarIssue(
            number=issue.number,
            title=issue.title,
            module=issue.module,
            type=issue.type,
            estimate_points=issue.estimate_points,
            actual_days=issue.actual_days,
            state=issue.state,
            score=round(score, 3),
        )
        for score, issue in scored[:limit]
    ]
