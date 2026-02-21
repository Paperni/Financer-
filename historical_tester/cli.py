from __future__ import annotations

import argparse
import json
from datetime import datetime
import zoneinfo


def _parse_dt(raw: str) -> datetime:
    dt = datetime.strptime(raw, "%Y-%m-%d")
    return dt.replace(tzinfo=zoneinfo.ZoneInfo("America/New_York"))


def _parse_overrides(raw: str) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Historical tester orchestrator")
    parser.add_argument("--mode", default="single", choices=["single", "benchmark", "sweep", "interactive"])
    parser.add_argument("--engine", default="native", choices=["native", "backtrader"])
    parser.add_argument("--engines", default="native,backtrader")
    parser.add_argument("--validate-with", default="", choices=["", "lean"])
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-03-01")
    parser.add_argument("--capital", type=float, default=None)
    parser.add_argument("--wallet-path", default="test_wallet.json")
    parser.add_argument("--speed", type=float, default=10.0)
    parser.add_argument("--config", default="configs/strategy/default.yaml")
    parser.add_argument("--profile", default="balanced")
    parser.add_argument("--overrides", default="")
    args = parser.parse_args()

    if args.mode == "interactive":
        from .tester import interactive_cli

        interactive_cli()
        return

    tester_kwargs = {
        "start_date": _parse_dt(args.start_date),
        "end_date": _parse_dt(args.end_date),
        "initial_capital": args.capital,
        "wallet_path": args.wallet_path,
        "speed_multiplier": args.speed,
        "config_path": args.config,
        "profile": args.profile,
        "overrides": _parse_overrides(args.overrides),
    }

    if args.mode == "single":
        from .orchestrator import run_single_engine

        result = run_single_engine(args.engine, tester_kwargs)
        print(json.dumps({"engine": result["engine"], "run_id": result["run_id"]}, indent=2))
        return

    if args.mode == "benchmark":
        from .orchestrator import run_benchmark_suite

        engine_names = [e.strip() for e in args.engines.split(",") if e.strip()]
        suite = run_benchmark_suite(engine_names, tester_kwargs, validate_with=(args.validate_with or None))
        print(json.dumps(suite["report_paths"], indent=2))
        return

    if args.mode == "sweep":
        from .optimizer import run_parameter_sweep

        override_sets = [
            ["risk.max_positions_per_sector=2"],
            ["risk.max_positions_per_sector=3"],
            ["risk.max_positions_per_sector=4"],
        ]
        results = run_parameter_sweep(tester_kwargs, override_sets, engine=args.engine)
        print(json.dumps({"runs": len(results), "best": results[0] if results else {}}, indent=2, default=str))
        return

