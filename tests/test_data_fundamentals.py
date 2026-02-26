"""Tests for financer.data.fundamentals — PEG proxy and quality flags.

All tests use fixture data.  Zero network calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from financer.data.fundamentals import get_valuation_inputs

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_provider(fixture_path: Path):
    """Return a provider that reads a local JSON fixture."""
    data = json.loads(fixture_path.read_text())
    def provider(ticker: str) -> dict:
        return data
    return provider


def _dict_provider(d: dict):
    """Return a provider that returns a fixed dict."""
    def provider(ticker: str) -> dict:
        return d
    return provider


class TestValuationSchema:
    def test_all_keys_present(self):
        result = get_valuation_inputs(
            "AAPL",
            provider=_fixture_provider(FIXTURES / "AAPL_valuation.json"),
        )
        assert "ticker" in result
        assert "pe_ttm" in result
        assert "pe_forward" in result
        assert "pe_used" in result
        assert "revenue_growth_pct" in result
        assert "peg_proxy" in result
        assert "quality_flags" in result

    def test_quality_flags_keys(self):
        result = get_valuation_inputs(
            "AAPL",
            provider=_fixture_provider(FIXTURES / "AAPL_valuation.json"),
        )
        flags = result["quality_flags"]
        assert "missing_pe" in flags
        assert "missing_growth" in flags
        assert "negative_earnings" in flags
        assert "outlier_growth" in flags


class TestPEGProxy:
    def test_peg_calculation(self):
        # pe_forward=25.0, growth=25% → peg=1.0
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 25.0, "trailingPE": 30.0, "revenueGrowth": 0.25}),
        )
        assert result["peg_proxy"] == pytest.approx(1.0)

    def test_fixture_peg(self):
        # fixture: forwardPE=25.2, growth=0.08 → 8% → peg=25.2/8.0=3.15
        result = get_valuation_inputs(
            "AAPL",
            provider=_fixture_provider(FIXTURES / "AAPL_valuation.json"),
        )
        assert result["peg_proxy"] == pytest.approx(25.2 / 8.0, abs=0.01)

    def test_peg_none_when_growth_zero(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 20.0, "revenueGrowth": 0.0}),
        )
        assert result["peg_proxy"] is None

    def test_peg_none_when_growth_negative(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 20.0, "revenueGrowth": -0.10}),
        )
        assert result["peg_proxy"] is None


class TestPEPreference:
    def test_forward_pe_preferred(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 22.0, "trailingPE": 28.0, "revenueGrowth": 0.10}),
        )
        assert result["pe_used"] == 22.0

    def test_falls_back_to_trailing(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"trailingPE": 28.0, "revenueGrowth": 0.10}),
        )
        assert result["pe_used"] == 28.0

    def test_both_none(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"revenueGrowth": 0.10}),
        )
        assert result["pe_used"] is None


class TestQualityFlags:
    def test_missing_pe(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"revenueGrowth": 0.10}),
        )
        assert result["quality_flags"]["missing_pe"] is True

    def test_not_missing_pe_when_trailing_exists(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"trailingPE": 20.0}),
        )
        assert result["quality_flags"]["missing_pe"] is False

    def test_missing_growth(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 20.0}),
        )
        assert result["quality_flags"]["missing_growth"] is True

    def test_negative_earnings(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": -5.0, "revenueGrowth": 0.10}),
        )
        assert result["quality_flags"]["negative_earnings"] is True

    def test_not_negative_when_positive(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 20.0, "revenueGrowth": 0.10}),
        )
        assert result["quality_flags"]["negative_earnings"] is False

    def test_outlier_growth_high(self):
        # 150% growth = outlier
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 20.0, "revenueGrowth": 1.50}),
        )
        assert result["quality_flags"]["outlier_growth"] is True

    def test_outlier_growth_low(self):
        # -60% growth = outlier
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 20.0, "revenueGrowth": -0.60}),
        )
        assert result["quality_flags"]["outlier_growth"] is True

    def test_normal_growth_not_outlier(self):
        result = get_valuation_inputs(
            "TEST",
            provider=_dict_provider({"forwardPE": 20.0, "revenueGrowth": 0.25}),
        )
        assert result["quality_flags"]["outlier_growth"] is False


class TestErrorHandling:
    def test_provider_exception_returns_safe_defaults(self):
        def boom(ticker):
            raise RuntimeError("API down")
        result = get_valuation_inputs("TEST", provider=boom)
        assert result["ticker"] == "TEST"
        assert result["pe_used"] is None
        assert result["peg_proxy"] is None
        assert result["quality_flags"]["missing_pe"] is True
