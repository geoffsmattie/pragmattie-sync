from datetime import datetime

import pytest

from sdlc import scoring
from sdlc.tables import Incident, PullRequest
from tests.conftest import NOW

FRIDAY = datetime(2026, 9, 18, 12, 0)
MONDAY = datetime(2026, 9, 14, 10, 0)


def features(**overrides) -> scoring.Features:
    base = {
        "lines": 10,
        "files_changed": 1,
        "modules_touched": 1,
        "touches_migration": False,
        "docs_only": False,
        "test_files_changed": 1,
        "review_count": 2,
        "rework_commits": 0,
        "real_ci_failures": 0,
        "at": MONDAY,
        "module_rate": 0.0,
        "max_module_rate": 0.1,
        "author_ratio": None,
    }
    return scoring.Features(**{**base, **overrides})


@pytest.mark.parametrize(
    ("lines", "points"),
    [(0, 0), (49, 0), (50, 5), (149, 5), (150, 10), (399, 10), (400, 15), (799, 15), (800, 20)],
)
def test_change_size_bands_match_the_blueprint(lines, points):
    assert scoring.change_size(lines) == points


def test_blast_radius_grows_with_files_and_module_spread():
    assert [scoring.blast_radius(f, 1) for f in (1, 3, 6, 11, 21)] == [0, 2, 4, 6, 7]
    assert scoring.blast_radius(3, 3) == 5  # +3 when more than two modules
    assert scoring.blast_radius(30, 3) == 10  # capped at the signal's maximum


def test_module_risk_is_scaled_against_the_riskiest_module():
    assert scoring.module_risk(0.1, 0.1) == 20
    assert scoring.module_risk(0.05, 0.1) == 10
    assert scoring.module_risk(0.0, 0.0) == 0  # no incidents anywhere yet


def test_author_record_is_average_until_there_is_history():
    assert scoring.author_record(None) == 5
    assert (scoring.author_record(0.0), scoring.author_record(1.0)) == (0, 5)
    assert scoring.author_record(4.0) == 10  # capped


def test_tests_with_the_change():
    assert scoring.tests_with_change(200, False, 0) == 10  # real code, no tests
    assert scoring.tests_with_change(200, False, 2) == 0
    assert scoring.tests_with_change(10, False, 0) == 0  # trivial change
    assert scoring.tests_with_change(200, True, 0) == 0  # docs only


def test_ci_review_and_rework_signals():
    assert [scoring.ci_signal(n) for n in (0, 1, 2, 5)] == [0, 4, 7, 10]
    assert scoring.review_depth(0, 10) == 5  # nobody looked
    assert scoring.review_depth(1, 500) == 5  # one rubber stamp on a large diff
    assert scoring.review_depth(1, 100) == 0
    assert [scoring.rework_churn(n) for n in (0, 1, 2, 4)] == [0, 2, 3, 5]


def test_timing_flags_fridays_weekends_and_off_hours():
    assert scoring.timing(FRIDAY) == 5
    assert scoring.timing(datetime(2026, 9, 19, 11, 0)) == 5  # Saturday
    assert scoring.timing(datetime(2026, 9, 14, 7, 30)) == 5  # before work
    assert scoring.timing(datetime(2026, 9, 14, 18, 0)) == 5  # after work
    assert scoring.timing(MONDAY) == 0


def test_a_quiet_change_scores_zero_and_the_worst_change_caps_at_100():
    assert scoring.score_features(features(author_ratio=0.0)).total == 0
    # With no history for the author, the record counts as average (5 of 10 points).
    assert scoring.score_features(features()).signals["author_record"] == 5

    worst = features(
        lines=900,
        files_changed=25,
        modules_touched=3,
        touches_migration=True,
        test_files_changed=0,
        review_count=0,
        rework_commits=3,
        real_ci_failures=3,
        at=FRIDAY,
        module_rate=0.1,
        author_ratio=3.0,
    )
    score = scoring.score_features(worst)
    assert sum(score.signals.values()) == 110  # the maxima add up to more than 100...
    assert score.total == 100  # ...and the total is capped
    assert score.signals == scoring.MAX_POINTS  # every signal at its maximum


def make_pr(db, number, module, created, merged=None, state="merged"):
    pr = PullRequest(
        source="synthetic",
        external_id=f"pr-{number}",
        number=number,
        title="x",
        module=module,
        state=state,
        created_at=created,
        merged_at=merged,
    )
    db.add(pr)
    db.flush()
    return pr


def test_history_signals_only_use_what_was_known_before_the_pr_opened(db):
    old = make_pr(db, 1, "billing_auth", datetime(2026, 8, 1), datetime(2026, 8, 2))
    db.add(
        Incident(
            source="synthetic",
            title="outage",
            severity="sev2",
            opened_at=datetime(2026, 9, 10),
            caused_by_pr_id=old.id,
        )
    )
    db.flush()

    # A PR opened before the incident cannot know about it...
    rates, team = scoring.module_rates(db, datetime(2026, 9, 1))
    assert team == 0.0 and rates["billing_auth"] == 0.0
    # ...but one opened afterwards can.
    rates, team = scoring.module_rates(db, datetime(2026, 9, 15))
    assert team == 1.0 and rates["billing_auth"] == pytest.approx((1 + 1.0 * 10) / 11)


def test_compute_features_reads_the_pr(db, history):
    pr = db.query(PullRequest).filter(PullRequest.state == "merged").first()
    f = scoring.compute_features(db, pr, NOW)
    assert f.lines == pr.additions + pr.deletions
    assert f.files_changed == pr.files_changed
    assert f.at == pr.merged_at
    assert f.max_module_rate >= f.module_rate >= 0
    assert 0 <= scoring.score_features(f).total <= 100
