from datetime import datetime, timedelta

from sdlc.agents.gate import Gate
from sdlc.agents.pr_risk import AGENT as PR_RISK_AGENT
from sdlc.agents.triage import AGENT as TRIAGE_AGENT
from sdlc.audit import record_decision
from sdlc.board import build_board
from sdlc.gate_status import upsert as upsert_gate
from sdlc.tables import Deployment, Engineer, Issue, PullRequest, Sprint

NOW = datetime(2026, 9, 23, 12, 0)
_n = [100]


def _next_id():
    _n[0] += 1
    return _n[0]


def make_issue(
    db, *, source="github", state="open", module=None, points=None, sprint_id=None, **kw
):
    number = _next_id()
    issue = Issue(
        source=source,
        external_id=f"issue-{number}",
        number=number,
        title=kw.pop("title", f"Issue {number}"),
        module=module,
        estimate_points=points,
        state=state,
        sprint_id=sprint_id,
        created_at=kw.pop("created_at", NOW - timedelta(days=1)),
        **kw,
    )
    db.add(issue)
    db.flush()
    return issue


def make_pr(db, *, issue=None, source="github", state="open", merged_at=None, module="leads", **kw):
    number = _next_id()
    pr = PullRequest(
        source=source,
        external_id=f"pr-{number}",
        number=number,
        title=kw.pop("title", f"PR {number}"),
        module=module,
        issue_id=issue.id if issue else None,
        state=state,
        merged_at=merged_at,
        created_at=kw.pop("created_at", NOW - timedelta(hours=12)),
        **kw,
    )
    db.add(pr)
    db.flush()
    return pr


def score_pr(db, pr, *, tier="T1", score=30, status="ok", now=None):
    return record_decision(
        db,
        agent=PR_RISK_AGENT,
        agent_version="v1",
        subject_type="pr",
        subject_source=pr.source,
        subject_id=pr.number,
        trigger="poll",
        now=now or NOW,
        head_sha="sha1",
        tier=tier,
        final_score=score,
        status=status,
    )


def triage_issue(db, issue, *, now=None):
    return record_decision(
        db,
        agent=TRIAGE_AGENT,
        agent_version="v1",
        subject_type="issue",
        subject_source=issue.source,
        subject_id=issue.number,
        trigger="opened",
        now=now or NOW,
        head_sha="v1",
        output={"module": issue.module},
        status="ok",
    )


def gate_for(
    db, pr, *, state="pending", missing=("human sign-off",), tier="T1", mode="enforce", now=None
):
    gate = Gate(state, "pending" if state != "success" else "success", missing, "waiting")
    return upsert_gate(db, pr, gate, tier=tier, mode=mode, now=now or NOW)


def make_deployment(db, *, source="synthetic", deployed_at, status="success", pr_count=1):
    d = Deployment(
        source=source, version="v1", deployed_at=deployed_at, pr_count=pr_count, status=status
    )
    db.add(d)
    db.flush()
    return d


def by_key(board, key):
    return next(c for c in board.cards if c.key == key)


# --- one column per state --------------------------------------------------------------------


def test_backlog_open_issue_no_progress(db):
    issue = make_issue(db)
    db.commit()
    board = build_board(db, now=NOW)
    card = by_key(board, f"issue-{issue.number}")
    assert card.column == "backlog"
    assert card.entered_column_at == issue.created_at


def test_triaged_real_issue_needs_a_real_triage_decision(db):
    issue = make_issue(db, module="leads", points=3)
    decision = triage_issue(db, issue)
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "triaged"
    assert card.entered_column_at == decision.created_at


def test_synthetic_issue_is_triaged_from_birth_no_decision_needed(db):
    issue = make_issue(db, source="synthetic", module="leads", points=5)
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "triaged"
    assert card.entered_column_at == issue.created_at  # no triage decision exists for synthetic


def test_in_progress_real_card_needs_no_sprint(db):
    issue = make_issue(db, module="leads", points=3)
    pr = make_pr(db, issue=issue)  # no sprint assigned to the issue at all
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "in_progress"
    assert card.pr_number == pr.number


def test_synthetic_in_progress_requires_the_current_sprint(db):
    sprint = Sprint(
        name="Sprint 1",
        start_date=NOW.date() - timedelta(days=3),
        end_date=NOW.date() + timedelta(days=3),
        source="synthetic",
    )
    db.add(sprint)
    db.flush()
    issue = make_issue(db, source="synthetic", module="leads", points=3, sprint_id=sprint.id)
    make_pr(db, issue=issue, source="synthetic", created_at=NOW - timedelta(days=1))
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "in_progress"
    assert card.sprint == "Sprint 1"


