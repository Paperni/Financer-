# Money Machine v3 — Complete Implementation Plan

A comprehensive upgrade from conservative prototype to fully-deployed institutional-grade swing trading system.

> **IMPORTANT:** This plan is designed for a coding agent. Every change is specified with exact file paths, function names, and logic. Follow the order precisely — each phase builds on the previous.

---

## Current Codebase State

| File | Lines | Key Responsibilities |
|---|---|---|
| `portfolio.py` | ~618 | Wallet, position sizing, buy/sell execution, exit logic, constants |
| `live_trader.py` | ~646 | Main loop, scan_and_buy, update_holdings, dashboard, CLI |
| `indicators.py` | ~501 | DataCache, technical indicators, 8-point scoring, regime detection |
| `data_static.py` | ~30 | Ticker lists (BROAD_STOCKS, BROAD_ETFS) |

### What Has Already Been Partially Applied

Some Phase 1 changes may exist in the codebase from a previous session. The coding agent **must verify** the current state of each item before making changes:

- `TIME_STOP_HOURS = 72` — may already be set in `portfolio.py` line ~41
- `SLIPPAGE_PCT = 0.0005` — may already exist in `portfolio.py` line ~44
- `deploy_baseline()`, `free_baseline()`, `count_swing_positions()` — may already exist in `portfolio.py` lines ~183-278
- Fee application in `execute_buy()` / `execute_sell()` — may already include slippage logic
- `update_holdings()` in `live_trader.py` may already skip baseline positions
- `scan_and_buy()` in `live_trader.py` may already use `count_swing_positions()`
- `run_live_cycle()` in `live_trader.py` may already have baseline deploy/free logic

> **CAUTION:** Before implementing, read each function fully and check what's already there. Do NOT blindly duplicate code. If a change is already applied, skip it and move on.

---

## Phase 1: Foundation (Fee Model + Capital Deployment + Time Stop)

### 1A. Fee Modeling — Honest PnL Tracking

#### MODIFY `portfolio.py`

**Add constant** (near line 44, after TIME_STOP_HOURS):
```python
SLIPPAGE_PCT = 0.0005  # 0.05% per trade (buy + sell = 0.10% round trip)
```

**Modify `execute_buy()` (starts ~line 340):**
- After calculating `qty`, compute effective buy price:
  ```python
  effective_price = price * (1 + SLIPPAGE_PCT)
  fee = qty * price * SLIPPAGE_PCT
  cost = qty * effective_price  # We pay slightly more than market
  ```
- Use `effective_price` for all cost calculations and cash affordability checks
- Track cumulative fees: `wallet["total_fees"] = wallet.get("total_fees", 0) + fee`
- Add `"Fee": round(fee, 2)` to the history record

**Modify `execute_sell()` (starts ~line 406):**
- Compute effective sell price:
  ```python
  effective_price = price * (1 - SLIPPAGE_PCT)
  fee = qty * price * SLIPPAGE_PCT
  proceeds = qty * effective_price  # We receive slightly less than market
  ```
- Track cumulative fees: `wallet["total_fees"] = wallet.get("total_fees", 0) + fee`
- PnL calculation must use `proceeds - entry_val` (which now includes fee drag)
- Add `"Fee": round(fee, 2)` to the history record

---

### 1B. Time Stop Extension

#### MODIFY `portfolio.py`

Change `TIME_STOP_HOURS` from `21` to `50` (line ~41). Reasoning: swing trades need 3 trading days to develop — cutting after 1 day kills potential winners.

---

### 1C. Baseline QQQ Position (Idle Cash Always Working)

#### MODIFY `portfolio.py`

**Add constants** (after `check_drawdown_halt` function):
```python
BASELINE_TICKER = "QQQ"
BASELINE_CASH_RESERVE = 2000.0  # Keep $2K reserve for slippage headroom
```

**Add function `deploy_baseline(wallet, price)`:**
- Calculate available cash: `wallet["cash"] - BASELINE_CASH_RESERVE`
- If available < one share price, return 0
- Calculate qty: `int(available / (price * (1 + SLIPPAGE_PCT)))`
- Apply slippage fee (same as execute_buy)
- If QQQ baseline already exists in holdings (check `pos.get("is_baseline")`), **merge**: recalculate weighted-average entry price, add qty
- If creating new baseline position, set special fields:
  - `"is_baseline": True`
  - `"sl": 0` (no stop loss on index baseline)
  - `"tp1": 999999, "tp2": 999999, "tp3": 999999` (never triggers TP)
