from __future__ import annotations

from datetime import datetime, timezone

import pytest

from financer.models.enums import Regime
from financer.intelligence.models import ControlPlan, MarketState, PolicyOverrides, neutral_plan


class TestControlPlan:
    def test_default_construction(self):
        plan = ControlPlan()
        assert plan.regime == Regime.RISK_ON
        assert plan.max_positions == 10
        assert plan.position_size_multiplier == 1.0
        assert plan.scorecard_threshold == 5
        assert plan.event_risk is None

    def test_uses_existing_regime_enum(self):
        """ControlPlan must use financer.models.enums.Regime, not a new one."""
        plan = ControlPlan(state=MarketState(regime=Regime.CAUTIOUS))
        assert plan.regime == Regime.CAUTIOUS
        assert plan.regime.value == "CAUTIOUS"

    def test_risk_off_via_existing_enum(self):
        plan = ControlPlan(
            state=MarketState(regime=Regime.RISK_OFF),
            policy=PolicyOverrides(max_positions=0)
        )
        assert plan.regime == Regime.RISK_OFF
        assert plan.max_positions == 0

    def test_json_round_trip(self):
        plan = ControlPlan(
            state=MarketState(regime=Regime.CAUTIOUS, regime_score=0.5),
            policy=PolicyOverrides(max_positions=4),
            tier1_sectors=["XLK", "XLI"],
        )
        data = plan.model_dump(mode="json")
        restored = ControlPlan.model_validate(data)
        assert restored.regime == Regime.CAUTIOUS
        assert restored.max_positions == 4
        assert restored.tier1_sectors == ["XLK", "XLI"]

    def test_str_output(self):
        plan = ControlPlan(
            state=MarketState(
                regime=Regime.CAUTIOUS,
                regime_score=0.8,
                regime_confidence=0.2,
                narrative="Caution required"
            ),
            policy=PolicyOverrides(
                max_positions=4,
                position_size_multiplier=0.5,
                scorecard_threshold=6
            )
        )
        text = str(plan)
        assert "CAUTIOUS" in text
        assert "Caution required" in text
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
        assert plan.event_risk is None
        assert plan.sentiment_score is None

    def test_accepts_custom_timestamp(self):
        ts = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
        plan = neutral_plan(as_of=ts)
        assert plan.as_of == ts

    def test_narrative_indicates_disabled(self):
        plan = neutral_plan()
        assert "disabled" in plan.narrative.lower() or "unavailable" in plan.narrative.lower()
