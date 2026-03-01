from financer.features.build import build_features
import pandas as pd

df = build_features("AAPL", start="2021-01-01", end="2025-12-31")
print("Columns:")
print(list(df.columns))
print("Any NaN in required columns?")
for col in ["atr_14", "sma_50", "above_50", "regime", "rs_20"]:
    print(f"{col}: {df[col].isna().sum()} NaNs")
    
if not df.empty:
    print(df.tail(1)[["atr_14", "sma_50", "above_50", "regime", "rs_20"]])
