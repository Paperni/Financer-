"""Tests for financer.intelligence.models — ControlPlan and neutral_plan.

Validates serialization, defaults, and the neutral factory.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from financer.models.enums import Regime
from financer.intelligence.models import ControlPlan, neutral_plan


class TestControlPlan:
    def test_default_construction(self):
        plan = ControlPlan()
        assert plan.regime == Regime.RISK_ON
        assert plan.max_positions == 10
        assert plan.position_size_multiplier == 1.0
        assert plan.scorecard_threshold == 5
        assert plan.event_risk == "CLEAR"

    def test_uses_existing_regime_enum(self):
        """ControlPlan must use financer.models.enums.Regime, not a new one."""
        plan = ControlPlan(regime=Regime.CAUTIOUS)
        assert plan.regime == Regime.CAUTIOUS
        assert plan.regime.value == "CAUTIOUS"

    def test_risk_off_via_existing_enum(self):
        plan = ControlPlan(regime=Regime.RISK_OFF, max_positions=0)
        assert plan.regime == Regime.RISK_OFF
        assert plan.max_positions == 0

    def test_json_round_trip(self):
        plan = ControlPlan(
            regime=Regime.CAUTIOUS,
            regime_score=0.5,
            max_positions=4,
            tier1_sectors=["XLK", "XLI"],
        )
        data = plan.model_dump(mode="json")
        restored = ControlPlan.model_validate(data)
        assert restored.regime == Regime.CAUTIOUS
        assert restored.max_positions == 4
        assert restored.tier1_sectors == ["XLK", "XLI"]

    def test_str_output(self):
        plan = ControlPlan(
            regime=Regime.CAUTIOUS,
            regime_score=0.8,
            regime_confidence=0.2,
            event_risk="CAUTION",
            next_event="NFP",
            hours_to_event=48.0,
            tier1_sectors=["XLE"],
            tier3_sectors=["XLV", "XLRE"],
            max_positions=4,
            position_size_multiplier=0.5,
            scorecard_threshold=6,
            allowed_sectors=["XLE", "XLK", "XLI"],
        )
        text = str(plan)
        assert "CAUTIOUS" in text
        assert "CAUTION" in text
        assert "NFP" in text
        assert "4" in text


class TestNeutralPlan:
    def test_returns_control_plan(self):
        plan = neutral_plan()
        assert isinstance(plan, ControlPlan)

    def test_neutral_defaults(self):
        plan = neutral_plan()
        assert plan.regime == Regime.RISK_ON
        assert plan.max_positions == 10
        assert plan.position_size_multiplier == 1.0
        assert plan.scorecard_threshold == 5
        assert plan.event_risk == "CLEAR"
        assert plan.sentiment_score == 0.0

    def test_accepts_custom_timestamp(self):
        ts = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
        plan = neutral_plan(as_of=ts)
        assert plan.as_of == ts

    def test_narrative_indicates_disabled(self):
        plan = neutral_plan()
        assert "disabled" in plan.narrative.lower() or "unavailable" in plan.narrative.lower()
