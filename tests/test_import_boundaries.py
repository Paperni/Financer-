"""Internal architecture boundary enforcement tests for the financer/ package.

Rules:
- engines/ must not import execution/ or live/
- analytics/ must not import broker/ or live/
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

FINANCER_ROOT = Path(__file__).resolve().parent.parent / "financer"

def _collect_imports(filepath: Path) -> list[tuple[int, str]]:
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0: 
                results.append((node.lineno, node.module))
    return results

def _scan_directory_for_forbidden_prefixes(sub_dir: str, forbidden_prefixes: list[str]) -> list[str]:
    violations: list[str] = []
    target_dir = FINANCER_ROOT / sub_dir
    
    if not target_dir.exists():
        return violations # Passes if directory doesn't exist yet
        
    for pyfile in sorted(target_dir.rglob("*.py")):
        rel = pyfile.relative_to(FINANCER_ROOT.parent)
        for lineno, module in _collect_imports(pyfile):
            for prefix in forbidden_prefixes:
                if module == prefix or module.startswith(prefix + "."):
                    violations.append(f"{rel}:{lineno} unlawfully imports '{module}' (banned prefix: {prefix})")
    
    return violations

class TestInternalBoundaries:
    def test_engines_do_not_import_execution_or_live(self):
        """engines/ must be pure model evaluators and not import execution or live loop state."""
        banned = ["financer.execution", "financer.live"]
        violations = _scan_directory_for_forbidden_prefixes("engines", banned)
        assert violations == [], (
            "Architecture boundary violated! engines/ must not import execution/ or live/.\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_analytics_does_not_import_broker_or_live(self):
        """analytics/ must be purely observational and not import broker execution or live loop state."""
        banned = ["financer.execution.broker", "financer.live"]
        violations = _scan_directory_for_forbidden_prefixes("analytics", banned)
        assert violations == [], (
            "Architecture boundary violated! analytics/ must not import broker or live/.\n"
            + "\n".join(f"  - {v}" for v in violations)
        )
