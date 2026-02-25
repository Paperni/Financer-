"""Tests for Financer Brain core Pydantic models.

Validates instantiation, serialization round-trips, computed properties,
and enum constraints for every model in financer.models.
"""

from datetime import datetime, timezone

import pytest

from financer.models import (
    ActionPlan,
    AllocationIntent,
    Conviction,
    Direction,
    EngineSource,
    EventFlags,
    Order,
    OrderStatus,
    PortfolioSnapshot,
    PositionState,
    ReasonCode,
    Regime,
    RiskState,
    RiskVeto,
    TimeHorizon,
    TradeIntent,
)


# ── ReasonCode ───────────────────────────────────────────────────────────────


class TestReasonCode:
    def test_minimal(self):
        rc = ReasonCode(code="STRONG_MOAT")
        assert rc.code == "STRONG_MOAT"
        assert rc.weight == 1.0
        assert rc.detail == ""

    def test_full(self):
        rc = ReasonCode(code="RSI_OVERSOLD", weight=0.8, detail="RSI at 25")
        assert rc.weight == 0.8
        assert rc.detail == "RSI at 25"


# ── TradeIntent ──────────────────────────────────────────────────────────────


class TestTradeIntent:
    def _make(self, **overrides):
        defaults = dict(
            ticker="AAPL",
            direction=Direction.BUY,
            conviction=Conviction.HIGH,
            time_horizon=TimeHorizon.SWING,
            source=EngineSource.SWING,
            reasons=[ReasonCode(code="TEST")],
        )
        defaults.update(overrides)
        return TradeIntent(**defaults)

    def test_minimal(self):
        intent = self._make()
        assert intent.ticker == "AAPL"
        assert intent.direction == Direction.BUY
        assert intent.suggested_weight_pct is None
        assert intent.stop_price is None
        assert isinstance(intent.created_at, datetime)

    def test_full_fields(self):
        intent = self._make(
            suggested_weight_pct=5.0,
            stop_price=140.0,
            target_price=180.0,
            meta={"phase_score": 8},
        )
        assert intent.suggested_weight_pct == 5.0
        assert intent.meta["phase_score"] == 8

    def test_round_trip(self):
        intent = self._make()
        d = intent.model_dump()
        restored = TradeIntent(**d)
        assert restored.ticker == intent.ticker
        assert restored.direction == intent.direction
        assert restored.conviction == intent.conviction

    def test_json_round_trip(self):
        intent = self._make()
        json_str = intent.model_dump_json()
        restored = TradeIntent.model_validate_json(json_str)
        assert restored.ticker == intent.ticker

    def test_invalid_direction_rejected(self):
        with pytest.raises(Exception):
            self._make(direction="INVALID")


# ── AllocationIntent ─────────────────────────────────────────────────────────


class TestAllocationIntent:
    def test_create(self):
        ai = AllocationIntent(
            source=EngineSource.SWING,
            cash_pct=10.0,
            baseline_pct=50.0,
            swing_pct=40.0,
            regime=Regime.RISK_ON,
            reasons=[ReasonCode(code="BULL_MARKET")],
        )
        assert ai.cash_pct == 10.0
        assert ai.regime == Regime.RISK_ON


# ── Order ────────────────────────────────────────────────────────────────────


class TestOrder:
    def test_minimal(self):
        order = Order(
            ticker="MSFT",
            direction=Direction.BUY,
            qty=10,
            price=400.0,
            source_engine=EngineSource.LONG_TERM,
            reason_codes=["STRONG_MOAT", "HIGH_ROIC"],
        )
        assert order.qty == 10
        assert order.status == OrderStatus.PROPOSED
        assert len(order.order_id) == 12

    def test_unique_ids(self):
        o1 = Order(
            ticker="A", direction=Direction.BUY, qty=1, price=1.0,
            source_engine=EngineSource.SWING, reason_codes=["X"],
        )
        o2 = Order(
            ticker="A", direction=Direction.BUY, qty=1, price=1.0,
            source_engine=EngineSource.SWING, reason_codes=["X"],
        )
        assert o1.order_id != o2.order_id


# ── ActionPlan ───────────────────────────────────────────────────────────────


