import pandas as pd
from pathlib import Path
from financer.engines.swing.scorecard import score_setup
import numpy as np

features_dir = Path("data/cache/features")

print("Scanning precomputed feature files to check scores...")

files = list(features_dir.glob("*.parquet"))
if not files:
    print("No parquet files found in cache.")
    exit(0)

# Load a few files and score every row
max_score = 0
score_dist = {i: 0 for i in range(8)}
total_rows = 0

for idx, f in enumerate(files[:50]): # Check first 50 files
    df = pd.read_parquet(f)
    if "above_50" not in df.columns:
        # Doesn't have features yet, was just raw prices cached?
        # WAIT! The cache is in `data_cache` but build_features caches in `.cache/features`?
        continue
    
    for i in range(len(df)):
        row = df.iloc[i]
        try:
            score, reasons = score_setup(row)
            score_dist[int(score)] += 1
            if score > max_score:
                max_score = score
            total_rows += 1
        except Exception:
            pass

print(f"Total Rows Scored: {total_rows}")
print(f"Max Score Achieved: {max_score}")
print("Score Distribution:")
for k, v in score_dist.items():
    if v > 0:
        print(f"  Score {k}: {v}")
