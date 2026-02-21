from __future__ import annotations

from typing import Any

from .schema import to_benchmark_record


def build_benchmark_payload(engine_results: list[dict[str, Any]]) -> dict[str, Any]:
    records = [to_benchmark_record(res["engine"], res.get("metrics", {})) for res in engine_results]
    if not records:
        return {"records": [], "deltas_vs_baseline": []}

    baseline = records[0]
    deltas = []
    for rec in records:
        deltas.append(
            {
                "engine": rec["engine"],
                "delta_return_pct": rec["total_return_pct"] - baseline["total_return_pct"],
                "delta_win_rate_pct": rec["win_rate_pct"] - baseline["win_rate_pct"],
                "delta_max_drawdown_pct": rec["max_drawdown_pct"] - baseline["max_drawdown_pct"],
                "delta_sharpe_ratio": (
                    None
                    if rec["sharpe_ratio"] is None or baseline["sharpe_ratio"] is None
                    else rec["sharpe_ratio"] - baseline["sharpe_ratio"]
                ),
            }
        )

    return {
        "baseline_engine": baseline["engine"],
        "records": records,
        "deltas_vs_baseline": deltas,
    }

