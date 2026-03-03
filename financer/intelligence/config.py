"""Intelligence configuration — loads from configs/intelligence.yml.

All thresholds live in YAML; nothing is hardcoded in logic modules.
If the YAML file is missing or malformed, returns safe defaults.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Default YAML location (relative to project root) ────────────────────────
_DEFAULT_CONFIG_PATH = Path("configs/intelligence.yml")


# ── Dataclasses (one per intelligence module) ────────────────────────────────

@dataclass(frozen=True)
class RegimeConfig:
    """Parameters for the market regime classifier."""

    spy_ticker: str = "SPY"
    sma_long: int = 200
    sma_short: int = 50
    slope_lookback: int = 10
    breadth_sma_period: int = 50
    breadth_bullish: float = 0.65
    breadth_bearish: float = 0.40
    vix_ticker: str = "^VIX"
    vix_normal_low: float = 18.0
    vix_normal_high: float = 25.0
    vix_crisis: float = 35.0
    yield_curve_series: str = "T10Y2Y"
    risk_on_threshold: float = 2.0
    risk_off_threshold: float = 0.0
    confirmation_days: int = 2
    # v1 price-based signals
    sma200_slope_lookback: int = 20
    sma200_slope_threshold: float = 0.0
    atr_vol_threshold: float = 0.03
    vol_shock_lookback: int = 5
    vol_shock_cautious_threshold: float = 0.035
    vol_shock_risk_off_threshold: float = 0.045


@dataclass(frozen=True)
class RegimeParamsConfig:
    """Per-regime trading parameter overrides (decision matrix)."""

    risk_on_max_positions: int = 12
    risk_on_size_mult: float = 1.0
    risk_on_threshold: float = 4.0
    cautious_max_positions: int = 6
    cautious_size_mult: float = 0.75
    cautious_threshold: float = 5.0
    risk_off_max_positions: int = 0
    risk_off_size_mult: float = 0.0
    risk_off_threshold: float = 6.0


@dataclass(frozen=True)
class RotationConfig:
    """Parameters for the sector rotation ranker."""

    weight_1m: float = 0.40
    weight_3m: float = 0.35
    weight_6m: float = 0.25
    overweight_count: int = 3
    underweight_count: int = 4
    benchmark_ticker: str = "SPY"


@dataclass(frozen=True)
class ConvictionConfig:
    """Parameters for the conviction-based position sizer."""

    base_risk_pct: float = 0.01
    max_multiplier: float = 2.0
    min_multiplier: float = 0.25
    tier1_bonus: float = 0.25
    tier3_penalty: float = -0.25
    score6_bonus: float = 0.25
    top_rs_bonus: float = 0.25
    top_rs_percentile: float = 0.20


@dataclass(frozen=True)
class EventsConfig:
    """Parameters for the macro event risk calendar."""

    high_impact_buffer_hours: float = 24.0
    caution_buffer_hours: float = 48.0


@dataclass(frozen=True)
class IntelligenceConfig:
    """Top-level intelligence configuration."""

    enabled: bool = True
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    regime_params: RegimeParamsConfig = field(default_factory=RegimeParamsConfig)
    rotation: RotationConfig = field(default_factory=RotationConfig)
    conviction: ConvictionConfig = field(default_factory=ConvictionConfig)
    events: EventsConfig = field(default_factory=EventsConfig)


# ── YAML loading ─────────────────────────────────────────────────────────────

def _build_section(cls: type, raw: dict[str, Any]) -> Any:
    """Instantiate a frozen dataclass from a raw dict, ignoring unknown keys."""
    valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in valid_keys}
    return cls(**filtered)


def load_config(path: Path | str | None = None) -> IntelligenceConfig:
    """Load intelligence configuration from a YAML file.

    Falls back to defaults if the file is missing or malformed.
    Never raises — logs a warning and returns safe defaults.

    Parameters
    ----------
    path : Path or str, optional
        Path to the YAML file.  Defaults to ``configs/intelligence.yml``
        relative to the current working directory.

    Returns
    -------
    IntelligenceConfig
        Frozen dataclass with all intelligence parameters.
    """
    resolved = Path(path) if path else _DEFAULT_CONFIG_PATH

    if not resolved.exists():
        logger.warning("Intelligence config not found at %s; using defaults", resolved)
        return IntelligenceConfig()

    try:
        import yaml  # noqa: PLC0415

        raw: dict[str, Any] = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("Failed to parse %s; using defaults", resolved, exc_info=True)
        return IntelligenceConfig()

    enabled = raw.get("intelligence", {}).get("enabled", True)

    regime = _build_section(RegimeConfig, raw.get("regime", {}))
    regime_params = _build_section(RegimeParamsConfig, raw.get("regime_params", {}))
    rotation = _build_section(RotationConfig, raw.get("rotation", {}))
    conviction = _build_section(ConvictionConfig, raw.get("conviction", {}))
    events = _build_section(EventsConfig, raw.get("events", {}))

    return IntelligenceConfig(
        enabled=enabled,
        regime=regime,
        regime_params=regime_params,
        rotation=rotation,
        conviction=conviction,
        events=events,
    )
