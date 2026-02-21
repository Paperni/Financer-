from __future__ import annotations

import json
from typing import Any

from .base import EngineContext, EngineResult
from ..tester import HistoricalTester


def _stable_hash(payload: dict[str, Any]) -> str:
    return str(abs(hash(json.dumps(payload, sort_keys=True, default=str))))


class NativeEngine:
    name = "native"

    def run(self, context: EngineContext) -> EngineResult:
        tester = HistoricalTester(**context.tester_kwargs, engine=self.name)
        metrics = tester.run()
        cfg_hash = _stable_hash(
            {
                "engine": self.name,
                "kwargs": context.tester_kwargs,
                "runtime_cfg": tester.runtime_cfg,
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
                "mode": "live-logic-replay",
            },
        }

