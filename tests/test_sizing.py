"""Tests for the position_size() pure function in financer.models.sizing.

Validates ATR-based sizing, regime adjustments, score clamping,
fallback calculations, and edge cases.
"""

import pytest

from financer.models.enums import Regime
from financer.models.sizing import (
    ATR_STOP_MULTIPLIER,
    CAUTIOUS_SIZE_MULT,
    FALLBACK_STOP_PCT,
    MAX_POSITION_BY_SCORE,
    RISK_BY_SCORE,
    check_entry_readiness,
    position_size,
)
from financer.models.risk import check_regime_allows_entry


class TestPositionSizeBasic:
    """Core sizing logic with ATR-based stops."""

    def test_known_values_score5(self):
        # price=100, atr=2, equity=100_000, RISK_ON, score=5
        # stop_distance = 2 * 1.5 = 3.0
        # risk_budget = 100_000 * 0.01 = 1_000
        # qty_by_risk = 1_000 / 3.0 = 333
        # qty_by_cap = 100_000 * 0.05 / 100 = 50
        # qty = min(333, 50) = 50
        result = position_size(price=100.0, atr=2.0, equity=100_000.0, score=5)
        assert result["qty"] == 50
        assert result["sl"] == pytest.approx(97.0)    # 100 - 3.0
        assert result["atr_used"] == 2.0

    def test_known_values_score8(self):
        # price=100, atr=2, equity=100_000, RISK_ON, score=8
        # stop_distance = 3.0
        # risk_budget = 100_000 * 0.025 = 2_500
        # qty_by_risk = 2_500 / 3.0 = 833
        # qty_by_cap = 100_000 * 0.10 / 100 = 100
        # qty = min(833, 100) = 100
        result = position_size(price=100.0, atr=2.0, equity=100_000.0, score=8)
        assert result["qty"] == 100
        assert result["sl"] == pytest.approx(97.0)

    def test_tp_levels(self):
        result = position_size(price=100.0, atr=2.0, equity=100_000.0, score=5)
        stop_dist = 2.0 * ATR_STOP_MULTIPLIER  # 3.0
        assert result["tp1"] == pytest.approx(100.0 + stop_dist * (2.0 / 1.5))
        assert result["tp2"] == pytest.approx(100.0 + stop_dist * (3.0 / 1.5))
        assert result["tp3"] == pytest.approx(100.0 + stop_dist * (4.0 / 1.5))

    def test_risk_per_share(self):
        result = position_size(price=100.0, atr=2.0, equity=100_000.0)
        assert result["risk_per_share"] == pytest.approx(3.0)  # 2.0 * 1.5


class TestRegimeAdjustments:
    """Regime-based position scaling."""

    def test_risk_on_full_size(self):
        result = position_size(
            price=100.0, atr=2.0, equity=100_000.0, regime=Regime.RISK_ON,
        )
        assert result["qty"] > 0

    def test_cautious_reduces_size(self):
        full = position_size(
            price=100.0, atr=2.0, equity=100_000.0, regime=Regime.RISK_ON, score=6,
        )
        cautious = position_size(
            price=100.0, atr=2.0, equity=100_000.0, regime=Regime.CAUTIOUS, score=6,
        )
        assert cautious["qty"] < full["qty"]
        assert cautious["qty"] == max(1, int(full["qty"] * CAUTIOUS_SIZE_MULT))

    def test_risk_off_zero_qty(self):
        result = position_size(
            price=100.0, atr=2.0, equity=100_000.0, regime=Regime.RISK_OFF,
        )
        assert result["qty"] == 0


class TestScoreClamping:
    """Scores outside 5–8 are clamped."""

    def test_score_below_min(self):
        low = position_size(price=100.0, atr=2.0, equity=100_000.0, score=3)
        baseline = position_size(price=100.0, atr=2.0, equity=100_000.0, score=5)
        assert low["qty"] == baseline["qty"]

    def test_score_above_max(self):
        high = position_size(price=100.0, atr=2.0, equity=100_000.0, score=10)
        baseline = position_size(price=100.0, atr=2.0, equity=100_000.0, score=8)
        assert high["qty"] == baseline["qty"]


class TestFallbackStop:
    """When ATR is None or zero, use FALLBACK_STOP_PCT."""

    def test_none_atr(self):
        result = position_size(price=100.0, atr=None, equity=100_000.0)
        expected_stop_dist = 100.0 * FALLBACK_STOP_PCT  # 5.0
        assert result["sl"] == pytest.approx(100.0 - expected_stop_dist)
        assert result["risk_per_share"] == pytest.approx(expected_stop_dist)
        assert result["atr_used"] is None

    def test_zero_atr(self):
        result = position_size(price=100.0, atr=0.0, equity=100_000.0)
        expected_stop_dist = 100.0 * FALLBACK_STOP_PCT
        assert result["sl"] == pytest.approx(100.0 - expected_stop_dist)


