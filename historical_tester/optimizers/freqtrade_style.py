from __future__ import annotations

from typing import Any

from .base import OptimizationContext, OptimizerResult
from ..engines.backtrader_engine import BacktraderEngine
from ..engines.base import EngineContext
from ..engines.native_engine import NativeEngine


class FreqtradeStyleOptimizer:
    name = "freqtrade_style"

    def _objective(self, metrics: dict[str, Any], objective_name: str) -> float:
        if objective_name == "return_drawdown_score":
            return float(metrics.get("total_return_pct", 0.0)) - abs(float(metrics.get("max_drawdown_pct", 0.0)))
        if objective_name == "sharpe":
            return float(metrics.get("sharpe_ratio", 0.0) or 0.0)
        return float(metrics.get("total_return_pct", 0.0))

    def optimize(self, context: OptimizationContext) -> OptimizerResult:
        leaderboard: list[dict[str, Any]] = []
        engine = BacktraderEngine() if context.engine == "backtrader" else NativeEngine()
        min_trades = int(context.constraints.get("min_trades", 0))
        max_drawdown_abs = context.constraints.get("max_drawdown_pct_abs", None)

        for overrides in context.override_sets:
            kwargs = dict(context.base_kwargs)
            kwargs["overrides"] = overrides
            result = engine.run(EngineContext(tester_kwargs=kwargs, run_label="optimizer"))
            metrics = result.get("metrics", {})
            trades = int(metrics.get("total_trades", 0) or 0)
            drawdown = abs(float(metrics.get("max_drawdown_pct", 0.0) or 0.0))
            constraint_ok = trades >= min_trades and (
                max_drawdown_abs is None or drawdown <= float(max_drawdown_abs)
            )
            score = self._objective(metrics, context.objective_name)
            leaderboard.append(
                {
                    "overrides": overrides,
                    "objective_score": score,
                    "constraint_ok": constraint_ok,
                    "total_return_pct": float(metrics.get("total_return_pct", 0.0) or 0.0),
                    "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0) or 0.0),
                    "win_rate_pct": float(metrics.get("win_rate_pct", 0.0) or 0.0),
                    "total_trades": trades,
                    "run_id": result.get("run_id", ""),
                }
            )

        ranking = sorted(
            leaderboard,
            key=lambda r: (r["constraint_ok"], r["objective_score"]),
            reverse=True,
        )
        best = ranking[0] if ranking else {"overrides": []}
        return {
            "best_config": {"overrides": best.get("overrides", [])},
            "leaderboard": ranking,
            "objective_name": context.objective_name,
            "trials": len(leaderboard),
        }