- Log to wallet history with `"Reason": "Baseline deploy"`
- Return qty bought

**Add function `free_baseline(wallet, amount_needed, price)`:**
- Check if QQQ exists in holdings and has `is_baseline=True`
- Calculate shares to sell: `min(pos["qty"], int(amount_needed / price) + 1)`
- Apply slippage fee (same as execute_sell)
- Remove position if fully sold
- Log to history with `"Reason": "Baseline free (swing trade)"`
- Return total proceeds

**Add function `count_swing_positions(wallet)`:**
```python
def count_swing_positions(wallet):
    return sum(1 for pos in wallet["holdings"].values() if not pos.get("is_baseline"))
```

**Modify `check_exits()` (starts ~line 439):**
- Add guard at the very top, after `pos = wallet["holdings"][ticker]`:
  ```python
  if pos.get("is_baseline"):
      return None  # Never auto-exit the baseline
  ```

---

### 1D. Integrate Baseline into Live Trader

#### MODIFY `live_trader.py`

**Modify `update_holdings()` (starts ~line 53):**
- After getting `holdings = wallet["holdings"]`, separate tickers:
  ```python
  swing_tickers = [t for t in holdings if not holdings[t].get("is_baseline")]
  all_tickers = list(holdings.keys())
  ```
- Fetch live prices for ALL tickers (baseline too — need current price)
- Update `last_price` on ALL positions (including baseline)
- Only run `check_exits()` on `swing_tickers` (not baseline)

**Modify `scan_and_buy()` (starts ~line 103):**
- Replace all `len(wallet["holdings"])` with `pf.count_swing_positions(wallet)`
- This ensures the baseline doesn't count against `MAX_POSITIONS`

**Modify `run_live_cycle()` (starts ~line 424):**
- After scan_and_buy (step 6), add step 7 — baseline deployment:
  ```python
  # 7. Deploy idle cash into QQQ baseline
  if wallet["cash"] > pf.BASELINE_CASH_RESERVE + 500:
      qqq_price = _cache.get_latest_price(pf.BASELINE_TICKER) or _get_live_price(pf.BASELINE_TICKER)
      bought = pf.deploy_baseline(wallet, qqq_price)
      if bought > 0:
          print(f"  Deployed {bought} shares of QQQ baseline @ ${qqq_price:.2f}")
  ```
- Before scan_and_buy, if cash is low but baseline exists, free it:
  ```python
  if wallet["cash"] < 5000 and pf.BASELINE_TICKER in wallet["holdings"]:
      qqq_price = _cache.get_latest_price(pf.BASELINE_TICKER) or _get_live_price(pf.BASELINE_TICKER)
      freed = pf.free_baseline(wallet, 15000, qqq_price)
      if freed > 0:
          print(f"  Freed ${freed:,.0f} from QQQ baseline for swing trades")
  ```
- Update cycle-end print to show fees and swing count:
  ```python
  fees = wallet.get('total_fees', 0)
  print(f"  Cycle Complete. Equity: ${equity:,.0f} | Fees: ${fees:,.2f} | Swing: {swing_count}/{pf.MAX_POSITIONS} ({regime})")
  ```

**Modify `--status` handler (starts ~line 547):**
- Show baseline position separately at the top
- Skip baseline from the swing positions loop
- Show fee totals: `wallet.get("total_fees", 0)`
- Exclude baseline trades from win/loss rate calculation

**Update startup banner (`--loop`, ~line 592):**
- Title: `LIVE MONEY MACHINE v3`
- Add lines for: fee model rate, baseline ticker, news gate, max swing + baseline

---

## Phase 2: Intelligence (FinBERT + Earnings Calendar + Pyramiding)

### 2A. FinBERT Sentiment Analysis

#### Dependencies
```bash
pip install transformers torch
```
This is ~2GB. Runs on CPU. Model: `ProsusAI/finbert`

#### MODIFY `indicators.py`

