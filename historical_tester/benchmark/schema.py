from __future__ import annotations

from typing import Any, TypedDict


class BenchmarkRecord(TypedDict):
    engine: str
    total_return_pct: float
    win_rate_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    total_trades: int
    fee_drag_pct: float
    avg_hold_time_hours: float | None


def to_benchmark_record(engine_name: str, metrics: dict[str, Any]) -> BenchmarkRecord:
    return {
        "engine": engine_name,
        "total_return_pct": float(metrics.get("total_return_pct", 0.0) or 0.0),
        "win_rate_pct": float(metrics.get("win_rate_pct", 0.0) or 0.0),
        "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0) or 0.0),
        "sharpe_ratio": metrics.get("sharpe_ratio", None),
        "total_trades": int(metrics.get("total_trades", 0) or 0),
        "fee_drag_pct": float(metrics.get("fee_drag_pct", 0.0) or 0.0),
        "avg_hold_time_hours": metrics.get("avg_hold_time_hours", None),
    }

