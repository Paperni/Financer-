"""
Alert notifier adapters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import request


class AlertNotifier:
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.channels = cfg.get("channels", ["console"])
        self.webhook_url = cfg.get("webhook_url")
        self.file_path = Path(cfg.get("file_path", "logs/alerts/alerts.jsonl"))
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, level: str, message: str, context: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        payload = {"level": level, "message": message, "context": context or {}}
        if "console" in self.channels:
            print(f"[ALERT:{level}] {message}")
        if "file" in self.channels:
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, default=str) + "\n")
        if "webhook" in self.channels and self.webhook_url:
            self._send_webhook(payload)

    def _send_webhook(self, payload: dict[str, Any]) -> None:
        try:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(
                self.webhook_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=5):
                pass
        except Exception:
            # Never crash trade loop because alert endpoint failed.
            return

