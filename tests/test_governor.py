from datetime import datetime, timezone
from financer.core.governor import RiskGovernor
from financer.models.actions import Order
from financer.models.enums import Direction, OrderStatus, EngineSource, Conviction, TimeHorizon
from financer.models.intents import TradeIntent, ReasonCode
from financer.models.portfolio import PortfolioSnapshot, PositionState
from financer.models.risk import RiskState


def test_anti_pyramiding_off():
    """When pyramiding is off, consecutive buys for same ticker are rejected."""
    gov = RiskGovernor(pyramiding_mode="off")
    portfolio = PortfolioSnapshot(cash=10000.0, positions=[
        PositionState(
            ticker="AAPL", qty=10, entry_price=150.0, source=EngineSource.SWING,
            opened_at=datetime.now(timezone.utc)
        )
    ])
    
    intent = TradeIntent(ticker="AAPL", target_price=160.0, stop_price=140.0,
                         direction=Direction.BUY, source=EngineSource.SWING,
                         conviction=Conviction.MEDIUM, time_horizon=TimeHorizon.SWING,
                         reasons=[ReasonCode(code="MOCK")])
                         
    approved, vetoed = gov.veto_intents([intent], portfolio)
    assert len(approved) == 0
    assert len(vetoed) == 1
    assert "anti-pyramiding" in vetoed[0].meta["veto_reason"]


def test_pyramiding_on_rejects_early():
    """When pyramiding is on, but position is < +1R, it is rejected."""
    gov = RiskGovernor(pyramiding_mode="on")
    portfolio = PortfolioSnapshot(cash=10000.0, positions=[
        PositionState(
            ticker="AAPL", qty=10, entry_price=150.0, current_price=155.0, # Target 1R is +10.0
            stop_loss=140.0, source=EngineSource.SWING,
            opened_at=datetime.now(timezone.utc)
        )
    ])
    
    intent = TradeIntent(ticker="AAPL", target_price=170.0, stop_price=150.0,
                         direction=Direction.BUY, source=EngineSource.SWING,
                         conviction=Conviction.MEDIUM, time_horizon=TimeHorizon.SWING,
                         reasons=[ReasonCode(code="MOCK")])
                         
    approved, vetoed = gov.veto_intents([intent], portfolio)
    assert len(approved) == 0
    assert len(vetoed) == 1
    assert "not_at_plus_1R_yet" in vetoed[0].meta["veto_reason"]


def test_pyramiding_on_approves_and_tags():
    """When pyramiding is on, and position is >= +1R, it is approved and tagged."""
    gov = RiskGovernor(pyramiding_mode="on")
    portfolio = PortfolioSnapshot(cash=10000.0, positions=[
        PositionState(
            ticker="AAPL", qty=10, entry_price=150.0, current_price=161.0, # +11.0 > 10.0 (1R)
            stop_loss=140.0, source=EngineSource.SWING,
            opened_at=datetime.now(timezone.utc)
        )
    ])
    
    intent = TradeIntent(ticker="AAPL", target_price=170.0, stop_price=150.0,
                         direction=Direction.BUY, source=EngineSource.SWING,
                         conviction=Conviction.MEDIUM, time_horizon=TimeHorizon.SWING,
                         reasons=[ReasonCode(code="MOCK")])
                         
    approved, vetoed = gov.veto_intents([intent], portfolio)
    assert len(vetoed) == 0
    assert len(approved) == 1
    assert approved[0].meta.get("is_pyramid_add") is True


def test_governor_max_heat_R():
    """Governor blocks order if Max Heat R limit is exceeded."""
    gov = RiskGovernor(max_heat_R=2.0)
    
    # 1R = 10% of portfolio if heat config expects (Total Risk / 1% Equity).
    # Equity = 10,000. Base 1R = 100.
    portfolio = PortfolioSnapshot(cash=10000.0, positions=[
        PositionState(
            ticker="AAPL", qty=10, entry_price=150.0, current_price=150.0,
            stop_loss=135.0, source=EngineSource.SWING,  # Risk = (150-135)*10 = 150 (1.5R)
            opened_at=datetime.now(timezone.utc)
        )
    ])
    state = RiskState()
    
    order = Order(
        ticker="MSFT", qty=10, price=300.0, stop_loss=290.0, # Expected Risk = 100 (1.0R)
        direction=Direction.BUY, source_engine=EngineSource.SWING,
        reason_codes=["MOCK"]
    )
    
    # Total combined proposed risk = 250 (2.5R). Max allowed = 2.0R.
    evaluated_order, veto = gov.evaluate_order(order, state, portfolio)
    assert veto.vetoed is True
    assert "max_heat_R_exceeded" in veto.reason
