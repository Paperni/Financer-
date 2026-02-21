"""
Approval queue store for manual trade workflow.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class ApprovalQueue:
    def __init__(self, queue_file: str = "control_center/approvals.json"):
        self.path = Path(queue_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save([])

    def _load(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        items = self._load()
        if status:
            return [i for i in items if i.get("status") == status]
        return items

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self._load()
        item = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "created_at": datetime.now().isoformat(),
            "status": "pending",
            "payload": payload,
            "decision_at": None,
            "decision_note": "",
        }
        items.append(item)
        self._save(items)
        return item

    def decide(self, approval_id: str, decision: str, note: str = "") -> dict[str, Any] | None:
        items = self._load()
        target = None
        for item in items:
            if item.get("id") == approval_id:
                item["status"] = "approved" if decision == "approve" else "rejected"
                item["decision_at"] = datetime.now().isoformat()
                item["decision_note"] = note
                target = item
                break
        self._save(items)
        return target

    def mark_executed(self, approval_id: str, note: str = "") -> None:
        items = self._load()
        for item in items:
            if item.get("id") == approval_id:
                item["status"] = "executed"
                item["decision_note"] = note
                item["decision_at"] = datetime.now().isoformat()
                break
        self._save(items)

