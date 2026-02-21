"""
Control Center state store (file-backed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ControlStateStore:
    def __init__(self, state_file: str = "control_center/state.json"):
        self.path = Path(state_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(self.default_state())

    @staticmethod
    def default_state() -> dict[str, Any]:
        return {
            "running": True,
            "pause_buys": False,
            "pause_sells": False,
            "emergency_flatten": False,
            "approval_mode": "auto",  # auto | manual
            "profile_override": None,
            "notes": "",
        }

    def load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            state = self.default_state()
            self.save(state)
            return state

    def save(self, state: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        state.update(patch)
        self.save(state)
        return state

