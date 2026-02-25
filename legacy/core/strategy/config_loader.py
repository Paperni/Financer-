"""
Runtime configuration loader for strategy and risk controls.

Supports:
- base config (configs/strategy/default.yaml)
- optional profile overlay (configs/profiles/<name>.yaml)
- optional explicit config file
- CLI overrides in dotted key form: risk.max_positions_per_sector=4
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _coerce_value(raw: str) -> Any:
    v = raw.strip()
    low = v.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _set_dotted(config: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        return
    curr = config
    for key in parts[:-1]:
        if key not in curr or not isinstance(curr[key], dict):
            curr[key] = {}
        curr = curr[key]
    curr[parts[-1]] = value


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        # Keep runtime safe even if yaml dependency is missing.
        # Defaults still apply from default_runtime_config().
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config at {path} must be a mapping/dict")
    return data


def default_runtime_config() -> dict[str, Any]:
    return {
        "capital": {
            "initial_capital": 100000.0,
        },
        "risk": {
            "max_positions_per_sector": 3,
            "daily_loss_halt_pct": 0.03,
            "max_open_risk_pct_of_equity": 0.10,
            "max_new_position_risk_pct_of_equity": 0.025,
            "max_position_notional_pct": 0.10,
        },
        "features": {
            "news_enabled": True,
            "earnings_enabled": True,
        },
    }


def load_runtime_config(
    config_path: str | None = None,
    profile: str | None = None,
    overrides: list[str] | None = None,
) -> dict[str, Any]:
    """
    Load runtime configuration with precedence:
      defaults < configs/strategy/default.yaml < profile < explicit config_path < overrides
    """
    root = _repo_root()
    cfg = default_runtime_config()

    base_path = root / "configs" / "strategy" / "default.yaml"
    cfg = _deep_merge(cfg, _load_yaml_file(base_path))

    if profile:
        profile_path = root / "configs" / "profiles" / f"{profile}.yaml"
        cfg = _deep_merge(cfg, _load_yaml_file(profile_path))

    if config_path:
        explicit = Path(config_path)
        if not explicit.is_absolute():
            explicit = root / explicit
        cfg = _deep_merge(cfg, _load_yaml_file(explicit))

    for ov in overrides or []:
        if "=" not in ov:
            continue
        key, raw_value = ov.split("=", 1)
        _set_dotted(cfg, key.strip(), _coerce_value(raw_value))

    return cfg
