"""
Historical testing lab tools:
- parameter sweeps
- walk-forward evaluation
- A/B comparisons
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .tester import HistoricalTester


def run_parameter_sweep(base_kwargs: dict[str, Any], override_sets: list[list[str]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for overrides in override_sets:
        tester = HistoricalTester(**base_kwargs, overrides=overrides)
        summary = tester.run()
        summary["overrides"] = overrides
        results.append(summary)
    return results


def run_walk_forward(
    base_kwargs: dict[str, Any],
    window_days: int = 30,
    step_days: int = 15,
) -> list[dict[str, Any]]:
    start = base_kwargs["start_date"]
    end = base_kwargs["end_date"]
    cursor = start
    results: list[dict[str, Any]] = []

    while cursor < end:
        window_end = min(cursor + timedelta(days=window_days), end)
        kwargs = dict(base_kwargs)
        kwargs["start_date"] = cursor
        kwargs["end_date"] = window_end
        tester = HistoricalTester(**kwargs)
        summary = tester.run()
        summary["window_start"] = cursor.isoformat()
        summary["window_end"] = window_end.isoformat()
        results.append(summary)
        cursor = cursor + timedelta(days=step_days)

    return results


def run_ab_compare(base_kwargs: dict[str, Any], profile_a: str, profile_b: str) -> dict[str, Any]:
    a_kwargs = dict(base_kwargs)
    b_kwargs = dict(base_kwargs)
    a_kwargs["profile"] = profile_a
    b_kwargs["profile"] = profile_b

    a_res = HistoricalTester(**a_kwargs).run()
    b_res = HistoricalTester(**b_kwargs).run()
    return {
        "profile_a": profile_a,
        "profile_b": profile_b,
        "a": a_res,
        "b": b_res,
        "delta_return_pct": a_res.get("total_return_pct", 0) - b_res.get("total_return_pct", 0),
        "delta_win_rate_pct": a_res.get("win_rate_pct", 0) - b_res.get("win_rate_pct", 0),
    }