**Add to `DataCache.__init__()` (line ~21):**
```python
self._news_cache = {}       # ticker -> {sentiment, score, headlines, cached_at}
self._news_ttl = 2 * 3600   # cache news for 2 hours
self._finbert = None        # lazy-loaded FinBERT model
self._finbert_tokenizer = None
```

**Add method `DataCache._load_finbert(self)`:**
```python
def _load_finbert(self):
    if self._finbert is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        model_name = "ProsusAI/finbert"
        self._finbert_tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._finbert = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._finbert.eval()
    return self._finbert, self._finbert_tokenizer
```

**Add method `DataCache.get_news_sentiment(self, ticker)`:**

Logic:
1. Check cache — if cached and within TTL, return cached result
2. Fetch headlines: `yf.Ticker(ticker).news` → list of dicts with `"title"` and `"providerPublishTime"`
3. Filter to last 72 hours only
4. Apply recency weighting: last 24h = weight 1.0, 24-72h = weight 0.5
5. Run each headline through FinBERT:
   ```python
   model, tokenizer = self._load_finbert()
   inputs = tokenizer(headline, return_tensors="pt", truncation=True, max_length=128)
   with torch.no_grad():
       outputs = model(**inputs)
   probs = torch.nn.functional.softmax(outputs.logits, dim=1)
   # FinBERT output: [positive, negative, neutral]
   pos, neg, neu = probs[0].tolist()
   ```
6. Calculate weighted sentiment score per headline: `(pos - neg) * recency_weight`
7. Aggregate: `net_sentiment = sum(weighted_scores) / len(headlines)`

Return dict:
```python
{
    "sentiment": "DANGER" | "NEGATIVE" | "NEUTRAL" | "POSITIVE",
    "score": float,           # -1.0 to +1.0
    "adjustment": float,      # score modifier: -99 (block), -1, 0, or +0.5
    "headline_count": int,
    "top_headline": str,      # Most impactful headline
    "cached_at": float,
}
```

Thresholds:
- `net_sentiment < -0.5` → DANGER, `adjustment = -99` (hard block)
- `-0.5 <= net_sentiment < -0.2` → NEGATIVE, `adjustment = -1.0`
- `-0.2 <= net_sentiment <= 0.2` → NEUTRAL, `adjustment = 0`
- `net_sentiment > 0.2` → POSITIVE, `adjustment = +0.5`

Cache result and return.

**Fallback:** Wrap entire method in try/except. On any error (no news, model failure, import error), return `{"sentiment": "NEUTRAL", "adjustment": 0, ...}` — never block a trade because the news system failed.

---

### 2B. Earnings Calendar Awareness

#### MODIFY `indicators.py`

**Add to `DataCache.__init__()`:**
```python
self._earnings_cache = {}   # ticker -> {earnings_date, cached_at}
self._earnings_ttl = 12 * 3600  # cache earnings dates for 12 hours
```

**Add method `DataCache.get_earnings_date(self, ticker)`:**
```python
def get_earnings_date(self, ticker):
    """Returns next earnings date (datetime) or None if unknown. Cached 12h."""
    now = _time.time()
    if ticker in self._earnings_cache:
        cached = self._earnings_cache[ticker]
        if now - cached["cached_at"] < self._earnings_ttl:
            return cached["earnings_date"]
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is not None and not cal.empty:
            if isinstance(cal, pd.DataFrame):
                earnings_date = pd.Timestamp(cal.iloc[0, 0]).to_pydatetime()
            else:
                earnings_date = pd.Timestamp(cal.get("Earnings Date", [None])[0]).to_pydatetime()
            self._earnings_cache[ticker] = {"earnings_date": earnings_date, "cached_at": now}
            return earnings_date
    except Exception:
        pass
    self._earnings_cache[ticker] = {"earnings_date": None, "cached_at": now}
    return None
```

**Add method `DataCache.days_until_earnings(self, ticker)`:**
```python
def days_until_earnings(self, ticker):
    """Returns days until next earnings. None if unknown."""
    from datetime import datetime, timezone
    earnings = self.get_earnings_date(ticker)
    if earnings is None:
        return None
    now = datetime.now(timezone.utc)
    if earnings.tzinfo is None:
        from zoneinfo import ZoneInfo
        earnings = earnings.replace(tzinfo=ZoneInfo("America/New_York"))
    delta = (earnings - now).days
    return max(0, delta)
```

