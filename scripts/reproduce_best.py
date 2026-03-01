import json
import csv
import hashlib
from pathlib import Path
import pandas as pd
from financer.features.build import build_features
from financer.cli.run_replay import run_replay
from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
from financer.execution import policy
from financer.models import sizing
from financer.engines.swing import scorecard

# Define highest returned survived configuration:
best_config = {
    "score_threshold": 5,
    "stop_atr_mult": 1.75,
    "time_stop_bars": 50,
    "rsi_band": [30, 45],
    "cautious_size_mult": 0.75
}

print(f"Reproducing Best Run: {best_config}")

tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
start_date = "2021-01-01"
end_date = "2025-12-31"

print(f"Loading cached features for {len(tickers)} tickers...")
feature_dfs = {}
for ticker in tickers:
    df = build_features(ticker, start=start_date, end=end_date)
    if not df.empty:
        feature_dfs[ticker] = df

daily_features = {}
for ticker, df in feature_dfs.items():
    ticker_dict = df.to_dict('index')
    for d, row_dict in ticker_dict.items():
        if pd.isna(d): continue
        ts = pd.to_datetime(d).normalize()
        if ts not in daily_features:
            daily_features[ts] = {}
        daily_features[ts][ticker] = row_dict

# Patch globals
policy.STOP_LOSS_ATR_MULTIPLIER = best_config["stop_atr_mult"]
sizing.ATR_STOP_MULTIPLIER = best_config["stop_atr_mult"]
policy.TIME_STOP_DAYS = best_config["time_stop_bars"]
scorecard.RSI_BAND_LOWER = best_config["rsi_band"][0]
scorecard.RSI_BAND_UPPER = best_config["rsi_band"][1]
sizing.CAUTIOUS_SIZE_MULT = best_config["cautious_size_mult"]

print("Running Replay...")
portfolio, equity_curve, trade_log = run_replay(
    tickers=list(feature_dfs.keys()),
    start=start_date,
    end=end_date,
    initial_cash=100000.0,
    min_entry_score=best_config["score_threshold"],
    stop_loss_atr_mult=best_config["stop_atr_mult"],
    precomputed_features=feature_dfs,
    precomputed_daily_features=daily_features
)

total_return = ((portfolio.equity / 100000.0) - 1.0) * 100.0
print(f"Replay complete. Final Equity: ${portfolio.equity:,.2f} ({total_return:.2f}%)")

out_dir = Path("artifacts/reproduce_best")
out_dir.mkdir(parents=True, exist_ok=True)

# Save Report
report = {"final_equity": portfolio.equity, "return_pct": total_return, "config": best_config}
with open(out_dir / "report.json", "w") as f:
    json.dump(report, f, indent=2)

# Save Equity Curve
with open(out_dir / "equity_curve.json", "w") as f:
    json.dump(equity_curve, f, indent=2)

# Save Ledger (Trade Log)
with open(out_dir / "ledger.csv", "w", newline="") as f:
    # Just grab all filled orders from the log
    writer = csv.writer(f)
    writer.writerow(["date", "ticker", "direction", "qty", "price"])
    for day in trade_log:
        for order in day.get("filled_orders", []):
            writer.writerow([day["date"], order["ticker"], order["direction"], order["qty"], order["price"]])

# Hash
for fname in ["report.json", "equity_curve.json", "ledger.csv"]:
    pth = out_dir / fname
    h = hashlib.sha256(pth.read_bytes()).hexdigest()
    print(f"{fname} SHA256: {h}")
