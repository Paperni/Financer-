"""
Alert rule helpers.
"""

from __future__ import annotations

from typing import Any


def should_alert(event: str, context: dict[str, Any] | None = None) -> bool:
    ctx = context or {}
    if event in {"emergency_flatten_triggered", "risk_halt", "critical_error"}:
        return True
    if event == "drawdown_circuit_breaker":
        return True
    if event == "trade_executed":
        return bool(ctx.get("important", False))
    return False

