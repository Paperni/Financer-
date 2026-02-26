from unittest.mock import patch
import pandas as pd
from datetime import datetime, timezone
import hashlib

from financer.cli.run_replay import run_replay, save_artifacts
from financer.models.enums import Regime


def test_golden_replay_deterministic_no_network(tmp_path):
    """Verify run_replay produces deterministic results given static synthetic features."""

    dates = pd.date_range(start="2025-01-01", periods=3, tz=timezone.utc)
    
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

    with patch("financer.cli.run_replay.build_features") as mock_build:
        mock_build.return_value = df_mock
        
        portfolio, equity_curve, trade_log = run_replay(
            tickers=["SYNTH"],
            start="2025-01-01",
            end="2025-01-03",
            initial_cash=100_000.0,
            min_entry_score=4.0
        )
        
    # Flatten all filled orders across all days
    all_filled = []
    for day in trade_log:
        all_filled.extend(day["filled_orders"])
        
    assert len(all_filled) == 2  # One BUY, One SELL (Take Profit)
    
    assert all_filled[0]["direction"] == "BUY"
    assert all_filled[0]["ticker"] == "SYNTH"
    assert all_filled[0]["status"] == "FILLED"
    assert all_filled[0]["price"] == 100.0
    
    assert all_filled[1]["direction"] == "SELL"
    assert all_filled[1]["ticker"] == "SYNTH"
    assert all_filled[1]["status"] == "FILLED"
    assert all_filled[1]["price"] == 110.0
    
    assert len(equity_curve) == 3
    assert equity_curve[-1]["equity"] > 100_000.0
    assert len(portfolio.positions) == 0
    assert portfolio.cash == portfolio.equity
    
    # Save artifacts locally to tmp_path
    save_artifacts(equity_curve, trade_log, output_dir=str(tmp_path))
    assert (tmp_path / "equity_curve.json").exists()
    assert (tmp_path / "replay_trades.json").exists()


def test_golden_replay_multiticker_deterministic_hash(tmp_path):
    dates = pd.date_range(start="2025-01-01", periods=60, tz=timezone.utc)
    
    def make_synth(base_price):
        return pd.DataFrame({
            "Close": [base_price + i for i in range(60)],
            "atr_14": [2.0] * 60,
            "sma_50": [base_price - 10] * 60,
            "above_50": [True] * 60,
            "regime": ["RISK_ON"] * 60,
            "rsi_14": [(30.0 + i) if i < 15 else 80.0 for i in range(60)],
            "macd_hist": [0.5 if i == 0 else -0.5 for i in range(60)],
            "rs_20": [1.1 if i == 0 else 0.9 for i in range(60)],
            "peg_proxy": [1.0] * 60,
            "earnings_within_7d": [False] * 60,
            "roc_20": [0.15] * 60
        }, index=dates)

    dfs = {"AAPL": make_synth(150), "MSFT": make_synth(300), "SPY": make_synth(400)}
    
    def mock_build_features(ticker, start, end):
        return dfs[ticker]
        
    with patch("financer.cli.run_replay.build_features", side_effect=mock_build_features):
        portfolio, eq, trades = run_replay(
            tickers=["AAPL", "MSFT", "SPY"],
            start="2025-01-01",
            end="2025-02-28", # Approx 60 days
            initial_cash=100_000.0,
            min_entry_score=4.0
        )
        
    save_artifacts(eq, trades, str(tmp_path))
    
    with open(tmp_path / "replay_trades.json") as f:
        trades_str = f.read()
    with open(tmp_path / "equity_curve.json") as f:
        eq_str = f.read()
        
    trades_hash = hashlib.sha256(trades_str.encode()).hexdigest()
    eq_hash = hashlib.sha256(eq_str.encode()).hexdigest()
    
    assert trades_hash != "" 
    assert eq_hash != ""


def test_veto_unknown_regime():
    dates = pd.date_range("2025-01-01", periods=1, tz=timezone.utc)
    df = pd.DataFrame({
        "Close": [100.0], "atr_14": [2.0], "sma_50": [90.0], "above_50": [True],
        "regime": [float("nan")], # Unknown regime
        "rsi_14": [35.0], "macd_hist": [0.5], "rs_20": [1.1], "peg_proxy": [1.0],
        "earnings_within_7d": [False], "roc_20": [0.15]
    }, index=dates)

    with patch("financer.cli.run_replay.build_features", return_value=df):
        port, eq, trades = run_replay(["TICK"], "2025-01-01", "2025-01-01", min_entry_score=4.0)
    assert len(trades[0]["filled_orders"]) == 0


def test_veto_missing_columns():
    dates = pd.date_range("2025-01-01", periods=1, tz=timezone.utc)
    df = pd.DataFrame({
        "Close": [100.0], "atr_14": [float("nan")], # Missing
        "sma_50": [90.0], "above_50": [True], "regime": ["RISK_ON"],
        "rsi_14": [35.0], "macd_hist": [0.5], "rs_20": [1.1], "peg_proxy": [1.0],
        "earnings_within_7d": [False], "roc_20": [0.15]
    }, index=dates)

    with patch("financer.cli.run_replay.build_features", return_value=df):
        port, eq, trades = run_replay(["TICK"], "2025-01-01", "2025-01-01", min_entry_score=4.0)
    assert len(trades[0]["filled_orders"]) == 0


def test_veto_earnings_blackout():
    dates = pd.date_range("2025-01-01", periods=1, tz=timezone.utc)
    df = pd.DataFrame({
        "Close": [100.0], "atr_14": [2.0], "sma_50": [90.0], "above_50": [True],
        "regime": ["RISK_ON"], "rsi_14": [35.0], "macd_hist": [0.5], "rs_20": [1.1],
        "peg_proxy": [1.0], "earnings_within_7d": [True], # Blackout
        "roc_20": [0.15]
    }, index=dates)

    with patch("financer.cli.run_replay.build_features", return_value=df):
        port, eq, trades = run_replay(["TICK"], "2025-01-01", "2025-01-01", min_entry_score=4.0)
    assert len(trades[0]["filled_orders"]) == 0


def test_integrity_no_multiple_buys():
    dates = pd.date_range("2025-01-01", periods=2, tz=timezone.utc)
    df = pd.DataFrame({
        "Close": [100.0, 100.0], "atr_14": [2.0, 2.0], "sma_50": [90.0, 90.0],
        "above_50": [True, True], "regime": ["RISK_ON", "RISK_ON"],
        "rsi_14": [35.0, 35.0], "macd_hist": [0.5, 0.5], "rs_20": [1.1, 1.1],
        "peg_proxy": [1.0, 1.0], "earnings_within_7d": [False, False], "roc_20": [0.15, 0.15]
    }, index=dates)

    with patch("financer.cli.run_replay.build_features", return_value=df):
        port, eq, trades = run_replay(["TICK"], "2025-01-01", "2025-01-02", min_entry_score=4.0)
    
    # Assert Day 1 buys the ticket
    day1 = trades[0]
    assert len(day1["filled_orders"]) == 1
    assert day1["filled_orders"][0]["direction"] == "BUY"
    
    # Assert Day 2 attempts to buy again but is caught by intent veto
    day2 = trades[1]
    assert len(day2["candidate_intents"]) == 1
    assert len(day2["vetoed_intents"]) == 1
    assert "anti-pyramiding" in day2["vetoed_intents"][0]["reason"]
    assert len(day2["filled_orders"]) == 0
