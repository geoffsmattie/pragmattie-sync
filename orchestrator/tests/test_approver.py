from datetime import datetime

import pytest
from sqlalchemy import func, select

from sdlc import approver
from sdlc.tables import Approval, PullRequest

NOW = datetime(2026, 9, 19, 9, 0)


@pytest.fixture
def simulated():
    return approver.load_approvers()["simulated-second-human"]


def make_pr(db, number=101, source="synthetic", state="open", title="Rework billing sync"):
    pr = PullRequest(
        source=source,
        external_id=f"{source}-{number}",
        number=number,
        title=title,
        state=state,
        created_at=NOW,
    )
    db.add(pr)
    db.flush()
    return pr


def test_policy_declares_a_simulated_approver_for_t3_only(simulated):
    assert simulated["controlled_by"] == "geoff"
    assert simulated["applies_to_tiers"] == ["T3"]


def test_nothing_is_pending_until_a_request_is_recorded(db):
    make_pr(db)
    assert (
        approver.describe_pending(approver.pending(db), {}) == "No approvals are waiting for you."
    )


def test_request_then_pending_then_approve(db, simulated):
    pr = make_pr(db)
    approval = approver.request_approval(db, pr, simulated, "T3", "touches a migration", now=NOW)
    assert (approval.status, approval.source, approval.tier) == ("pending", "simulated", "T3")

    text = approver.describe_pending(approver.pending(db), {simulated["id"]: simulated})
    assert "1 approval waiting for you" in text
    assert "PR #101 [synthetic] T3" in text and "touches a migration" in text

    approver.approve(db, pr, simulated, note="checked by Geoff", now=NOW)
    assert approval.status == "approved" and approval.decided_at == NOW
    assert approver.pending(db) == []


def test_approving_needs_a_request_first_and_cannot_repeat(db, simulated):
    pr = make_pr(db)
    with pytest.raises(approver.ApproverError, match="no approval request"):
        approver.approve(db, pr, simulated)
    approver.request_approval(db, pr, simulated, "T3", now=NOW)
    approver.approve(db, pr, simulated, now=NOW)
    with pytest.raises(approver.ApproverError, match="already approved"):
        approver.approve(db, pr, simulated)


def test_request_is_rejected_for_other_tiers_closed_prs_and_repeats(db, simulated):
    with pytest.raises(approver.ApproverError, match="only covers tier T3"):
        approver.request_approval(db, make_pr(db, 1), simulated, "T2")
    with pytest.raises(approver.ApproverError, match="is merged"):
        approver.request_approval(db, make_pr(db, 2, state="merged"), simulated, "T3")
    pr = make_pr(db, 3)
    approver.request_approval(db, pr, simulated, "T3")
    with pytest.raises(approver.ApproverError, match="already has an approval request"):
        approver.request_approval(db, pr, simulated, "T3")


def test_requests_on_prs_that_are_no_longer_open_are_not_listed(db, simulated):
    pr = make_pr(db)
    approver.request_approval(db, pr, simulated, "T3", now=NOW)
    pr.state = "merged"
    db.flush()
    assert approver.pending(db) == []


def test_pending_lists_oldest_first(db, simulated):
    later = approver.request_approval(db, make_pr(db, 1), simulated, "T3", now=NOW)
    earlier = approver.request_approval(
        db, make_pr(db, 2), simulated, "T3", now=datetime(2026, 9, 18, 9, 0)
    )
    assert approver.pending(db) == [earlier, later]


def test_find_pull_request_needs_a_source_when_the_number_is_ambiguous(db):
    make_pr(db, 7, source="synthetic")
    make_pr(db, 7, source="github")
    with pytest.raises(approver.ApproverError, match="add --source"):
        approver.find_pull_request(db, 7)
    assert approver.find_pull_request(db, 7, "github").source == "github"
    with pytest.raises(approver.ApproverError, match="No pull request #99"):
        approver.find_pull_request(db, 99)


def test_cli_never_approves_on_its_own(db, capsys):
    make_pr(db, 55)
    db.commit()

    approver.main(["request", "55", "--reason", "schema change"])
    approver.main(["pending"])
    assert "PR #55" in capsys.readouterr().out

    def status():
        db.expire_all()
        return db.scalar(select(Approval.status))

    assert status() == "pending"  # requesting and listing never approve
    approver.main(["approve", "55", "--note", "ok"])
    assert status() == "approved"
    assert "SIMULATED" in capsys.readouterr().out
    assert db.scalar(select(func.count()).select_from(Approval)) == 1


def test_cli_reports_problems_without_a_traceback(db):
    with pytest.raises(SystemExit, match="No pull request #404"):
        approver.main(["approve", "404"])
