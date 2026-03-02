from __future__ import annotations

from datetime import datetime, timezone

from financer.intelligence.models import ControlPlan, MarketState, PolicyOverrides
from financer.models.enums import Regime


def test_controlplan_backward_compatibility():
    """Ensure legacy flat property access still proxies exactly to the nested sub-models."""
    ts = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    
    plan = ControlPlan(
        state=MarketState(
            regime=Regime.CAUTIOUS,
            regime_score=1.5,
            regime_confidence=0.5,
            narrative="Test narrative",
            computed_at=ts,
            schema_version="v1",
            features_used=["spy_sma50"],
            source="test_source"
        ),
        policy=PolicyOverrides(
            max_positions=4,
            position_size_multiplier=0.5,
            scorecard_threshold=6.0
        )
    )
    
    # Assert all proxy properties match exactly
    assert plan.as_of == ts
    assert plan.regime == Regime.CAUTIOUS
    assert plan.regime_score == 1.5
    assert plan.regime_confidence == 0.5
    assert plan.narrative == "Test narrative"
    
    assert plan.max_positions == 4
    assert plan.position_size_multiplier == 0.5
    assert plan.scorecard_threshold == 6.0


def test_controlplan_schema_requirements():
    """Ensure the MarketState sub-model carries the exact required metadata fields."""
    plan = ControlPlan()
    
    # Ensure UTC timezone awareness on default factory
    assert plan.state.computed_at.tzinfo == timezone.utc
    assert plan.as_of.tzinfo == timezone.utc
    
    # Contract requirements
    assert plan.state.schema_version == "v1"
    assert isinstance(plan.state.features_used, list)
    assert hasattr(plan.state, "source")


def test_controlplan_placeholder_nullification():
    """Ensure future intelligence fields default cleanly to None so downstream code must check them."""
    plan = ControlPlan()
    
    assert plan.event_risk is None
    assert plan.next_event is None
    assert plan.hours_to_event is None
    
    assert plan.sentiment_score is None
    assert plan.sentiment_label is None
    
    assert plan.tier1_sectors is None
    assert plan.tier2_sectors is None
    assert plan.tier3_sectors is None
    assert plan.sector_scores is None
    assert plan.allowed_sectors is None
