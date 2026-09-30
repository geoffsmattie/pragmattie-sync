from sdlc.changes import classify_files, infer_module, is_docs_or_config, is_test_file


def test_docs_and_config_only_prs_are_flagged():
    assert classify_files(["README.md", "docs/architecture.md", ".gitignore"]).docs_only
    assert classify_files(["docker-compose.yml", ".github/pull_request_template.md"]).docs_only


def test_anything_else_in_the_change_means_not_docs_only():
    assert not classify_files(["README.md", "apps/api/app/main.py"]).docs_only
    assert not classify_files([]).docs_only  # nothing known about the files: never assume T0


def test_governance_and_dependency_files_never_count_as_config():
    # Editing the tier policy or CI must not be able to reach T0.
    assert not is_docs_or_config("orchestrator/policies/tiers.yaml")
    assert not is_docs_or_config("orchestrator/policies/approvers.yaml")
    assert not is_docs_or_config(".github/workflows/ci.yml")
    # Dependency manifests change what code runs.
    assert not is_docs_or_config("apps/api/requirements.txt")
    assert not is_docs_or_config("apps/web/package-lock.json")
    assert is_docs_or_config("CLAUDE.md")


def test_test_files_are_counted():
    paths = [
        "apps/api/tests/test_leads.py",
        "apps/web/tests/format.spec.js",
        "orchestrator/tests/conftest.py",
        "apps/api/app/api/leads.py",
    ]
    assert [is_test_file(p) for p in paths] == [True, True, True, False]
    assert classify_files(paths).test_files_changed == 3


def test_migrations_are_detected():
    facts = classify_files(["apps/api/alembic/versions/0003_stage_history.py"])
    assert facts.touches_migration and not facts.docs_only


def test_migrations_folder_named_migrations_is_detected_too():
    # The rebuild keeps its Alembic revisions in migrations/versions/ (PR #97 there scored T1).
    assert classify_files(["orchestrator/migrations/versions/0001_initial.py"]).touches_migration
    assert classify_files(["apps/api/migrations/versions/0001_initial.py"]).touches_migration
    assert not classify_files(["apps/api/migrations/env.py"]).touches_migration
    assert not classify_files(["docs/versions/notes.md"]).touches_migration


def test_workflows_and_policies_are_governance_files():
    assert classify_files([".github/workflows/implement.yml"]).touches_governance
    mixed = ["apps/api/app/main.py", "orchestrator/policies/tiers.yaml"]
    assert classify_files(mixed).touches_governance
    # A proposed workflow does nothing until a person applies it, and other .github files are docs.
    assert not classify_files(["ci/proposed/ci.yml"]).touches_governance
    assert not classify_files([".github/ISSUE_TEMPLATE/agent-task.yml"]).touches_governance


def test_modules_touched_counts_distinct_modules_and_is_at_least_one():
    paths = [
        "apps/web/src/views/LeadsView.vue",
        "apps/api/app/api/opportunities.py",
        "apps/api/app/forecast.py",
        "apps/api/app/api/pipeline_helpers.py",
    ]
    assert classify_files(paths).modules_touched == 3  # leads, pipeline, forecasting
    assert classify_files(["README.md"]).modules_touched == 1


def test_infer_module_is_shared_with_the_collector():
    assert infer_module(["orchestrator/sdlc/api.py"]) == "orchestrator"
    assert infer_module(["README.md"]) == "platform"


def test_no_source_module_looks_like_a_test_file():
    """The risk score and the test selector read `test_*.py` as a test. A source module named
    that way would be miscounted as tests (it happened once: sdlc/test_selector.py)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for app in ("sdlc", "alembic"):
        for path in (root / app).rglob("*.py"):
            relative = f"orchestrator/{path.relative_to(root).as_posix()}"
            assert not is_test_file(relative), relative
