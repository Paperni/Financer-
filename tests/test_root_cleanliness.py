"""Root cleanliness guard: fail if unexpected .py files or directories appear in the project root.

Allowlisted root-level .py files: none (all .py lives in packages).
Allowlisted root-level directories: financer/, tests/, docs/, scripts/, legacy/,
                                      historical_tester/, configs/, control_center/, tools/
Allowlisted root-level files: README.md, CLAUDE.md, .gitignore
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_ROOT_DIRS: set[str] = {
    "financer",
    "tests",
    "docs",
    "scripts",
    "legacy",
    "historical_tester",
    "configs",
    "control_center",
    "tools",
    "artifacts",     # gitignored runtime cache/outputs
}

ALLOWED_ROOT_FILES: set[str] = {
    "README.md",
    "CLAUDE.md",
    ".gitignore",
}


class TestRootCleanliness:
    def test_no_stray_python_files_in_root(self):
        """No .py files should live directly in the project root."""
        stray = [
            p for p in PROJECT_ROOT.iterdir()
            if p.is_file() and p.suffix == ".py"
            and not p.name.startswith(".")
        ]
        assert stray == [], (
            "Stray .py files detected in project root (move to financer/, legacy/, or scripts/):\n"
            + "\n".join(f"  {p.name}" for p in stray)
        )

    def test_no_unexpected_root_directories(self):
        """Only allowlisted directories may exist in the project root."""
        unexpected = [
            p for p in PROJECT_ROOT.iterdir()
            if p.is_dir()
            and not p.name.startswith(".")   # ignore .git, .venv, .pytest_cache etc.
            and not p.name.startswith("__")  # ignore __pycache__
            and p.name not in ALLOWED_ROOT_DIRS
        ]
        assert unexpected == [], (
            "Unexpected directories in project root (add to ALLOWED_ROOT_DIRS if intentional):\n"
            + "\n".join(f"  {p.name}/" for p in unexpected)
        )

    def test_no_stray_log_or_json_in_root(self):
        """No .log or runtime .json files should accumulate in the project root."""
        stray = [
            p for p in PROJECT_ROOT.iterdir()
            if p.is_file()
            and p.suffix in {".log", ".json", ".parquet"}
            and p.name not in ALLOWED_ROOT_FILES
        ]
        assert stray == [], (
            "Runtime artefact files found in project root (add to .gitignore and delete):\n"
            + "\n".join(f"  {p.name}" for p in stray)
        )