class TestEdgeCases:
    """Boundary and degenerate inputs."""

    def test_zero_price(self):
        result = position_size(price=0.0, atr=2.0, equity=100_000.0)
        assert result["qty"] == 0

    def test_zero_equity(self):
        result = position_size(price=100.0, atr=2.0, equity=0.0)
        assert result["qty"] == 0

    def test_negative_price(self):
        result = position_size(price=-10.0, atr=2.0, equity=100_000.0)
        assert result["qty"] == 0

    def test_very_high_atr(self):
        # ATR = 50 on a $100 stock → stop_distance = 75 → huge risk per share
        # risk_budget at score 5 = 1_000
        # qty_by_risk = 1_000 / 75 = 13
        # qty_by_cap = 5_000 / 100 = 50
        # qty = min(13, 50) = 13
        result = position_size(price=100.0, atr=50.0, equity=100_000.0, score=5)
        assert result["qty"] == 13

    def test_very_small_equity(self):
        result = position_size(price=100.0, atr=2.0, equity=500.0, score=5)
        # risk_budget = 500 * 0.01 = 5
        # qty_by_risk = 5 / 3 = 1
        # qty_by_cap = 500 * 0.05 / 100 = 0 → but min is 1
        assert result["qty"] >= 1


class TestConstantsIntegrity:
    """Verify constants match portfolio.py values."""

    def test_risk_scores_present(self):
        for s in [5, 6, 7, 8]:
            assert s in RISK_BY_SCORE
            assert s in MAX_POSITION_BY_SCORE

    def test_risk_increases_with_score(self):
        scores = sorted(RISK_BY_SCORE.keys())
        for i in range(len(scores) - 1):
            assert RISK_BY_SCORE[scores[i]] < RISK_BY_SCORE[scores[i + 1]]

    def test_position_cap_increases_with_score(self):
        scores = sorted(MAX_POSITION_BY_SCORE.keys())
        for i in range(len(scores) - 1):
            assert MAX_POSITION_BY_SCORE[scores[i]] < MAX_POSITION_BY_SCORE[scores[i + 1]]

    def test_atr_multiplier(self):
        assert ATR_STOP_MULTIPLIER == 1.5

    def test_fallback_stop(self):
        assert FALLBACK_STOP_PCT == 0.05

    def test_cautious_mult(self):
        assert CAUTIOUS_SIZE_MULT == 0.75


# ── Entry readiness ─────────────────────────────────────────────────────────


class TestEntryReadiness:
    """check_entry_readiness must block entries when required columns are NaN."""

    def test_all_present(self):
        row = {"atr_14": 2.5, "sma_50": 150.0, "above_50": True,
               "regime": "RISK_ON", "rs_20": 1.05}
        ready, missing = check_entry_readiness(row)
        assert ready is True
        assert missing == []

    def test_missing_atr(self):
        row = {"atr_14": float("nan"), "sma_50": 150.0, "above_50": True,
               "regime": "RISK_ON", "rs_20": 1.05}
        ready, missing = check_entry_readiness(row)
        assert ready is False
        assert "atr_14" in missing

    def test_none_value(self):
        row = {"atr_14": 2.5, "sma_50": None, "above_50": True,
               "regime": "RISK_ON", "rs_20": 1.05}
        ready, missing = check_entry_readiness(row)
        assert ready is False
        assert "sma_50" in missing

    def test_absent_key(self):
        row = {"atr_14": 2.5, "above_50": True, "regime": "RISK_ON", "rs_20": 1.05}
        ready, missing = check_entry_readiness(row)
        assert ready is False
        assert "sma_50" in missing

    def test_regime_string_accepted(self):
        row = {"atr_14": 2.5, "sma_50": 150.0, "above_50": True,
               "regime": "CAUTIOUS", "rs_20": 0.95}
        ready, _ = check_entry_readiness(row)
        assert ready is True

    def test_multiple_missing(self):
        row = {"above_50": True, "regime": "RISK_ON"}
        ready, missing = check_entry_readiness(row)
        assert ready is False
        assert len(missing) == 3  # atr_14, sma_50, rs_20


# ── Regime veto ──────────────────────────────────────────────────────────────


class TestRegimeVeto:
    """check_regime_allows_entry: fail-closed on unknown regime."""

    def test_risk_on_allowed(self):
        allowed, _ = check_regime_allows_entry(Regime.RISK_ON)
        assert allowed is True

    def test_cautious_allowed(self):
        allowed, _ = check_regime_allows_entry(Regime.CAUTIOUS)
        assert allowed is True

    def test_risk_off_blocked(self):
        allowed, reason = check_regime_allows_entry(Regime.RISK_OFF)
        assert allowed is False
        assert "risk_off" in reason

    def test_none_blocked(self):
        allowed, reason = check_regime_allows_entry(None)
        assert allowed is False
        assert "unknown" in reason

    def test_invalid_string_blocked(self):
        allowed, reason = check_regime_allows_entry("BANANA")
        assert allowed is False
        assert "invalid" in reason

    def test_string_risk_on_allowed(self):
        allowed, _ = check_regime_allows_entry("RISK_ON")
        assert allowed is True

    def test_string_risk_off_blocked(self):
        allowed, reason = check_regime_allows_entry("RISK_OFF")
        assert allowed is False
