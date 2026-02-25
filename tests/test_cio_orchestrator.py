from __future__ import annotations

from financer.core.governor import RiskGovernor
from financer.core.orchestrator import CIOOrchestrator
from financer.execution.broker_sim import SimBroker

from financer.models.enums import Conviction, Direction, EngineSource, OrderStatus, TimeHorizon, Regime
from financer.models.intents import ReasonCode, TradeIntent
from financer.models.portfolio import PortfolioSnapshot
from financer.models.risk import RiskState


def test_risk_governor_allows_and_vetoes():
    gov = RiskGovernor(max_open_risk_pct=0.10)
    
    # Needs absolute mock orders to test RiskGovernor directly
    from financer.models.actions import Order
    order = Order(
        ticker="AAPL", direction=Direction.BUY, qty=10, price=150.0,
        source_engine=EngineSource.SWING, reason_codes=[]
    )
    
    # 1. Allow entry (under risk limit)
    state = RiskState(open_risk_pct=0.05)
    order, veto = gov.evaluate_order(order, state)
    assert not veto.vetoed
    assert order.status == OrderStatus.APPROVED

    # 2. Veto entry (over risk limit)
    state = RiskState(open_risk_pct=0.15)
    order, veto = gov.evaluate_order(order, state)
    assert veto.vetoed
    assert order.status == OrderStatus.VETOED
    assert "open_risk_pct" in veto.reason


def test_cio_transforms_intents_to_action_plan():
    orch = CIOOrchestrator()
    intent = TradeIntent(
        ticker="TSLA",
        direction=Direction.BUY,
        conviction=Conviction.HIGH,
        time_horizon=TimeHorizon.SWING,
        source=EngineSource.SWING,
        reasons=[ReasonCode(code="RSI_PULLBACK")],
        stop_price=180.0,
        target_price=220.0,
        meta={"latest_price": 200.0, "atr_14": 5.0}
    )

    portfolio = PortfolioSnapshot(cash=100_000, positions=[])
    risk_state = RiskState(regime=Regime.RISK_ON, open_risk_pct=0.0)

    # Convert Intent -> ActionPlan
    plan = orch.formulate_plan([intent], [], portfolio, risk_state)
    
    assert len(plan.orders) == 1
    order = plan.orders[0]
    
    assert order.ticker == "TSLA"
    assert order.status == OrderStatus.APPROVED
    assert order.qty > 0  # Sizing engine assigned a quantity


def test_sim_broker_executes_action_plan():
    orch = CIOOrchestrator()
    broker = SimBroker()

    intent = TradeIntent(
        ticker="MSFT",
        direction=Direction.BUY,
        conviction=Conviction.VERY_HIGH,
        time_horizon=TimeHorizon.SWING,
        source=EngineSource.SWING,
        reasons=[],
        meta={"latest_price": 400.0, "atr_14": 10.0}
    )

    initial_cash = 50_000.0
    portfolio = PortfolioSnapshot(cash=initial_cash, positions=[])
    risk_state = RiskState(regime=Regime.RISK_ON)

    # Orchestrator formulates the plan
    plan = orch.formulate_plan([intent], [], portfolio, risk_state)
    order_qty = plan.orders[0].qty
    assert plan.orders[0].status == OrderStatus.APPROVED

    # Broker executes the plan
    updated_portfolio = broker.execute_plan(plan, portfolio)

    assert len(updated_portfolio.positions) == 1
    assert updated_portfolio.positions[0].ticker == "MSFT"
    assert updated_portfolio.positions[0].qty == order_qty
    
    expected_cash = initial_cash - (order_qty * 400.0)
    assert updated_portfolio.cash == expected_cash
    assert plan.orders[0].status == OrderStatus.FILLED
