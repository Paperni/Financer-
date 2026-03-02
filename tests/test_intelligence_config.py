"""Tests for financer.intelligence.config — YAML loading and defaults.

Zero network calls.  Uses tmp_path fixtures for YAML I/O.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from financer.intelligence.config import (
    ConvictionConfig,
    EventsConfig,
    IntelligenceConfig,
    RegimeConfig,
    RotationConfig,
    load_config,
)


# ── Default construction ────────────────────────────────────────────────────

class TestDefaults:
    def test_default_config_is_valid(self):
        cfg = IntelligenceConfig()
        assert cfg.enabled is True
        assert isinstance(cfg.regime, RegimeConfig)
        assert isinstance(cfg.rotation, RotationConfig)
        assert isinstance(cfg.conviction, ConvictionConfig)
        assert isinstance(cfg.events, EventsConfig)

    def test_regime_defaults(self):
        r = RegimeConfig()
        assert r.spy_ticker == "SPY"
        assert r.sma_long == 200
        assert r.sma_short == 50
        assert r.vix_crisis == 35.0
        assert r.confirmation_days == 2

    def test_rotation_defaults(self):
        r = RotationConfig()
        assert r.weight_1m + r.weight_3m + r.weight_6m == pytest.approx(1.0)
        assert r.overweight_count == 3
        assert r.underweight_count == 4

    def test_conviction_defaults(self):
        c = ConvictionConfig()
        assert c.min_multiplier == 0.25
        assert c.max_multiplier == 2.0

    def test_events_defaults(self):
        e = EventsConfig()
        assert e.high_impact_buffer_hours == 24.0

    def test_frozen_dataclass(self):
        r = RegimeConfig()
        with pytest.raises(AttributeError):
            r.sma_long = 100  # type: ignore[misc]


# ── YAML loading ─────────────────────────────────────────────────────────────

_MINIMAL_YAML = """\
intelligence:
  enabled: true

regime:
  vix_crisis: 40.0
  confirmation_days: 3

rotation:
  weight_1m: 0.50
  weight_3m: 0.30
  weight_6m: 0.20
"""

_DISABLED_YAML = """\
intelligence:
  enabled: false
"""


class TestLoadConfig:
    def test_load_from_file(self, tmp_path: Path):
        yml = tmp_path / "intelligence.yml"
        yml.write_text(_MINIMAL_YAML, encoding="utf-8")

        cfg = load_config(yml)
        assert cfg.enabled is True
        assert cfg.regime.vix_crisis == 40.0
        assert cfg.regime.confirmation_days == 3
        assert cfg.rotation.weight_1m == 0.50
        # Unspecified fields keep defaults
        assert cfg.regime.spy_ticker == "SPY"
        assert cfg.conviction.max_multiplier == 2.0

    def test_disabled_flag(self, tmp_path: Path):
        yml = tmp_path / "intelligence.yml"
        yml.write_text(_DISABLED_YAML, encoding="utf-8")

        cfg = load_config(yml)
        assert cfg.enabled is False

    def test_missing_file_returns_defaults(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.yml")
        assert cfg.enabled is True
        assert cfg.regime.sma_long == 200

    def test_empty_file_returns_defaults(self, tmp_path: Path):
        yml = tmp_path / "empty.yml"
        yml.write_text("", encoding="utf-8")

        cfg = load_config(yml)
        assert cfg.enabled is True

    def test_malformed_yaml_returns_defaults(self, tmp_path: Path):
        yml = tmp_path / "bad.yml"
        yml.write_text("{{{{not yaml at all", encoding="utf-8")

        cfg = load_config(yml)
        assert cfg.enabled is True

    def test_extra_keys_ignored(self, tmp_path: Path):
        yml = tmp_path / "extra.yml"
        yml.write_text(
            "intelligence:\n  enabled: true\nregime:\n  unknown_key: 99\n",
            encoding="utf-8",
        )
        cfg = load_config(yml)
        assert cfg.regime.spy_ticker == "SPY"  # unknown_key silently dropped

    def test_loads_real_config(self):
        """Smoke test: load the actual configs/intelligence.yml if present."""
        real = Path("configs/intelligence.yml")
        if not real.exists():
            pytest.skip("configs/intelligence.yml not found")
        cfg = load_config(real)
        assert cfg.enabled is True
        assert cfg.regime.vix_crisis == 35.0
