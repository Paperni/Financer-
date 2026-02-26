from __future__ import annotations

from typing import Any


def run_external_lean_validation(_: dict[str, Any]) -> dict[str, Any]:
    """
    Reserved hook for future LEAN CLI/container integration.
    """
    return {
        "status": "not_implemented",
        "message": "External LEAN execution is not wired in this PoC.",
    }

