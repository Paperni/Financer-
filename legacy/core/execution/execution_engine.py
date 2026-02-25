"""
Execution realism layer for simulation environments.

This module focuses on:
- order mode behavior (market, limit, stop_limit)
- intraday trade window controls
- simple fill/no-fill simulation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ExecutionConfig:
    order_mode: str = "market"  # market | limit | stop_limit
    no_trade_first_minutes: int = 0
    no_trade_last_minutes: int = 0
    limit_offset_pct: float = 0.0
    stop_offset_pct: float = 0.001


class ExecutionEngine:
    def __init__(self, cfg: dict[str, Any] | None = None):
        c = cfg or {}
        self.cfg = ExecutionConfig(
            order_mode=str(c.get("order_mode", "market")),
            no_trade_first_minutes=int(c.get("no_trade_first_minutes", 0)),
            no_trade_last_minutes=int(c.get("no_trade_last_minutes", 0)),
            limit_offset_pct=float(c.get("limit_offset_pct", 0.0)),
            stop_offset_pct=float(c.get("stop_offset_pct", 0.001)),
        )

    def can_open_position(self, now_dt: datetime) -> tuple[bool, str]:
        """
        Optional intraday guardrails:
        - avoid first X minutes after 9:30 ET
        - avoid last X minutes before 16:00 ET
        """
        open_minutes = (now_dt.hour * 60 + now_dt.minute) - (9 * 60 + 30)
        close_minutes = (16 * 60) - (now_dt.hour * 60 + now_dt.minute)

        if self.cfg.no_trade_first_minutes > 0 and open_minutes < self.cfg.no_trade_first_minutes:
            return False, f"blocked by opening-window guard ({self.cfg.no_trade_first_minutes}m)"
        if self.cfg.no_trade_last_minutes > 0 and close_minutes < self.cfg.no_trade_last_minutes:
            return False, f"blocked by closing-window guard ({self.cfg.no_trade_last_minutes}m)"
        return True, "OK"

    def resolve_entry(self, row, signal_price: float) -> dict[str, Any]:
        """
        Decide if/how an entry fills on the current bar.
        Expects row with Close/High/Low where available.
        """
        mode = self.cfg.order_mode
        close = float(row.get("Close", signal_price))
        high = float(row.get("High", close))
        low = float(row.get("Low", close))

        if mode == "market":
            return {"filled": True, "price": close, "mode": mode}

        if mode == "limit":
            limit_price = signal_price * (1.0 - self.cfg.limit_offset_pct)
            return {
                "filled": low <= limit_price,
                "price": float(limit_price),
                "mode": mode,
            }

        if mode == "stop_limit":
            stop_price = signal_price * (1.0 + self.cfg.stop_offset_pct)
            limit_price = stop_price
            triggered = high >= stop_price
            filled = triggered and low <= limit_price <= high
            return {
                "filled": filled,
                "price": float(limit_price),
                "mode": mode,
            }

        # Fallback to market mode for unknown values
        return {"filled": True, "price": close, "mode": "market"}

