import pandas as pd
from datetime import timezone
from unittest.mock import patch
from financer.cli.run_replay import run_replay

dates = pd.date_range("2025-01-01", periods=2, tz=timezone.utc)
df = pd.DataFrame({
    "Close": [100.0, 100.0], "atr_14": [2.0, 2.0], "sma_50": [90.0, 90.0],
    "above_50": [True, True], "regime": ["RISK_ON", "RISK_ON"],
    "rsi_14": [35.0, 35.0], "macd_hist": [0.5, 0.5], "rs_20": [1.1, 1.1],
    "peg_proxy": [1.0, 1.0], "earnings_within_7d": [False, False], "roc_20": [0.15, 0.15]
}, index=dates)

def debug():
    with patch("financer.cli.run_replay.build_features", return_value=df):
        port, eq, trades = run_replay(["TICK"], "2025-01-01", "2025-01-02", min_entry_score=4.0)
    
    print("ALL TRADES:")
    for t in trades:
        print(f"Date: {t['date']}, Ticker: {t['ticker']}, Dir: {t['direction']}, Status: {t['status']}, Reason: {t['veto_reason']}")
        
if __name__ == "__main__":
    debug()