class TestActionPlan:
    def test_empty(self):
        plan = ActionPlan()
        assert plan.orders == []
        assert plan.allocation_shifts == {}
        assert len(plan.plan_id) == 12

    def test_with_orders(self):
        order = Order(
            ticker="NVDA", direction=Direction.BUY, qty=5, price=800.0,
            source_engine=EngineSource.SWING, reason_codes=["MOMENTUM"],
        )
        plan = ActionPlan(orders=[order], rationale="Momentum breakout")
        assert len(plan.orders) == 1
        assert plan.rationale == "Momentum breakout"


# ── PositionState ────────────────────────────────────────────────────────────


class TestPositionState:
    def _make(self, **overrides):
        defaults = dict(
            ticker="AAPL",
            qty=10,
            entry_price=150.0,
            current_price=160.0,
            source=EngineSource.SWING,
            opened_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return PositionState(**defaults)

    def test_unrealized_pnl(self):
        pos = self._make(entry_price=150.0, current_price=160.0, qty=10)
        assert pos.unrealized_pnl == pytest.approx(100.0)

    def test_unrealized_pnl_loss(self):
        pos = self._make(entry_price=150.0, current_price=140.0, qty=10)
        assert pos.unrealized_pnl == pytest.approx(-100.0)

    def test_market_value(self):
        pos = self._make(current_price=160.0, qty=10)
        assert pos.market_value == pytest.approx(1600.0)

    def test_zero_qty(self):
        pos = self._make(qty=0, current_price=100.0)
        assert pos.market_value == 0.0
        assert pos.unrealized_pnl == 0.0


# ── PortfolioSnapshot ────────────────────────────────────────────────────────


class TestPortfolioSnapshot:
    def test_equity(self):
        pos = PositionState(
            ticker="AAPL", qty=10, entry_price=150.0, current_price=160.0,
            source=EngineSource.SWING,
            opened_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )
        snap = PortfolioSnapshot(cash=50_000.0, positions=[pos])
        # equity = 50_000 + 10 * 160 = 51_600
        assert snap.equity == pytest.approx(51_600.0)

    def test_drawdown_pct(self):
        snap = PortfolioSnapshot(
            cash=90_000.0, positions=[], initial_capital=100_000.0,
        )
        # drawdown = 1 - 90_000 / 100_000 = 0.10
        assert snap.drawdown_pct == pytest.approx(0.10)

    def test_no_drawdown(self):
        snap = PortfolioSnapshot(
            cash=110_000.0, positions=[], initial_capital=100_000.0,
        )
        assert snap.drawdown_pct == 0.0

    def test_empty_portfolio(self):
        snap = PortfolioSnapshot(cash=0.0, positions=[])
        assert snap.equity == 0.0


# ── RiskState ────────────────────────────────────────────────────────────────


class TestRiskState:
    def test_defaults(self):
        rs = RiskState()
        assert rs.regime == Regime.RISK_ON
        assert rs.halt_active is False
        assert rs.sector_counts == {}

    def test_halt(self):
        rs = RiskState(halt_active=True, halt_reason="Daily loss limit")
        assert rs.halt_active is True
        assert rs.halt_reason == "Daily loss limit"


# ── RiskVeto ─────────────────────────────────────────────────────────────────


class TestRiskVeto:
    def test_approved(self):
        veto = RiskVeto(
            order_id="abc123",
            vetoed=False,
            checks_passed=["sector_limit", "daily_loss", "open_risk"],
        )
        assert not veto.vetoed
        assert len(veto.checks_passed) == 3

    def test_vetoed(self):
        veto = RiskVeto(
            order_id="abc123",
            vetoed=True,
            reason="Sector cap reached",
            checks_failed=["sector_limit"],
            checks_passed=["daily_loss"],
        )
        assert veto.vetoed
        assert veto.reason == "Sector cap reached"


# ── EventFlags ───────────────────────────────────────────────────────────────


class TestEventFlags:
    def test_defaults(self):
        flags = EventFlags()
        assert flags.earnings_blackout == {}
        assert flags.regime_change is False
        assert flags.drawdown_halt is False
        assert flags.emergency_flatten is False
        assert flags.pause_buys is False
        assert flags.pause_sells is False

    def test_blackout(self):
        flags = EventFlags(earnings_blackout={"AAPL": True, "MSFT": False})
        assert flags.earnings_blackout["AAPL"] is True
        assert flags.earnings_blackout["MSFT"] is False

    def test_emergency(self):
        flags = EventFlags(emergency_flatten=True, pause_buys=True)
        assert flags.emergency_flatten is True
