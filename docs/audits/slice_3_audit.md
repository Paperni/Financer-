# Slice 3 Quality Audit: Swing Engine

## 1. Architectural Checks

**✅ Emit Only TradeIntent**  
The Swing Engine strictly emits `TradeIntent` objects and never instantiates `Order` or `Position` objects directly. All outputs are correctly formatted as intents with conviction scores, targets, stops, and supporting reason codes.
*File:* `financer/engines/swing/engine.py:72` (return type `list[TradeIntent]`)

**✅ Strict Reader of build_features()**  
The engine expects a dictionary mapping string tickers to standard pandas Series (representing a single row output from `build_features()`). It does not import any legacy scripts (`downloader.py`, `portfolio.py`, etc.) for data fetching or logic.
*File:* `financer/engines/swing/engine.py:27` (`def evaluate(...)`)

**✅ Check Entry Readiness & Regime Gates**  
The `check_entry_readiness()` and `check_regime_allows_entry()` boundaries are correctly enforced inside the evaluation loop. If a row is missing required structural columns (like `atr_14`, `sma_50`, `regime`) or the market regime is `RISK_OFF`, the asset is skipped immediately without scoring.
*File:* `financer/engines/swing/engine.py:34-39`

## 2. Reason Codes
The scorecard emits the following reason codes during evaluation:

| Code | Trigger Criteria | Weight |
|---|---|---|
| `TREND_UP` | Price is > 50-period SMA | 1.0 |
| `RSI_PULLBACK` | 14-period RSI is between 30 and 45 | 1.0 |
| `RSI_OVERSOLD` | 14-period RSI is between 25 and 30 | 0.5 |
| `MACD_POSITIVE` | MACD Histogram > 0 | 1.0 |
| `STRONG_RS` | 20-period Relative Strength vs SPY > 1.05 | 1.0 |
| `POSITIVE_RS` | 20-period Relative Strength vs SPY > 1.00 | 0.5 |
| `FAIR_VALUATION` | PEG Proxy <= 1.2 | 1.0 |
| `NO_EARNINGS_RISK` | Earnings date is NOT within next 7 days | 1.0 |

*File:* `financer/engines/swing/scorecard.py:18`

## 3. Tunable Parameters
All core tunables are currently isolated across the engine configurations:

**Drafting Parameters:**
- **Momentum Lookback:** 20 periods (`roc_20` and `rs_20`)
- **Draft Size:** 10 assets maximum (`engine.py:24`)

**Scorecard Parameters:**
- **Entry Minimum Score Threshold:** 4.0 out of 6.0 (`engine.py:24`)
- **RSI Pullback Band:** 30 to 45 (`scorecard.py:25`)
- **ATR Multiples for Exits:** Stop Loss = -1.5 ATR, Target = +4.0 ATR (`engine.py:53`)

**Policy Parameters (Market Regime Allocation):**
- **RISK_ON:** Cash 0%, Baseline 20%, Swing 80%
- **CAUTIOUS:** Cash 40%, Baseline 30%, Swing 30%
- **RISK_OFF:** Cash 80%, Baseline 20%, Swing 0%
*File:* `financer/engines/swing/policy.py:12`

> **Note on Trade Frequency**: 
> Currently, the system requires a score of 4.0/6.0, meaning an asset must have a perfect RSI dip, an explicit MACD turnaround, strong relative momentum, AND fair valuation simultaneously. This will likely result in low trade frequency (1-3 trades a month). 
> 
> *To loosen frequency first*: Reduce the `min_entry_score` constraint from 4.0 to 3.0 in `engine.py`.
