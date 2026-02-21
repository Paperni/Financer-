"""
Run registry for historical testing artifacts.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class RunRegistry:
    def __init__(self, base_dir: str = "test_results/runs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_run(self, meta: dict[str, Any]) -> tuple[str, Path]:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, default=str),
            encoding="utf-8",
        )
        return run_id, run_dir

    def save_summary(self, run_dir: Path, summary: dict[str, Any]) -> None:
        (run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )

    def append_leaderboard(self, row: dict[str, Any]) -> None:
        leaderboard = self.base_dir / "leaderboard.jsonl"
        with leaderboard.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")

