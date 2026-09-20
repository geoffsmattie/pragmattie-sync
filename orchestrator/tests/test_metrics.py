from datetime import date, datetime, timedelta

from sdlc.metrics import ci_health, dora_summary, pr_cycle_time, sprint_velocity
from sdlc.tables import CIRun, Deployment, Incident, Issue, PullRequest, Sprint

NOW = datetime(2026, 9, 18, 12, 0)


def test_dora_summary(db):
    deploy_ok = Deployment(version="a", deployed_at=NOW - timedelta(days=3), status="success")
    deploy_bad = Deployment(version="b", deployed_at=NOW - timedelta(days=2), status="success")
    rollback = Deployment(version="c", deployed_at=NOW - timedelta(days=1), status="rolled_back")
    db.add_all([deploy_ok, deploy_bad, rollback])
    db.flush()
    for hours in (10, 20, 30):
        opened = NOW - timedelta(days=5)
        db.add(
            PullRequest(
                title="x",
                state="merged",
                created_at=opened,
                merged_at=opened + timedelta(hours=hours),
            )
        )
    db.add(
        Incident(
            title="down",
            severity="sev2",
            opened_at=NOW - timedelta(days=2),
            resolved_at=NOW - timedelta(days=2) + timedelta(hours=4),
            deployment_id=deploy_bad.id,
        )
    )
    db.commit()

    current = dora_summary(db, NOW, days=28)["current"]
    assert current["deploys_per_week"] == 0.8  # 3 deploys over 4 weeks
    assert current["lead_time_hours"] == 20
    assert current["change_failure_rate"] == 66.7  # 1 incident deploy + 1 rollback of 3
    assert current["time_to_restore_hours"] == 4


def test_sprint_velocity_counts_work_closed_by_sprint_end(db):
    sprint = Sprint(name="Sprint 1", start_date=date(2026, 9, 7), end_date=date(2026, 9, 20))
    db.add(sprint)
    db.flush()
    created = datetime(2026, 9, 1)
    db.add_all(
        [
            Issue(
                title="a",
                estimate_points=5,
                sprint_id=sprint.id,
                created_at=created,
                closed_at=datetime(2026, 9, 10),
                state="closed",
            ),
            Issue(
                title="b",
                estimate_points=3,
                sprint_id=sprint.id,
                created_at=created,
                closed_at=datetime(2026, 9, 22),
                state="closed",
            ),
            Issue(title="c", estimate_points=2, sprint_id=sprint.id, created_at=created),
        ]
    )
    db.commit()
    [row] = sprint_velocity(db, date(2026, 9, 18))
    assert (row["committed"], row["completed"], row["in_progress"]) == (10, 5, True)


def test_cycle_time_and_ci_health(db):
    monday = datetime(2026, 9, 14, 9)
    for hours in (4, 8, 12, 100):
        db.add(
            PullRequest(
                title="x",
                state="merged",
                created_at=monday,
                merged_at=monday + timedelta(hours=hours),
            )
        )
    for conclusion, flaky in [
        ("success", False),
        ("failure", True),
        ("success", False),
        ("failure", False),
    ]:
        db.add(CIRun(suite="api", conclusion=conclusion, flaky=flaky, started_at=monday))
    db.commit()

    [week] = pr_cycle_time(db, weeks=4, now=NOW)
    assert week["median_hours"] == 10
    assert week["merged"] == 4
    [suite] = ci_health(db, weeks=4, now=NOW)["by_suite"]
    assert (suite["pass_rate"], suite["flaky_rate"]) == (50.0, 25.0)