---

### 2C. Integrate News + Earnings into Trading Logic

#### MODIFY `live_trader.py`

**Modify `scan_and_buy()` — add news + earnings gate AFTER sector check, BEFORE execute_buy:**

In the `for ticker, score, reasons, row, atr, rs, fundies in candidates:` loop (~line 166), after the sector concentration check, add:

```python
# ── Earnings calendar gate ──
days_to_earn = _cache.days_until_earnings(ticker)
if days_to_earn is not None and days_to_earn <= 3:
    print(f"  Skip {ticker}: earnings in {days_to_earn} days (binary risk)")
    continue

# ── News sentiment gate ──
news = _cache.get_news_sentiment(ticker)
if news["sentiment"] == "DANGER":
    print(f"  BLOCKED {ticker}: {news['sentiment']} — {news.get('top_headline', 'N/A')}")
    continue
score += news["adjustment"]
if news["adjustment"] != 0:
    reasons["news"] = f"News: {news['sentiment']} ({news['adjustment']:+.1f})"
if score < 5:
    print(f"  Skip {ticker}: score dropped to {score:.1f}/8 after news penalty")
    continue
```

Update the `signals` dict to include news data:
```python
signals["news_sentiment"] = news["sentiment"]
signals["news_adjustment"] = news["adjustment"]
signals["days_to_earnings"] = days_to_earn
```

**Modify `update_holdings()` — pre-earnings exit for held positions:**

In the swing position loop, after fetching the price and before `check_exits()`, add:

```python
# Pre-earnings safety: reduce to half size if earnings within 2 days
days_to_earn = _cache.days_until_earnings(ticker)
if days_to_earn is not None and days_to_earn <= 2 and not pos.get("earnings_reduced"):
    half_qty = pos["qty"] // 2
    if half_qty > 0:
        pnl = pf.execute_sell(wallet, ticker, price, half_qty, f"Pre-earnings reduce ({days_to_earn}d)")
        print(f"  >> PRE-EARNINGS: Reduced {ticker} by {half_qty} sh (earnings in {days_to_earn}d) | PnL: ${pnl:.2f}")
        if ticker in wallet["holdings"]:
            wallet["holdings"][ticker]["earnings_reduced"] = True
        continue  # Skip normal exit check this cycle
```

**Modify `premarket_warmup()` — add news column to briefing table:**

For each candidate in the briefing, add:
```python
news = _cache.get_news_sentiment(ticker)
days_to_earn = _cache.days_until_earnings(ticker)
earn_str = f"{days_to_earn}d" if days_to_earn is not None else "—"
news_str = f"{news['sentiment']}" if news else "—"
```
Include `news_str` and `earn_str` columns in the printed briefing table.

---

### 2D. Pyramid Into Winners

#### MODIFY `portfolio.py`

**Modify `check_exits()` — add pyramid flag after TP1:**

In the TP1 section, after setting `pos["tp1_hit"] = True` and `pos["sl"] = pos["entry_price"]`, add:
```python
pos["pyramid_eligible"] = True  # Flag for live_trader to check
```

#### MODIFY `live_trader.py`

**Add new function `check_pyramids(wallet)` after `update_holdings()`:**