def test_synthetic_pr_outside_the_current_sprint_does_not_get_in_progress(db):
    sprint = Sprint(
        name="Sprint 1",
        start_date=NOW.date() - timedelta(days=3),
        end_date=NOW.date() + timedelta(days=3),
        source="synthetic",
    )
    db.add(sprint)
    db.flush()
    issue = make_issue(db, source="synthetic", module="leads", points=3)
    make_pr(db, issue=issue, source="synthetic", created_at=NOW - timedelta(days=30))
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "triaged"  # the PR contributed nothing: stays at the issue's own state


def test_in_review_needs_a_successful_score_and_a_clean_gate(db):
    issue = make_issue(db, module="leads", points=3)
    pr = make_pr(db, issue=issue)
    decision = score_pr(db, pr, tier="T1", score=25)
    gate_for(db, pr, state="success", missing=())
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "in_review"
    assert (card.tier, card.risk_score) == ("T1", 25)
    assert card.entered_column_at == decision.created_at


def test_gated_when_the_gate_is_pending_and_names_whats_missing(db):
    issue = make_issue(db, module="billing_auth", points=8)
    pr = make_pr(db, issue=issue, module="billing_auth")
    score_pr(db, pr, tier="T3", score=90)
    gate_for(db, pr, state="pending", missing=("human sign-off", "manual QA"))
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "gated"
    assert card.gate_missing == ("human sign-off", "manual QA")
    assert card.tier == "T3"


def test_gated_on_agent_failure_still_shows_the_fallback_tier(db):
    issue = make_issue(db, module="billing_auth", points=8)
    pr = make_pr(db, issue=issue, module="billing_auth")
    # No successful risk decision at all: the agent failed and fell back closed.
    gate_for(db, pr, state="failure", missing=("a successful risk assessment",), tier="T3")
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "gated"
    assert card.tier == "T3"  # from the gate's fallback tier, not a (nonexistent) risk decision
    assert card.risk_score is None


def test_merged_with_no_deployment_yet(db):
    issue = make_issue(db, module="leads", points=3)
    pr = make_pr(db, issue=issue, state="merged", merged_at=NOW - timedelta(hours=2))
    score_pr(db, pr, tier="T1", score=20)
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "merged"
    assert card.entered_column_at == pr.merged_at


def test_production_when_a_later_deployment_picks_it_up(db):
    issue = make_issue(db, source="synthetic", module="leads", points=3)
    make_pr(db, issue=issue, source="synthetic", state="merged", merged_at=NOW - timedelta(days=2))
    make_deployment(db, deployed_at=NOW - timedelta(days=3))  # before the merge: not this one
    shipped = make_deployment(db, deployed_at=NOW - timedelta(days=1))  # first one at/after merge
    make_deployment(db, deployed_at=NOW)  # later still: also not this one
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "production"
    assert card.entered_column_at == shipped.deployed_at
    assert card.rolled_back is False


def test_rolled_back_deployment_keeps_the_card_in_production_flagged(db):
    issue = make_issue(db, source="synthetic", module="leads", points=3)
    make_pr(db, issue=issue, source="synthetic", state="merged", merged_at=NOW - timedelta(days=1))
    make_deployment(db, deployed_at=NOW - timedelta(hours=1), status="rolled_back")
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "production"
    assert card.rolled_back is True


def test_real_merged_pr_never_reaches_production_no_real_deploys_exist(db):
    issue = make_issue(db, module="leads", points=3)
    make_pr(db, issue=issue, state="merged", merged_at=NOW - timedelta(days=30))
    # A synthetic deployment exists, but it must never claim a real PR (different source).
    make_deployment(db, source="synthetic", deployed_at=NOW)
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "merged"


def test_closed_pr_that_never_merged_is_dropped(db):
    issue = make_issue(db, module="leads", points=3)
    make_pr(db, issue=issue, state="closed")
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "triaged"  # falls back to the issue's own state, PR contributes nothing


def test_closed_issue_with_no_pr_is_dropped_from_the_board(db):
    make_issue(db, state="closed")
    db.commit()
    assert build_board(db, now=NOW).cards == ()


def test_multiple_linked_prs_the_most_advanced_one_wins(db):
    issue = make_issue(db, module="leads", points=3)
    old_pr = make_pr(db, issue=issue, state="merged", merged_at=NOW - timedelta(days=5))
    new_pr = make_pr(db, issue=issue)  # just opened, still in_progress
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    assert card.column == "merged" and card.pr_number == old_pr.number
    assert new_pr.number != old_pr.number


