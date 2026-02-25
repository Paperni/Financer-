from unittest.mock import patch
import pandas as pd
from datetime import datetime, timezone

from financer.cli.run_replay import run_replay
from financer.models.enums import Regime


def test_golden_replay_deterministic_no_network():
    """Verify run_replay produces deterministic results given static synthetic features."""

    # 1. Create a synthetic feature dataframe spanning 3 days
    dates = pd.date_range(start="2025-01-01", periods=3, tz=timezone.utc)
    
    # Day 0: Setup scores a 6.0! (RSI 35, MACD > 0, PEG 1.0, etc.)
    # Day 1: Price goes up strongly.
    # Day 2: Price hits TP of 110.0 (Entry 100, ATR 2.5, Target +4ATR: 100+10 = 110)
    
    df_mock = pd.DataFrame({
        "Close": [100.0, 105.0, 110.0],
        "atr_14": [2.5, 2.5, 2.5],
        "sma_50": [90.0, 91.0, 92.0],
        "above_50": [True, True, True],
        "regime": ["RISK_ON", "RISK_ON", "RISK_ON"],
        "rsi_14": [35.0, 60.0, 75.0],
        "macd_hist": [0.5, -0.5, -0.5],
        "rs_20": [1.1, 0.9, 0.9],
        "peg_proxy": [1.0, 3.0, 3.0],
        "earnings_within_7d": [False, False, False],
        "roc_20": [0.15, 0.20, 0.25]
    }, index=dates)

    # 2. Mock 'build_features' to return our synthetic DF
    with patch("financer.cli.run_replay.build_features") as mock_build:
        mock_build.return_value = df_mock
        
        # 3. Run Replay
        portfolio, equity_curve, trade_log = run_replay(
            tickers=["SYNTH"],
            start="2025-01-01",
            end="2025-01-03",
            initial_cash=100_000.0,
            min_entry_score=4.0
        )
        
    # 4. Assert Deterministic Outputs
    assert len(trade_log) == 2  # One BUY, One SELL (Take Profit)
    
    assert trade_log[0]["direction"] == "BUY"
    assert trade_log[0]["ticker"] == "SYNTH"
    assert trade_log[0]["status"] == "FILLED"
    assert trade_log[0]["price"] == 100.0
    
    assert trade_log[1]["direction"] == "SELL"
    assert trade_log[1]["ticker"] == "SYNTH"
    assert trade_log[1]["status"] == "FILLED"
    assert trade_log[1]["price"] == 110.0
    
    assert len(equity_curve) == 3
    # Initial Equity = 100k
    # Day 0 Buy: PnL 0
    # Day 1: Price goes from 100 to 105. Unrealized Pnl goes up.
    # Day 2: Price hits 110. Sold for +10 per share.
    assert equity_curve[-1]["equity"] > 100_000.0
    
    # Portfolio cleanly flattened
    assert len(portfolio.positions) == 0
    assert portfolio.cash == portfolio.equity
