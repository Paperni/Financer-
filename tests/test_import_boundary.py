"""Import boundary enforcement for financer/ package.

Rule: financer/ must NEVER import root-level scripts (portfolio.py,
indicators.py, live_trader.py, smart_trader.py, etc.).

Root scripts may import financer/.  The reverse is forbidden.

This test statically scans all .py files under financer/ and fails if
any import statement references a known root-level module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Root-level modules that financer/ must never import.
# Extend this set as new root scripts are added.
FORBIDDEN_ROOT_MODULES: set[str] = {
    "analyzer",
    "data_engine",
    "data_static",
    "diagnose_signals",
    "downloader",
    "indicators",
    "live_trader",
    "metrics",
    "news_engine",
    "portfolio",
    "qualitative",
    "smart_trader",
    "technical",
    "trader",
}

FINANCER_ROOT = Path(__file__).resolve().parent.parent / "financer"


def _collect_imports(filepath: Path) -> list[tuple[int, str]]:
    """Parse a Python file and return (line_number, module_name) for every import."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Top-level module is the first dotted component
                top = alias.name.split(".")[0]
                results.append((node.lineno, top))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # absolute imports only
                top = node.module.split(".")[0]
                results.append((node.lineno, top))
    return results


def _scan_financer_imports() -> list[str]:
    """Scan all .py files under financer/ for forbidden imports."""
    violations: list[str] = []
    for pyfile in sorted(FINANCER_ROOT.rglob("*.py")):
        rel = pyfile.relative_to(FINANCER_ROOT.parent)
        for lineno, module in _collect_imports(pyfile):
            if module in FORBIDDEN_ROOT_MODULES:
                violations.append(f"{rel}:{lineno} imports '{module}'")
    return violations


class TestImportBoundary:
    def test_financer_does_not_import_root_modules(self):
        """financer/ must never import root-level scripts."""
        violations = _scan_financer_imports()
        assert violations == [], (
            "Import boundary violated! financer/ must not import root-level modules.\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_forbidden_list_is_not_empty(self):
        """Safety check: ensure the forbidden set is populated."""
        assert len(FORBIDDEN_ROOT_MODULES) >= 10

    def test_financer_package_exists(self):
        """Sanity check: financer/ directory exists."""
        assert FINANCER_ROOT.is_dir(), f"Expected {FINANCER_ROOT} to exist"
