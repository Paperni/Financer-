from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypedDict


class EngineResult(TypedDict):
    run_id: str
    engine: str
    config_hash: str
    metrics: dict[str, Any]
    trades: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]] | list[tuple[str, float]]
    metadata: dict[str, Any]


@dataclass
class EngineContext:
    tester_kwargs: dict[str, Any]
    run_label: str | None = None
    run_dir: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BacktestEngine(Protocol):
    name: str

    def run(self, context: EngineContext) -> EngineResult:
        ...

