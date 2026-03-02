"""Integration tests — ControlPlan wired through orchestrator and governor.

Verifies that passing control_plan=None preserves backward compatibility,
and that ControlPlan values actually affect sizing and position limits.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from financer.core.governor import RiskGovernor
from financer.core.orchestrator import CIOOrchestrator
from financer.models.enums import (
    Conviction,
    Direction,
    EngineSource,
    OrderStatus,
    Regime,
    TimeHorizon,
)
from financer.models.actions import Order
from financer.models.intents import ReasonCode, TradeIntent
from financer.models.portfolio import PortfolioSnapshot, PositionState
from financer.models.risk import RiskState
from financer.intelligence.models import ControlPlan


def _buy_intent(ticker: str = "AAPL", price: float = 150.0) -> TradeIntent:
    return TradeIntent(
        ticker=ticker,
        direction=Direction.BUY,
        conviction=Conviction.HIGH,
        time_horizon=TimeHorizon.SWING,
        source=EngineSource.SWING,
        reasons=[ReasonCode(code="TEST")],
        stop_price=price * 0.95,
        target_price=price * 1.10,
        meta={"latest_price": price, "atr_14": price * 0.02},
    )


# ── Backward compatibility ───────────────────────────────────────────────────

class TestBackwardCompat:
    def test_orchestrator_no_control_plan(self):
        """formulate_plan works identically without control_plan."""
        orch = CIOOrchestrator()
        intent = _buy_intent()
        portfolio = PortfolioSnapshot(cash=100_000, positions=[])
        risk_state = RiskState(regime=Regime.RISK_ON)
        plan = orch.formulate_plan([intent], [], portfolio, risk_state)
        assert len(plan.orders) == 1
        assert plan.orders[0].status == OrderStatus.APPROVED

    def test_governor_no_control_plan(self):
        """evaluate_order works identically without control_plan."""
        gov = RiskGovernor(max_positions=20)
        order = Order(
            ticker="AAPL", direction=Direction.BUY, qty=10, price=150.0,
            source_engine=EngineSource.SWING, reason_codes=[],
        )
        state = RiskState(open_risk_pct=0.05)
        portfolio = PortfolioSnapshot(cash=100_000, positions=[])
        order, veto = gov.evaluate_order(order, state, portfolio)
        assert not veto.vetoed


# ── ControlPlan sizing multiplier ────────────────────────────────────────────

class TestControlPlanSizing:
    def test_size_multiplier_reduces_qty(self):
        """position_size_multiplier < 1.0 should reduce order qty."""
        orch = CIOOrchestrator()
        intent = _buy_intent(price=100.0)
        portfolio = PortfolioSnapshot(cash=100_000, positions=[])
        risk_state = RiskState(regime=Regime.RISK_ON)

        # Baseline without control_plan
        plan_base = orch.formulate_plan([intent], [], portfolio, risk_state)
        qty_base = plan_base.orders[0].qty

        # With 50% multiplier
        cp = ControlPlan(position_size_multiplier=0.50, max_positions=20)
        intent2 = _buy_intent(price=100.0)
        plan_half = orch.formulate_plan([intent2], [], portfolio, risk_state, control_plan=cp)
        qty_half = plan_half.orders[0].qty

        assert qty_half < qty_base
        assert qty_half == int(qty_base * 0.50)

    def test_size_multiplier_zero_blocks(self):
        """position_size_multiplier=0.0 should produce qty=0 and skip order."""
        orch = CIOOrchestrator()
        intent = _buy_intent(price=100.0)
        portfolio = PortfolioSnapshot(cash=100_000, positions=[])
        risk_state = RiskState(regime=Regime.RISK_ON)

        cp = ControlPlan(position_size_multiplier=0.0, max_positions=0)
        plan = orch.formulate_plan([intent], [], portfolio, risk_state, control_plan=cp)
        # All BUY orders should be skipped (qty=0)
        buy_orders = [o for o in plan.orders if o.direction == Direction.BUY]
        assert len(buy_orders) == 0

    def test_size_multiplier_1_no_change(self):
        """position_size_multiplier=1.0 should not alter qty."""
        orch = CIOOrchestrator()
        intent = _buy_intent(price=100.0)
        portfolio = PortfolioSnapshot(cash=100_000, positions=[])
        risk_state = RiskState(regime=Regime.RISK_ON)

        plan_base = orch.formulate_plan([intent], [], portfolio, risk_state)
        qty_base = plan_base.orders[0].qty

        cp = ControlPlan(position_size_multiplier=1.0, max_positions=20)
        intent2 = _buy_intent(price=100.0)
        plan_cp = orch.formulate_plan([intent2], [], portfolio, risk_state, control_plan=cp)
        # multiplier=1.0 path: int(qty * 1.0) == qty
        assert plan_cp.orders[0].qty == qty_base


# ── ControlPlan max_positions ────────────────────────────────────────────────

class TestControlPlanMaxPositions:
    def test_governor_clamps_max_positions(self):
        """control_plan.max_positions=2 with 3 open positions -> veto."""
        gov = RiskGovernor(max_positions=20)
        positions = [
            PositionState(
                ticker=t, qty=10, entry_price=100.0, current_price=105.0,
                stop_loss=95.0, source=EngineSource.SWING,
                opened_at=datetime.now(timezone.utc),
            )
            for t in ["AAPL", "MSFT", "GOOGL"]
        ]
        portfolio = PortfolioSnapshot(cash=70_000, positions=positions)
        state = RiskState(open_risk_pct=0.05)

        order = Order(
            ticker="TSLA", direction=Direction.BUY, qty=10, price=200.0,
            stop_loss=190.0, source_engine=EngineSource.SWING, reason_codes=[],
        )

        # Without control_plan: 3 < 20, should pass
        _, veto_no_cp = gov.evaluate_order(order, state, portfolio)
        assert not veto_no_cp.vetoed

        # With control_plan max_positions=2: 3 >= 2, should veto
        cp = ControlPlan(max_positions=2)
        order2 = Order(
            ticker="TSLA", direction=Direction.BUY, qty=10, price=200.0,
            stop_loss=190.0, source_engine=EngineSource.SWING, reason_codes=[],
        )
        _, veto_cp = gov.evaluate_order(order2, state, portfolio, control_plan=cp)
        assert veto_cp.vetoed
        assert "max_positions_reached" in veto_cp.reason

    def test_governor_allows_under_cp_limit(self):
        """control_plan.max_positions=5 with 2 open -> allow."""
        gov = RiskGovernor(max_positions=20)
        positions = [
            PositionState(
                ticker=t, qty=10, entry_price=100.0, current_price=105.0,
                stop_loss=95.0, source=EngineSource.SWING,
                opened_at=datetime.now(timezone.utc),
            )
            for t in ["AAPL", "MSFT"]
        ]
        portfolio = PortfolioSnapshot(cash=80_000, positions=positions)
        state = RiskState(open_risk_pct=0.03)

        cp = ControlPlan(max_positions=5)
        order = Order(
            ticker="TSLA", direction=Direction.BUY, qty=10, price=200.0,
            stop_loss=190.0, source_engine=EngineSource.SWING, reason_codes=[],
        )
        _, veto = gov.evaluate_order(order, state, portfolio, control_plan=cp)
        assert not veto.vetoed


# ── Engine score override ────────────────────────────────────────────────────

class TestEngineScoreOverride:
    def test_min_entry_score_is_mutable(self):
        """SwingEngine.min_entry_score can be overridden per-cycle."""
        from financer.engines.swing.engine import SwingEngine

        engine = SwingEngine(min_entry_score=4.0)
        assert engine.min_entry_score == 4.0

        engine.min_entry_score = 6.0
        assert engine.min_entry_score == 6.0

        engine.min_entry_score = 4.0  # restore
        assert engine.min_entry_score == 4.0
