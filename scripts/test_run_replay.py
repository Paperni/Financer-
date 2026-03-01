from financer.cli.run_replay import run_replay
from financer.features.build import build_features
import pandas as pd
import time

tickers = ["AAPL", "MSFT", "GOOGL", "SPY"]
feature_dfs = {}
for ticker in tickers:
    df = build_features(ticker, start="2021-01-01", end="2025-12-31")
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

print("Running run_replay...")
portfolio, equity_curve, trade_log = run_replay(
    tickers=list(feature_dfs.keys()),
    start="2021-01-01",
    end="2025-12-31",
    min_entry_score=5.0,
    precomputed_features=feature_dfs,
    precomputed_daily_features=daily_features
)

trades = sum(1 for d in trade_log for o in d.get("filled_orders", []) if o["direction"] == "SELL")
print(f"Trades logged: {trades}")
created = sum(len(d.get("created_orders", [])) for d in trade_log)
print(f"Total created orders: {created}")
vetoed = sum(len(d.get("vetoed_intents", [])) for d in trade_log)
print(f"Total vetoed intents: {vetoed}")
raw_intents = sum(len(d.get("candidate_intents", [])) for d in trade_log)
print(f"Total candidate intents logged: {raw_intents}")
from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
print(f"Running on {len(tickers)} tickers...")
feature_dfs = {}
for ticker in tickers[:50]:  # Just load 50 to test
    df = build_features(ticker, start="2021-01-01", end="2025-12-31")
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

print("Running run_replay.py...")
portfolio, equity_curve, trade_log = run_replay(
    tickers=list(feature_dfs.keys()),
    start="2021-01-01",
    end="2025-12-31",
    min_entry_score=5.0,
    precomputed_features=feature_dfs,
    precomputed_daily_features=daily_features
)
created = sum(len(d.get("created_orders", [])) for d in trade_log)
print(f"Total created orders: {created}")
vetoed = sum(len(d.get("vetoed_intents", [])) for d in trade_log)
print(f"Total vetoed intents: {vetoed}")
raw_intents = sum(len(d.get("candidate_intents", [])) for d in trade_log)
print(f"Total candidate intents logged: {raw_intents}")
