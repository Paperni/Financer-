from __future__ import annotations

from datetime import datetime
from typing import Any

from .benchmark.report import write_benchmark_report
from .engines.backtrader_engine import BacktraderEngine
from .engines.base import EngineContext
from .engines.native_engine import NativeEngine
from .validators.lean_adapter import LeanValidationAdapter


def _resolve_engine(name: str):
    if name == "backtrader":
        return BacktraderEngine()
    return NativeEngine()


def run_single_engine(engine_name: str, tester_kwargs: dict[str, Any]) -> dict[str, Any]:
    engine = _resolve_engine(engine_name)
    return engine.run(EngineContext(tester_kwargs=tester_kwargs, run_label="single"))


def run_benchmark_suite(
    engine_names: list[str],
    tester_kwargs: dict[str, Any],
    validate_with: str | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for engine_name in engine_names:
        engine = _resolve_engine(engine_name)
        result = engine.run(EngineContext(tester_kwargs=tester_kwargs, run_label="benchmark"))
        results.append(result)

    validation = None
    if validate_with == "lean" and len(results) >= 2:
        validation = LeanValidationAdapter().validate(results[0], results[1])

    report_paths = write_benchmark_report(results, validate_result=validation)
    return {
        "generated_at": datetime.now().isoformat(),
        "results": results,
        "validation": validation,
        "report_paths": report_paths,
    }

