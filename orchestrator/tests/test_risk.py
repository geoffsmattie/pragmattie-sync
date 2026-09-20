from datetime import datetime

import pytest
from sqlalchemy import func, select

from sdlc import risk
from sdlc.audit import record_decision
from sdlc.calibration import calibrate, calibrate_many, format_many, format_report, pool
from sdlc.tables import AgentDecision, PullRequest
from sdlc.tiers import load_policy

NOW = datetime(2026, 9, 20, 9, 0)


def make_pr(db, number=301, module="billing_auth", **kwargs):
    pr = PullRequest(
        source="synthetic",
        external_id=f"syn-{number}",
        number=number,
        title="Rework billing sync",
        module=module,
        state="open",
        created_at=NOW,
        additions=300,
        deletions=40,
        files_changed=5,
        **kwargs,
    )
    db.add(pr)
    db.flush()
    return pr


def test_record_decision_appends_and_never_updates(db):
    pr = make_pr(db)
    first = record_decision(
        db, agent="pr_risk", agent_version="v1", pr=pr, trigger="manual", now=NOW, final_score=40
    )
    correction = record_decision(
        db,
        agent="pr_risk",
        agent_version="v1",
        pr=pr,
        trigger="manual",
        now=NOW,
        final_score=55,
        supersedes_id=first.id,
    )
    assert db.scalar(select(func.count()).select_from(AgentDecision)) == 2
    assert first.final_score == 40  # the earlier row is untouched
    assert correction.supersedes_id == first.id
    assert (first.subject_type, first.subject_source, first.subject_id) == ("pr", "synthetic", 301)


def test_explain_shows_the_score_the_tier_and_why(db, capsys):
    make_pr(db)
    db.commit()
    risk.main(["explain", "301"])
    out = capsys.readouterr().out
    assert "PR #301 [synthetic]" in out
    assert "change_size" in out and "/ 20" in out
    assert "tier T3" in out  # the billing_auth floor
    assert "billing_auth" in out
    assert db.scalar(select(func.count()).select_from(AgentDecision)) == 0  # read-only by default


def test_explain_record_writes_one_audit_row(db, capsys):
    make_pr(db)
    db.commit()
    risk.main(["explain", "301", "--record"])
    assert "Recorded as decision" in capsys.readouterr().out
    row = db.scalar(select(AgentDecision))
    assert (row.agent, row.tier, row.status, row.trigger) == (
        "pr_risk_rubric",
        "T3",
        "ok",
        "manual",
    )
    assert row.final_score == row.raw_score and row.adjustment is None
    assert set(row.signals) == set(risk.MAX_POINTS)
    assert row.inputs_digest["lines"] == 340


def test_unknown_pr_is_reported_without_a_traceback(db):
    with pytest.raises(SystemExit, match="No pull request #999"):
        risk.main(["explain", "999"])


def test_calibrating_one_history_reports_its_shape(db, history):
    # One history is a noisy judge (its top decile catches 27%-86% depending on the draw), so this
    # checks the report's shape and leaves the pass/fail bars to the pooled test below.
    report = calibrate(db, load_policy())
    assert sum(t["prs"] for t in report["by_tier"].values()) == report["merged_prs"]
    assert report["incident_prs"] > 5
    recalls = [t["recall"] for t in report["thresholds"].values()]
    assert recalls == sorted(recalls, reverse=True)  # a stricter threshold can't find more
    assert set(report["bars"]) == {"t0_has_no_incidents", "top_decile_captures_majority"}
    assert "Bar 1" in format_report(report)


def test_pooling_adds_runs_together():
    def run(prs, incidents, captured):
        return {
            "merged_prs": prs,
            "incident_prs": incidents,
            "by_tier": {t: {"prs": prs // 4, "incidents": 0} for t in ("T0", "T1", "T2", "T3")},
            "top_decile": {"prs": prs // 10, "incidents_captured": captured},
            "thresholds": {
                t: {"flagged": 10, "hits": incidents, "precision": 0, "recall": 0}
                for t in ("T1", "T2", "T3")
            },
        }

    pooled = pool([run(100, 4, 3), run(200, 6, 2)])
    assert (pooled["histories"], pooled["merged_prs"], pooled["incident_prs"]) == (2, 300, 10)
    assert pooled["top_decile_capture"] == 0.5  # 5 of 10, pooled, not the mean of 75% and 33%
    assert (pooled["top_decile_capture_min"], pooled["top_decile_capture_max"]) == (
        pytest.approx(1 / 3),
        0.75,
    )
    assert pooled["histories_with_no_t0_incident"] == 2
    assert pooled["thresholds"]["T1"]["flagged"] == 20
    assert pooled["thresholds"]["T1"]["recall"] == pytest.approx(1.0)  # 4 + 6 hits of 10 incidents


def test_pooled_calibration_meets_the_bars_across_30_generated_histories():
    # The acceptance check: don't let a weight change quietly break it. The seeds and the clock are
    # fixed, so this is deterministic; the thresholds were set before the first pooled run.
    report = calibrate_many(load_policy(), histories=30)
    assert report["histories"] == 30
    assert report["incident_prs"] > 300  # enough incidents to judge, unlike one history's ~14
    assert report["bars"] == {
        "t0_rate_at_most_a_quarter_of_overall": True,
        "top_decile_captures_majority_pooled": True,
    }
    text = format_many(report)
    assert "Bar 1" in text and "Bar 2" in text and "FAIL" not in text