```python
def check_pyramids(wallet):
    """Check if any TP1-hit positions qualify for a pyramid add."""
    for ticker, pos in list(wallet["holdings"].items()):
        if not pos.get("pyramid_eligible") or pos.get("pyramided"):
            continue
        if pos.get("is_baseline"):
            continue

        # Re-score the stock with fresh data
        row = _cache.get_latest_row(ticker)
        if row is None:
            continue
        rs = _cache.get_relative_strength(ticker)
        vol_contract = check_volume_contraction(_cache.get(ticker))
        fundies = _cache.get_fundamentals(ticker)
        daily_sma50 = _cache.get_daily_sma50(ticker)
        score, reasons = check_buy_signal_detailed(row, rs, vol_contract, fundies, daily_sma50)

        if score >= 5:
            atr = _cache.get_atr(ticker)
            price = pos.get("last_price", pos["entry_price"])
            pyramid_cost = pos["initial_qty"] * pos["entry_price"] * 0.5
            pyramid_qty = int(pyramid_cost / price)
            if pyramid_qty > 0 and wallet["cash"] > pyramid_qty * price:
                fee = pyramid_qty * price * pf.SLIPPAGE_PCT
                cost = pyramid_qty * price * (1 + pf.SLIPPAGE_PCT)
                wallet["cash"] -= cost
                wallet["total_fees"] = wallet.get("total_fees", 0) + fee
                old_cost = pos["qty"] * pos["entry_price"]
                new_cost = pyramid_qty * price
                total_qty = pos["qty"] + pyramid_qty
                pos["entry_price"] = round((old_cost + new_cost) / total_qty, 4)
                pos["qty"] = total_qty
                pos["pyramided"] = True
                if atr:
                    pos["sl"] = round(price - pf.ATR_STOP_MULTIPLIER * atr, 2)
                    pos["tp2"] = round(price + pf.ATR_TP2_MULTIPLIER * atr, 2)
                    pos["tp3"] = round(price + pf.ATR_TP3_MULTIPLIER * atr, 2)
                wallet["history"].append({
                    "Ticker": ticker, "Time": pf.now_str(), "Action": "BUY",
                    "Price": price, "Qty": pyramid_qty, "PnL": 0, "PnL_Pct": 0,
                    "Fee": round(fee, 2), "Reason": f"Pyramid add (score {score}/8)",
                })
                print(f"  >> PYRAMID: Added {pyramid_qty} sh of {ticker} @ ${price:.2f} (Score: {score}/8)")
```

**Call `check_pyramids(wallet)` in `run_live_cycle()`** after `update_holdings(wallet)` (step 3.5).

---

## Phase 3: Dashboard + Analytics Polish

### 3A. Dashboard Enhancements

#### MODIFY `live_trader.py` — `update_dashboard_html()`

Add to the dashboard HTML:

1. **Fee summary row:** Show `Gross PnL`, `Fees`, `Net PnL`
2. **Baseline section:** Show QQQ baseline position, current value, unrealized PnL
3. **Earnings flags:** Next to each held position, show days until earnings if < 7
4. **News sentiment badge:** For each position, show colored badge (red=DANGER, yellow=NEG, green=POS, white=NEUTRAL)

### 3B. Performance Analytics

#### MODIFY `live_trader.py` — `--status` handler

Add these metrics to the status display:
- **Sharpe-like ratio:** `(avg_daily_return / std_daily_return) * sqrt(252)` from equity curve
- **Max drawdown:** From equity curve history
- **Average hold time:** From trade history timestamps
- **Best/Worst trade:** From realized PnL
- **Fee drag %:** `total_fees / initial_capital * 100`

---

## Verification Plan

### After Phase 1
1. Run `python live_trader.py --status` → verify:
   - Swing count shown separately from baseline
   - Total fees displayed
   - Baseline QQQ shown if idle cash was deployed
2. Check `wallet.json` → verify `total_fees` field exists
3. Run `--loop` for one cycle → verify baseline deploys on first cycle and fees are tracked

### After Phase 2
1. Run `python -c "from indicators import DataCache; c = DataCache(); print(c.get_news_sentiment('AAPL'))"` → verify FinBERT output
2. Run `python -c "from indicators import DataCache; c = DataCache(); print(c.days_until_earnings('AAPL'))"` → verify earnings data
3. Run `--warmup` → verify news sentiment and earnings columns in briefing table
4. During market hours, observe that stocks near earnings are skipped with clear log messages

### After Phase 3
- Open `dashboard.html` → verify fee summary, baseline section, earnings flags, news badges visible

---

## Risk Considerations

> **WARNING — FinBERT model size:** ~1.3GB download on first run. The model loads lazily — first call takes ~15-30 seconds, subsequent calls are instant. If the system runs out of memory, fall back to keyword-based sentiment.

> **WARNING — Yahoo Finance rate limits:** News and earnings calendar API calls go through `yfinance`. Cache aggressively (2h for news, 12h for earnings). Never call these in the hot loop for all 266 tickers — only call for the 10-15 candidates that pass Phase 2 scoring.

> **IMPORTANT — Wallet migration:** Existing `wallet.json` from v2 won't have `total_fees` or `is_baseline` fields. All code must use `.get()` with defaults: `wallet.get("total_fees", 0)`, `pos.get("is_baseline", False)`. Never crash on missing fields.
