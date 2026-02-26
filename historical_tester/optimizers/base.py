from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict


class OptimizerResult(TypedDict):
    best_config: dict[str, Any]
    leaderboard: list[dict[str, Any]]
    objective_name: str
    trials: int


@dataclass
class OptimizationContext:
    base_kwargs: dict[str, Any]
    override_sets: list[list[str]]
    objective_name: str = "return_drawdown_score"
    constraints: dict[str, Any] = field(default_factory=dict)
    engine: str = "native"


class Optimizer(Protocol):
    name: str

    def optimize(self, context: OptimizationContext) -> OptimizerResult:
        ...

