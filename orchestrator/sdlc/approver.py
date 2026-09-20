"""Simulated approver: stands in for the second human that governance tier T3 needs.

Geoff is the only human on this repo, so T3 ("2 humans incl. code owner") would lock the
process. The simulated approver (orchestrator/policies/approvers.yaml) fills the second seat.
It is MANUAL ONLY: it never approves anything until Geoff runs `approve` for that pull request.
Every approval is stored with source="simulated" so it is never mistaken for a human one.

Usage:
    python -m sdlc.approver pending                  # what is waiting for me?
    python -m sdlc.approver request 212 --tier T3    # record that PR #212 needs the approval
    python -m sdlc.approver approve 212              # give the simulated approval

`request` is what the Phase 4 PR risk agent will call when it assigns tier T3; until then you
run it by hand. Pass --source when a PR number exists in both synthetic and github data.
"""

import argparse
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.db import SessionLocal
from sdlc.tables import SOURCES, Approval, PullRequest

POLICY = Path(__file__).resolve().parent.parent / "policies" / "approvers.yaml"


class ApproverError(Exception):
    """A problem worth telling the user about, without a traceback."""


def load_approvers(path: Path = POLICY) -> dict[str, dict]:
    approvers = {a["id"]: a for a in yaml.safe_load(path.read_text(encoding="utf-8"))["approvers"]}
    if not approvers:
        raise ApproverError(f"No approvers are configured in {path}.")
    return approvers


def resolve_approver(approvers: dict[str, dict], approver_id: str | None) -> dict:
    if approver_id is None:
        if len(approvers) > 1:
            raise ApproverError(
                f"Several approvers exist; pick one with --approver: {list(approvers)}"
            )
        return next(iter(approvers.values()))
    if approver_id not in approvers:
        raise ApproverError(f"Unknown approver '{approver_id}'. Known: {list(approvers)}")
    return approvers[approver_id]


def find_pull_request(db: Session, number: int, source: str | None = None) -> PullRequest:
    query = select(PullRequest).where(PullRequest.number == number)
    if source:
        query = query.where(PullRequest.source == source)
    matches = db.scalars(query).all()
    if not matches:
        raise ApproverError(
            f"No pull request #{number}" + (f" in source '{source}'." if source else ".")
        )
    if len(matches) > 1:
        sources = ", ".join(sorted(pr.source for pr in matches))
        raise ApproverError(f"PR #{number} exists in several sources ({sources}); add --source.")
    return matches[0]


def _existing(db: Session, pr: PullRequest, approver_id: str) -> Approval | None:
    return db.scalar(
        select(Approval).where(
            Approval.pull_request_id == pr.id, Approval.approver_id == approver_id
        )
    )


def request_approval(
    db: Session,
    pr: PullRequest,
    approver: dict,
    tier: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> Approval:
    """Record that `pr` needs `approver`'s approval (status: pending)."""
    if tier not in approver["applies_to_tiers"]:
        covered = ", ".join(approver["applies_to_tiers"])
        raise ApproverError(f"{approver['name']} only covers tier {covered}, not {tier}.")
    if pr.state != "open":
        raise ApproverError(f"PR #{pr.number} is {pr.state}; only open PRs need an approval.")
    if (existing := _existing(db, pr, approver["id"])) is not None:
        raise ApproverError(f"PR #{pr.number} already has an approval request ({existing.status}).")
    approval = Approval(
        pull_request_id=pr.id,
        approver_id=approver["id"],
        tier=tier,
        status="pending",
        reason=reason,
        requested_at=now or datetime.now().replace(microsecond=0),
    )
    db.add(approval)
    db.flush()
    return approval


def approve(
    db: Session,
    pr: PullRequest,
    approver: dict,
    note: str | None = None,
    now: datetime | None = None,
) -> Approval:
    """Give the simulated approval. Only ever called on Geoff's explicit instruction."""
    approval = _existing(db, pr, approver["id"])
    if approval is None:
        raise ApproverError(
            f"PR #{pr.number} has no approval request. Run `request {pr.number}` first."
        )
    if approval.status == "approved":
        raise ApproverError(
            f"PR #{pr.number} was already approved on {approval.decided_at:%Y-%m-%d}."
        )
    approval.status = "approved"
    approval.note = note
    approval.decided_at = now or datetime.now().replace(microsecond=0)
    db.flush()
    return approval


def pending(db: Session) -> list[Approval]:
    """Approvals still waiting, oldest first. Requests on merged or closed PRs are ignored."""
    query = (
        select(Approval)
        .join(PullRequest)
        .where(Approval.status == "pending", PullRequest.state == "open")
        .order_by(Approval.requested_at, Approval.id)
    )
    return list(db.scalars(query))


def describe_pending(items: list[Approval], approvers: dict[str, dict]) -> str:
    if not items:
        return "No approvals are waiting for you."
    noun = "approval" if len(items) == 1 else "approvals"
    lines = [f"{len(items)} {noun} waiting for you (simulated, so not real human approvals):"]
    for item in items:
        pr = item.pull_request
        name = approvers.get(item.approver_id, {}).get("name", item.approver_id)
        line = f"  PR #{pr.number} [{pr.source}] {item.tier} - {pr.title[:70]} ({name}"
        line += f", requested {item.requested_at:%Y-%m-%d})"
        if item.reason:
            line += f" - {item.reason}"
        lines.append(line)
    lines.append("Approve one with: python -m sdlc.approver approve <pr> [--source ...]")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the simulated second approver.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("pending", help="list approvals waiting for you")

    for name, help_text in (
        ("request", "record that a PR needs the simulated approval"),
        ("approve", "give the simulated approval to a PR"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("number", type=int, help="pull request number")
        command.add_argument("--source", choices=SOURCES, help="needed if the number is ambiguous")
        command.add_argument("--approver", help="approver id (default: the only one configured)")
        if name == "request":
            command.add_argument("--tier", default="T3", help="tier that needs it (default T3)")
            command.add_argument("--reason", help="why this PR needs it")
        else:
            command.add_argument("--note", help="optional note stored with the approval")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        approvers = load_approvers()
        with SessionLocal() as db:
            if args.command == "pending":
                print(describe_pending(pending(db), approvers))
                return
            approver = resolve_approver(approvers, args.approver)
            pr = find_pull_request(db, args.number, args.source)
            label = f"PR #{pr.number} [{pr.source}]"
            if args.command == "request":
                request_approval(db, pr, approver, args.tier, args.reason)
                print(f"Recorded: {label} needs {approver['name']} ({args.tier}).")
            else:
                approve(db, pr, approver, args.note)
                print(f"Approved (SIMULATED) by {approver['name']}: {label}.")
            db.commit()
    except ApproverError as err:
        raise SystemExit(str(err)) from err


if __name__ == "__main__":
    main()
