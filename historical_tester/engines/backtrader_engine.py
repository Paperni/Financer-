from __future__ import annotations

import json
from typing import Any

from .base import EngineContext, EngineResult
from ..tester import HistoricalTester


def _stable_hash(payload: dict[str, Any]) -> str:
    return str(abs(hash(json.dumps(payload, sort_keys=True, default=str))))


class BacktraderEngine:
    """
    Backtrader PoC adapter.

    Current PoC keeps strategy logic parity by replaying the existing native
    trading stack while exposing a dedicated engine contract and metadata.
    If `backtrader` is installed, we mark capability and keep parity mode.
    """

    name = "backtrader"

    def run(self, context: EngineContext) -> EngineResult:
        has_backtrader = False
        try:
            import backtrader  # noqa: F401

            has_backtrader = True
        except Exception:
            has_backtrader = False

        tester = HistoricalTester(**context.tester_kwargs, engine="backtrader_proxy")
        metrics = tester.run()
        cfg_hash = _stable_hash(
            {
                "engine": self.name,
                "kwargs": context.tester_kwargs,
                "runtime_cfg": tester.runtime_cfg,
                "has_backtrader": has_backtrader,
            }
        )
        return {
            "run_id": str(metrics.get("run_id", "")),
            "engine": self.name,
            "config_hash": cfg_hash,
            "metrics": metrics,
            "trades": metrics.get("trades", []),
            "equity_curve": metrics.get("equity_curve", []),
            "metadata": {
                "run_label": context.run_label,
                "backtrader_installed": has_backtrader,
                "poc_mode": "proxy-parity",
            },
        }

