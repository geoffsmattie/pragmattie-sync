import json
from datetime import datetime

from sdlc import export_rebuild
from sdlc.audit import record_decision
from sdlc.tables import AgentDecision, Approval, PullRequest

NOW = datetime(2026, 10, 14, 12, 0)


def _pr(db, number, source):
    pr = PullRequest(
        source=source,
        external_id=f"pr-{number}",
        number=number,
        title=f"PR {number}",
        state="open",
        created_at=NOW,
    )
    db.add(pr)
    db.flush()
    return pr


def _decision(db, agent, source, subject_id, **fields):
    return record_decision(
        db,
        agent=agent,
        agent_version="v1",
        subject_type=fields.pop("subject_type", "pr"),
        subject_source=source,
        subject_id=subject_id,
        trigger=fields.pop("trigger", "poll"),
        now=NOW,
        **fields,
    )


def test_the_export_holds_only_the_rebuilds_rows_with_every_field(db):
    rebuild_pr, own_pr = _pr(db, 200, "agentic"), _pr(db, 7, "github")
    first = _decision(
        db,
        "pr_risk",
        "agentic",
        200,
        head_sha="abc",
        inputs_digest={"files": 3},
        raw_score=30,
        adjustment=5,
        final_score=35,
        tier="T1",
        signals={"change_size": 10},
        output={"reasons": ["small"]},
        status="ok",
    )
    second = _decision(db, "pr_risk", "agentic", 200, head_sha="abc", attempt=2, status="ok")
    second.supersedes_id = first.id
    _decision(db, "triage", "agentic", 150, subject_type="issue", head_sha="v1", status="ok")
    _decision(db, "pr_risk", "github", 7, head_sha="def", status="ok")  # v1's own repository
    _decision(db, "pr_risk", "synthetic", 9, head_sha="ghi", status="ok")
    for pr in (rebuild_pr, own_pr):
        db.add(
            Approval(
                pull_request_id=pr.id,
                approver_id="simulated-second",
                tier="T3",
                status="approved",
                reason="migration",
                requested_at=NOW,
                decided_at=NOW,
            )
        )
    db.commit()

    data = export_rebuild.export(db, "pragmattie/pragmattie-sync-agentic", now=NOW)

    assert data["exported_at"] == "2026-10-14T12:00:00"
    assert data["repository"] == "pragmattie/pragmattie-sync-agentic"
    assert [(d["agent"], d["subject_id"]) for d in data["decisions"]] == [
        ("pr_risk", 200),
        ("pr_risk", 200),
        ("triage", 150),
    ]  # oldest first, the rebuild's only
    row = data["decisions"][0]
    assert set(row) == set(export_rebuild.DECISION_FIELDS)
    assert (row["inputs_digest"], row["final_score"], row["tier"]) == ({"files": 3}, 35, "T1")
    assert row["created_at"] == "2026-10-14T12:00:00"
    assert data["decisions"][1]["supersedes_id"] == row["id"]
    assert data["approvals"] == [
        {
            "pr": 200,
            "approver_id": "simulated-second",
            "tier": "T3",
            "status": "approved",
            "reason": "migration",
            "note": None,
            "requested_at": "2026-10-14T12:00:00",
            "decided_at": "2026-10-14T12:00:00",
        }
    ]
    json.dumps(data)  # it serializes as it is


def test_the_command_writes_the_file_and_says_what_it_wrote(db, tmp_path, capsys):
    _decision(db, "release_gate", "agentic", 210, subject_type="release", head_sha="e9e")
    db.commit()
    out = tmp_path / "export.json"

    export_rebuild.main(["--out", str(out)])

    data = json.loads(out.read_text(encoding="utf-8"))
    assert [d["agent"] for d in data["decisions"]] == ["release_gate"]
    assert "Exported 1 decisions and 0 approvals about pragmattie/pragmattie-sync-agentic" in (
        capsys.readouterr().out
    )
    assert db.query(AgentDecision).count() == 1  # it only reads
