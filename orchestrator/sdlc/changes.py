"""Facts about which files a pull request changed.

Shared by the GitHub collector (real paths) and the risk score (Phase 4), so both read a PR
the same way. The synthetic history has no real paths and sets the same facts directly.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

# Infer a module from file paths when a PR has no module: label. Case-insensitive, so Vue
# components such as LeadsView.vue match as well as lead.py; the floors depend on this.
PATH_MODULES = [
    (re.compile(r"(^|/)(leads|lead)[^/]*\b", re.I), "leads"),
    (re.compile(r"(^|/)accounts?[^/]*\b|AccountDetail", re.I), "accounts"),
    (re.compile(r"(^|/)(opportunities|pipeline)[^/]*", re.I), "pipeline"),
    (re.compile(r"forecast", re.I), "forecasting"),
    (re.compile(r"^orchestrator/"), "orchestrator"),
]

MIGRATION_DIR = "alembic/versions/"

TEST_FILE = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|\.(spec|test)\.[jt]sx?$")

DOC_OR_CONFIG_SUFFIXES = {".md", ".rst", ".txt", ".yml", ".yaml", ".toml", ".ini", ".cfg"}
DOC_OR_CONFIG_NAMES = {".editorconfig", ".gitattributes", ".gitignore", ".env.example", "LICENSE"}
# Dependency manifests change what code runs, so they never count as docs or config.
DEPENDENCY_FILE = re.compile(r"(^|/)(requirements[^/]*\.txt|package(-lock)?\.json)$")
# Editing these changes governance or CI itself, so they never count as "just config".
GOVERNANCE_PATHS = ("orchestrator/policies/", ".github/workflows/")


@dataclass(frozen=True)
class FileFacts:
    touches_migration: bool
    test_files_changed: int
    docs_only: bool  # docs, copy or config only (a tier T0 candidate)
    modules_touched: int


def module_of(path: str) -> str | None:
    for pattern, module in PATH_MODULES:
        if pattern.search(path):
            return module
    return None


def infer_module(paths: list[str]) -> str:
    votes: dict[str, int] = {}
    for path in paths:
        if module := module_of(path):
            votes[module] = votes.get(module, 0) + 1
    return max(votes, key=votes.get) if votes else "platform"


def is_test_file(path: str) -> bool:
    return bool(TEST_FILE.search(path))


def is_docs_or_config(path: str) -> bool:
    if DEPENDENCY_FILE.search(path) or path.startswith(GOVERNANCE_PATHS):
        return False
    name = PurePosixPath(path)
    return (
        path.startswith(("docs/", ".github/"))
        or name.suffix.lower() in DOC_OR_CONFIG_SUFFIXES
        or name.name in DOC_OR_CONFIG_NAMES
    )


def classify_files(paths: list[str]) -> FileFacts:
    return FileFacts(
        touches_migration=any(MIGRATION_DIR in p for p in paths),
        test_files_changed=sum(is_test_file(p) for p in paths),
        docs_only=bool(paths) and all(is_docs_or_config(p) for p in paths),
        modules_touched=len({m for p in paths if (m := module_of(p))}) or 1,
    )
