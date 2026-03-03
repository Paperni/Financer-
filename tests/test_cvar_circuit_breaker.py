import numpy as np
import pandas as pd

from financer.core.orchestrator import CIOOrchestrator
from financer.core.governor import RiskGovernor
from financer.models.intents import TradeIntent, ReasonCode, EngineSource
from financer.models.enums import Direction, Conviction, TimeHorizon, Regime
from financer.models.portfolio import PortfolioSnapshot
from financer.models.risk import RiskState

def test_cvar_circuit_breaker_high_correlation_tech_basket():
    """
    Simulates a highly correlated, high-volatility basket of tech stocks.
    Proves that even though individual volatility sizing shrinks each position uniformly,
    the composite portfolio tail risk (CVaR_99) exceeds the 4.9% breaker and vetoes all buys.
    """
    np.random.seed(42)
    
    tickers = ["TSLA", "NVDA", "AMD", "COIN", "MSTR"]
    
    # 1. Synthesize highly correlated returns with fat tails (Black Swan events)
    periods = 252
    market_shock = np.random.normal(0, 0.05, periods) 
    
    # Inject extreme market crashes to generate tail risk beyond what a normal
    # distribution would produce under fixed volatility-targeting
    market_shock[10] = -0.40  
    market_shock[50] = -0.35
    market_shock[100] = -0.38
    market_shock[200] = -0.45

    historical_returns = {}
    for ticker in tickers:
        # Asset Volatility ~ 80% annualized
        # Correlated 100% to the shock, 5% idiosyncratic
        idiosyncratic = np.random.normal(0, 0.02, periods)
        returns = (1.0 * market_shock) + (0.05 * idiosyncratic)
        historical_returns[ticker] = pd.Series(returns)

    # 2. Setup CIO Orchestrator & Risk Governor
    # V2 Refactor updates RiskGovernor with max_cvar_99
    governor = RiskGovernor(max_cvar_99=0.049)
    orchestrator = CIOOrchestrator(governor=governor)
    
    portfolio = PortfolioSnapshot(cash=100000.0, positions=[])
    risk_state = RiskState(regime=Regime.RISK_ON)
    
    # 3. Create 5 Buy Intents
    intents = []
    for ticker in tickers:
        returns = historical_returns[ticker]
        ann_vol = float(returns.std() * np.sqrt(252)) # ~60-70%
        
        intent = TradeIntent(
            ticker=ticker,
            direction=Direction.BUY,
            conviction=Conviction.HIGH,
            time_horizon=TimeHorizon.SWING,
            source=EngineSource.SWING,
            reasons=[ReasonCode(code="BREAKOUT", detail="Test")],
            meta={"latest_price": 100.0, "annualized_vol": ann_vol}
        )
        intents.append(intent)

    # 4. Formulate Plan
    action_plan = orchestrator.formulate_plan(
        trade_intents=intents,
        allocation_intents=[],
        portfolio=portfolio,
        risk_state=risk_state,
        historical_returns=historical_returns
    )

    # 5. Assertions: Intercepted batch, 5 blocked orders, 0 executions
    assert len(action_plan.orders) == 0, f"Expected 0 orders, got {len(action_plan.orders)}"
    assert len(action_plan.vetoed_intents) == 5, f"Expected 5 vetoes, got {len(action_plan.vetoed_intents)}"
    
    for veto in action_plan.vetoed_intents:
        reason = veto.meta.get("veto_reason", "")
        print(f"[{veto.ticker}] VETOED: {reason}")
        assert "RISK_LIMIT_BREACH" in reason, f"Expected RISK_LIMIT_BREACH, got {reason}"

if __name__ == "__main__":
    test_cvar_circuit_breaker_high_correlation_tech_basket()
    print("\nSUCCESS: CVaR Circuit Breaker correctly intercepted the highly correlated basket.")
