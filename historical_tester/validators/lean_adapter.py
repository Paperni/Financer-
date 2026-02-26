from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypedDict


class ValidationResult(TypedDict):
    validator: str
    passed: bool
    parity_score: float
    notes: list[str]
    metrics: dict[str, Any]


class Validator(Protocol):
    name: str

    def validate(self, baseline: dict[str, Any], comparison: dict[str, Any]) -> ValidationResult:
        ...


@dataclass
class LeanValidationAdapter:
    """
    Lightweight LEAN parity validator.

    This adapter keeps validation local and compares run parity on core metrics.
    It can later be replaced with an external LEAN backtest runner.
    """

    name: str = "lean"
    return_tolerance_pct: float = 2.0
    drawdown_tolerance_pct: float = 2.0

    def validate(self, baseline: dict[str, Any], comparison: dict[str, Any]) -> ValidationResult:
        b = baseline.get("metrics", {})
        c = comparison.get("metrics", {})
        b_ret = float(b.get("total_return_pct", 0.0) or 0.0)
        c_ret = float(c.get("total_return_pct", 0.0) or 0.0)
        b_dd = float(b.get("max_drawdown_pct", 0.0) or 0.0)
        c_dd = float(c.get("max_drawdown_pct", 0.0) or 0.0)
        ret_gap = abs(b_ret - c_ret)
        dd_gap = abs(b_dd - c_dd)

        ret_score = max(0.0, 1.0 - (ret_gap / max(self.return_tolerance_pct, 1e-6)))
        dd_score = max(0.0, 1.0 - (dd_gap / max(self.drawdown_tolerance_pct, 1e-6)))
        parity_score = round((ret_score + dd_score) / 2.0, 4)
        passed = ret_gap <= self.return_tolerance_pct and dd_gap <= self.drawdown_tolerance_pct

        return {
            "validator": self.name,
            "passed": passed,
            "parity_score": parity_score,
            "notes": [
                "PoC parity validator (LEAN adapter placeholder).",
                "Use dedicated LEAN runner for full external validation in next iteration.",
            ],
            "metrics": {
                "return_gap_pct": ret_gap,
                "drawdown_gap_pct": dd_gap,
                "baseline_engine": baseline.get("engine"),
                "comparison_engine": comparison.get("engine"),
            },
        }

