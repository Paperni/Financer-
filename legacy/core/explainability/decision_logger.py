"""
Structured decision logging for explainability and audits.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class DecisionLogger:
    def __init__(self, log_dir: str = "logs/decisions"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self) -> Path:
        day = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"{day}.jsonl"

    def log(self, event: str, ticker: str | None = None, reason: str = "", context: dict[str, Any] | None = None):
        rec = {
            "ts": datetime.now().isoformat(),
            "event": event,
            "ticker": ticker,
            "reason": reason,
            "context": context or {},
        }
        with self._file_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")

