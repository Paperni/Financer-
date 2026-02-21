"""
Lightweight local Control Center API server.

Endpoints:
- GET /status
- GET /controls
- POST /controls   (json patch)
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .state_store import ControlStateStore
from .approvals import ApprovalQueue


class _Handler(BaseHTTPRequestHandler):
    store = ControlStateStore()
    approvals = ApprovalQueue()

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/status":
            self._send(200, {"ok": True, "service": "control_center"})
            return
        if self.path == "/controls":
            self._send(200, self.store.load())
            return
        if self.path == "/approvals":
            self._send(200, {"items": self.approvals.list()})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path not in {"/controls", "/approvals/decision"}:
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            patch = json.loads(raw) if raw else {}
            if not isinstance(patch, dict):
                raise ValueError("Expected JSON object")
            if self.path == "/controls":
                state = self.store.update(patch)
                self._send(200, state)
                return
            approval_id = str(patch.get("id", ""))
            decision = str(patch.get("decision", "reject"))
            note = str(patch.get("note", ""))
            item = self.approvals.decide(approval_id, decision, note)
            if not item:
                self._send(404, {"error": "approval id not found"})
                return
            self._send(200, item)
        except Exception as exc:
            self._send(400, {"error": str(exc)})


def run_control_center(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = HTTPServer((host, port), _Handler)
    print(f"Control Center API running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_control_center()