def test_standalone_pr_with_no_linked_issue_gets_its_own_card(db):
    pr = make_pr(db, issue=None, module="platform")
    score_pr(db, pr, tier="T0", score=5)
    gate_for(db, pr, state="success", missing=())
    db.commit()
    card = by_key(build_board(db, now=NOW), f"pr-{pr.number}")
    assert card.issue_number is None and card.column == "in_review" and card.points is None


# --- owner --------------------------------------------------------------------------------


def test_owner_prefers_the_issue_assignee_then_falls_back_to_the_pr_author(db):
    dana = Engineer(login="dana", name="Dana K.", source="github")
    marcus = Engineer(login="marcus", name="Marcus L.", source="github")
    db.add_all([dana, marcus])
    db.flush()

    assigned = make_issue(db, module="leads", points=3, assignee_id=dana.id)
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{assigned.number}")
    assert card.owner == "Dana K."

    unassigned = make_issue(db, module="leads", points=2)
    make_pr(db, issue=unassigned, author_id=marcus.id)
    db.commit()
    card2 = by_key(build_board(db, now=NOW), f"issue-{unassigned.number}")
    assert card2.owner == "Marcus L."


# --- WIP and median age ---------------------------------------------------------------------


def test_column_stats_report_wip_and_median_age(db):
    make_issue(db, module="leads", points=3, created_at=NOW - timedelta(hours=10))
    make_issue(db, module="pipeline", points=2, created_at=NOW - timedelta(hours=20))
    db.commit()
    board = build_board(db, now=NOW)
    stats = board.columns["triaged"]
    assert stats["wip"] == 2
    assert stats["median_age_hours"] == 15.0
    assert board.columns["backlog"]["wip"] == 0
    assert board.columns["backlog"]["median_age_hours"] is None


# --- filters --------------------------------------------------------------------------------


def test_module_and_owner_and_source_filters(db):
    leads_issue = make_issue(db, module="leads", points=3)
    pipeline_issue = make_issue(db, source="synthetic", module="pipeline", points=2)
    db.commit()

    only_leads = build_board(db, now=NOW, module="leads")
    assert {c.key for c in only_leads.cards} == {f"issue-{leads_issue.number}"}

    only_synthetic = build_board(db, now=NOW, source="synthetic")
    assert {c.key for c in only_synthetic.cards} == {f"issue-{pipeline_issue.number}"}


def test_sprint_filter_never_excludes_real_cards(db):
    sprint = Sprint(
        name="Sprint 1",
        start_date=NOW.date(),
        end_date=NOW.date() + timedelta(days=1),
        source="synthetic",
    )
    db.add(sprint)
    db.flush()
    real_issue = make_issue(db, module="leads", points=3)  # no sprint: always visible
    synthetic_issue = make_issue(
        db, source="synthetic", module="leads", points=3, sprint_id=sprint.id
    )
    epic_backlog_issue = make_issue(
        db, source="synthetic", module="leads", points=3
    )  # unscheduled simulated story: in no sprint
    db.commit()

    board = build_board(db, now=NOW, sprint="current")
    keys = {c.key for c in board.cards}
    assert f"issue-{real_issue.number}" in keys
    assert f"issue-{synthetic_issue.number}" in keys
    assert f"issue-{epic_backlog_issue.number}" not in keys  # only under "all"
    everything = {c.key for c in build_board(db, now=NOW, sprint="all").cards}
    assert f"issue-{epic_backlog_issue.number}" in everything

    named = build_board(db, now=NOW, sprint="Sprint 2")  # a sprint that isn't this one
    keys2 = {c.key for c in named.cards}
    assert f"issue-{real_issue.number}" in keys2  # still never excluded
    assert f"issue-{synthetic_issue.number}" not in keys2  # this one really is in Sprint 1


def test_sprint_all_shows_everything(db):
    make_issue(db, source="synthetic", module="leads", points=3)
    db.commit()
    assert len(build_board(db, now=NOW, sprint="all").cards) == 1


# --- decisions carried for the drawer --------------------------------------------------------


def test_card_carries_its_decisions_for_the_detail_drawer(db):
    issue = make_issue(db, module="billing_auth", points=8)
    triage = triage_issue(db, issue)
    pr = make_pr(db, issue=issue, module="billing_auth")
    risk = score_pr(db, pr, tier="T3", score=85)
    db.commit()
    card = by_key(build_board(db, now=NOW), f"issue-{issue.number}")
    ids = {d.id for d in card.decisions}
    assert ids == {triage.id, risk.id}
