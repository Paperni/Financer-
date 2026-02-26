"""
Shared technical indicator engine with data caching.

Provides:
- DataCache: bulk download + incremental refresh for 250+ tickers
- Full indicator suite: SMA, Wilder RSI, MACD, ATR, Volume MA, Relative Strength
- 8-point entry scoring with market regime gate (includes PEG valuation)
- Momentum scoring for asset selection (draft phase)
"""

import time as _time
import numpy as np
import pandas as pd
import yfinance as yf


# ── Data cache ───────────────────────────────────────────────────────────────
class DataCache:
    """Caches yfinance hourly data between cycles. Only fetches new bars on refresh."""

    def __init__(self):
        self._hourly = {}       # ticker -> DataFrame (with indicators)
        self._daily = {}        # ticker -> DataFrame (for relative strength calc)
        self._fundamentals = {} # ticker -> {pe, revenue_growth, fetched_at}
        self._last_fetch = 0.0
        self._fetch_interval = 55  # min seconds between refreshes
        self._fundamentals_ttl = 6 * 3600  # cache fundamentals for 6 hours
        self._spy_sma50 = None  # cached SPY SMA-50 for regime check
        self._spy_sma200 = None
        self._spy_close = None
        self._spy_return_20d = None  # SPY 20-day return for relative strength
        # News sentiment (FinBERT)
        self._news_cache = {}       # ticker -> {sentiment, score, adjustment, ...}
        self._news_ttl = 2 * 3600   # cache news for 2 hours
        self._finbert = None
        self._finbert_tokenizer = None
        # Earnings calendar
        self._earnings_cache = {}   # ticker -> {earnings_date, cached_at}
        self._earnings_ttl = 12 * 3600  # cache earnings dates for 12 hours

    def bulk_download(self, tickers, period="1mo", interval="1h"):
        """Full download for all tickers + daily SPY for regime/RS."""
        now = _time.time()
        if now - self._last_fetch < self._fetch_interval and self._hourly:
            return

        # 1. Hourly data for trading signals
        print(f"  [Cache] Downloading {len(tickers)} tickers ({interval})...")
        try:
            data = yf.download(
                tickers, period=period, interval=interval,
                group_by="ticker", progress=False, threads=True,
            )
        except Exception as e:
            print(f"  [Cache] Download error: {e}")
            return

        is_multi = len(tickers) > 1
        updated = 0

        for ticker in tickers:
            try:
                df = data[ticker].copy() if is_multi else data.copy()
                df = df.dropna(how="all")
                if df.empty:
                    continue
                df = calculate_indicators(df)
                if len(df) >= 50:
                    self._hourly[ticker] = df
                    updated += 1
            except (KeyError, IndexError, TypeError):
                continue

        # 2. Daily data for SPY regime + relative strength
        self._update_daily_context(tickers)

        self._last_fetch = _time.time()
        print(f"  [Cache] Updated {updated}/{len(tickers)} tickers.")

    def _update_daily_context(self, tickers):
        """Download daily data for SPY (regime) and all tickers (relative strength)."""
        # Always include SPY for regime check
        daily_tickers = list(set(["SPY"] + tickers))
        try:
            daily = yf.download(
                daily_tickers, period="6mo", interval="1d",
                group_by="ticker", progress=False, threads=True,
            )
        except Exception as e:
            print(f"  [Cache] Daily context error: {e}")
            return

        is_multi = len(daily_tickers) > 1

        for ticker in daily_tickers:
            try:
                df = daily[ticker].copy() if is_multi else daily.copy()
                df = df.dropna(how="all")
                if not df.empty:
                    self._daily[ticker] = df
            except (KeyError, IndexError, TypeError):
                continue

        # Cache SPY regime data
        if "SPY" in self._daily:
            spy = self._daily["SPY"]
            if len(spy) >= 200:
                self._spy_sma50 = float(spy["Close"].rolling(50).mean().iloc[-1])
                self._spy_sma200 = float(spy["Close"].rolling(200).mean().iloc[-1])
            elif len(spy) >= 50:
                self._spy_sma50 = float(spy["Close"].rolling(50).mean().iloc[-1])
                self._spy_sma200 = None
            self._spy_close = float(spy["Close"].iloc[-1])

            # SPY 20-day return
            if len(spy) >= 21:
                self._spy_return_20d = (
                    float(spy["Close"].iloc[-1]) / float(spy["Close"].iloc[-21]) - 1
                )

    def refresh(self, tickers, period="5d", interval="1h"):
        """Lightweight incremental refresh."""
        if not self._hourly:
            self.bulk_download(tickers)
            return

        now = _time.time()
        if now - self._last_fetch < self._fetch_interval:
            return

        print(f"  [Cache] Refreshing {len(tickers)} tickers (last {period})...")
        try:
            data = yf.download(
                tickers, period=period, interval=interval,
                group_by="ticker", progress=False, threads=True,
            )
        except Exception as e:
            print(f"  [Cache] Refresh error: {e}")
            return

        is_multi = len(tickers) > 1
        refreshed = 0

        for ticker in tickers:
            try:
                new_df = data[ticker].copy() if is_multi else data.copy()
                new_df = new_df.dropna(how="all")
                if new_df.empty:
                    continue

                if ticker in self._hourly:
                    old_df = self._hourly[ticker]
                    ind_cols = [c for c in old_df.columns if c not in
                                ("Open", "High", "Low", "Close", "Volume")]
                    old_clean = old_df.drop(columns=ind_cols, errors="ignore")
                    combined = pd.concat([old_clean, new_df])
                    combined = combined[~combined.index.duplicated(keep="last")]
                    combined = combined.sort_index()
                else:
                    combined = new_df

                combined = calculate_indicators(combined)
                if len(combined) >= 50:
                    self._hourly[ticker] = combined
                    refreshed += 1
            except (KeyError, IndexError, TypeError):
                continue

        # Refresh daily context too
        self._update_daily_context(tickers)

        self._last_fetch = _time.time()
        print(f"  [Cache] Refreshed {refreshed} tickers.")

    def get(self, ticker):
        return self._hourly.get(ticker)

    def get_latest_price(self, ticker):
        df = self._hourly.get(ticker)
        if df is not None and not df.empty:
            return float(df["Close"].dropna().iloc[-1])
        return None

    def get_latest_row(self, ticker):
        df = self._hourly.get(ticker)
        if df is not None and not df.empty:
            return df.iloc[-1]
        return None

    def get_relative_strength(self, ticker):
        """20-day return of ticker vs SPY. >1.0 means outperforming."""
        if self._spy_return_20d is None:
            return None
        df = self._daily.get(ticker)
        if df is None or len(df) < 21:
            return None
        stock_return = float(df["Close"].iloc[-1]) / float(df["Close"].iloc[-21]) - 1
        # Outperformance vs SPY: RS > 1.0 means stock beat SPY.
        # Using subtraction formula (not division) to handle zero/negative SPY returns
        # without division-by-zero or sign discontinuity.
        return stock_return - self._spy_return_20d + 1

    def get_atr(self, ticker):
        """Get latest ATR value for a ticker from hourly data."""
        df = self._hourly.get(ticker)
        if df is not None and "ATR" in df.columns:
            series = df["ATR"].dropna()
            if len(series) == 0:
                return None
            val = series.iloc[-1]
            return float(val) if not pd.isna(val) else None
        return None

    def get_daily_sma50(self, ticker):
        """Get daily SMA-50 for a ticker (50 trading days = ~2.5 months trend)."""
        df = self._daily.get(ticker)
        if df is not None and len(df) >= 50:
            sma = df["Close"].rolling(50).mean().iloc[-1]
            return float(sma) if not pd.isna(sma) else None
        return None

    def get_fundamentals(self, ticker):
        """Lazy-fetch P/E and revenue growth from yfinance. Cached for 6 hours.

        Returns dict with 'pe' and 'revenue_growth' (as percentage, e.g. 60 for 60%),
        or None if data unavailable.
        """
        now = _time.time()
        cached = self._fundamentals.get(ticker)
        if cached and (now - cached["fetched_at"]) < self._fundamentals_ttl:
            return cached

        try:
            info = yf.Ticker(ticker).info
            pe = info.get("trailingPE") or info.get("forwardPE")
            rev_growth = info.get("revenueGrowth")  # decimal, e.g. 0.60 for 60%
            sector = info.get("sector", "Unknown")

            result = {
                "pe": float(pe) if pe is not None else None,
                "revenue_growth": float(rev_growth) * 100 if rev_growth is not None else None,
                "sector": sector,
                "fetched_at": now,
            }

            self._fundamentals[ticker] = result
            return result
        except Exception:
            return None

    def get_market_regime(self):
        """Returns market regime based on SPY position vs moving averages.

        Returns:
            'RISK_ON'   - SPY > SMA-50 and SMA-200: Full trading
            'CAUTIOUS'  - SPY > SMA-200 but < SMA-50: Half size, tighter stops
            'RISK_OFF'  - SPY < SMA-200: No new buys
            'UNKNOWN'   - Not enough data
        """
        if self._spy_close is None or self._spy_sma50 is None:
            return "UNKNOWN"

        if self._spy_sma200 is not None:
            if self._spy_close > self._spy_sma50 and self._spy_close > self._spy_sma200:
                return "RISK_ON"
            elif self._spy_close > self._spy_sma200:
                return "CAUTIOUS"
            else:
                return "RISK_OFF"
        else:
            # Only have SMA-50
            return "RISK_ON" if self._spy_close > self._spy_sma50 else "CAUTIOUS"

    # ── Earnings calendar ──────────────────────────────────────────────────────
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
            if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
                if isinstance(cal, pd.DataFrame):
                    earnings_date = pd.Timestamp(cal.iloc[0, 0]).to_pydatetime()
                elif isinstance(cal, dict):
                    dates = cal.get("Earnings Date", [])
                    if dates:
                        earnings_date = pd.Timestamp(dates[0]).to_pydatetime()
                    else:
                        earnings_date = None
                else:
                    earnings_date = None
                self._earnings_cache[ticker] = {"earnings_date": earnings_date, "cached_at": now}
                return earnings_date
        except Exception:
            pass
        self._earnings_cache[ticker] = {"earnings_date": None, "cached_at": now}
        return None

    def days_until_earnings(self, ticker):
        """Returns days until next earnings. None if unknown."""
        from datetime import datetime, timezone
        earnings = self.get_earnings_date(ticker)
        if earnings is None:
            return None
        # Normalize both to UTC for consistent arithmetic.
        # yfinance often returns UTC-aware or naive datetimes; treat naive as UTC.
        if earnings.tzinfo is None:
            earnings = earnings.replace(tzinfo=timezone.utc)
        else:
            earnings = earnings.astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        delta = (earnings - now_utc).days
        return max(0, delta)

    # ── FinBERT news sentiment ────────────────────────────────────────────────
    def _load_finbert(self):
        """Lazy-load FinBERT model + tokenizer."""
        if self._finbert is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            model_name = "ProsusAI/finbert"
            self._finbert_tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._finbert = AutoModelForSequenceClassification.from_pretrained(model_name)
            self._finbert.eval()
        return self._finbert, self._finbert_tokenizer

    def get_news_sentiment(self, ticker):
        """Analyze recent news headlines with FinBERT. Returns sentiment dict. Cached 2h."""
        now = _time.time()
        if ticker in self._news_cache:
            cached = self._news_cache[ticker]
            if now - cached["cached_at"] < self._news_ttl:
                return cached

        neutral = {"sentiment": "NEUTRAL", "score": 0.0, "adjustment": 0,
                    "headline_count": 0, "top_headline": "", "cached_at": now}
        try:
            import torch
            t = yf.Ticker(ticker)
            news_items = t.news
            if not news_items:
                self._news_cache[ticker] = neutral
                return neutral

            # Filter to last 72 hours and extract headlines
            from datetime import datetime, timezone
            cutoff_72h = now - 72 * 3600
            cutoff_24h = now - 24 * 3600
            headlines = []
            for item in news_items:
                # Handle both old format (flat) and new format (nested under 'content')
                content = item.get("content", item)
                title = content.get("title", "")
                if not title:
                    continue
                # Parse publish time — could be epoch (old) or ISO string (new)
                pub_time = item.get("providerPublishTime", 0)
                if not pub_time:
                    pub_date_str = content.get("pubDate", "")
                    if pub_date_str:
                        try:
                            dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                            pub_time = dt.timestamp()
                        except Exception:
                            pub_time = now  # Assume recent if can't parse
                if pub_time < cutoff_72h:
                    continue
                weight = 1.0 if pub_time >= cutoff_24h else 0.5
                headlines.append((title, weight))

            if not headlines:
                self._news_cache[ticker] = neutral
                return neutral

            # Run FinBERT
            model, tokenizer = self._load_finbert()
            weighted_scores = []
            max_impact = 0
            top_headline = ""

            for title, weight in headlines:
                inputs = tokenizer(title, return_tensors="pt", truncation=True, max_length=128)
                with torch.no_grad():
                    outputs = model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=1)
                pos, neg, neu = probs[0].tolist()
                score = (pos - neg) * weight
                weighted_scores.append(score)
                impact = abs(pos - neg)
                if impact > max_impact:
                    max_impact = impact
                    top_headline = title

            net_sentiment = sum(weighted_scores) / len(weighted_scores)

            # Classify
            if net_sentiment < -0.5:
                sentiment, adjustment = "DANGER", -99
            elif net_sentiment < -0.2:
                sentiment, adjustment = "NEGATIVE", -1.0
            elif net_sentiment > 0.2:
                sentiment, adjustment = "POSITIVE", 0.5
            else:
                sentiment, adjustment = "NEUTRAL", 0

            result = {
                "sentiment": sentiment,
                "score": round(net_sentiment, 3),
                "adjustment": adjustment,
                "headline_count": len(headlines),
                "top_headline": top_headline,
                "cached_at": now,
            }
            self._news_cache[ticker] = result
            return result

        except Exception as e:
            # Never block a trade because news system failed
            neutral["_error"] = str(e)
            self._news_cache[ticker] = neutral
            return neutral

    @property
    def tickers(self):
        return list(self._hourly.keys())

    def clear(self):
        self._hourly.clear()
        self._daily.clear()
        self._fundamentals.clear()
        self._news_cache.clear()
        self._earnings_cache.clear()
        self._last_fetch = 0.0


# ── Indicator calculations ───────────────────────────────────────────────────
def calculate_indicators(df, sma_period=50, rsi_period=14, atr_period=14):
    """Calculate SMA, Wilder RSI, MACD, ATR, and Volume MA."""
    if len(df) < sma_period:
        return df

    # SMA-50
    df["SMA_50"] = df["Close"].rolling(window=sma_period).mean()

    # Wilder RSI
    df["RSI"] = wilder_rsi(df["Close"], period=rsi_period)

    # MACD (12, 26, 9)
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    # ATR (Average True Range — Wilder's method)
    df["ATR"] = wilder_atr(df, period=atr_period)

    # Volume moving average (20-period)
    df["Vol_MA"] = df["Volume"].rolling(window=20).mean()

    # Volume of last 3 bars (for pullback contraction check)
    df["Vol_3bar"] = df["Volume"].rolling(window=3).mean()

    return df


def wilder_rsi(close, period=14):
    """Wilder's RSI using exponential (Wilder) smoothing."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    for i in range(period, len(close)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def wilder_atr(df, period=14):
    """Average True Range using Wilder's smoothing method."""
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Wilder smoothing (same as RSI smoothing)
    atr = tr.rolling(window=period).mean()
    for i in range(period, len(tr)):
        atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period

    return atr


def calculate_momentum_score(df):
    """Score an asset by risk-adjusted momentum (Sharpe-like).
    Used by smart_trader's draft phase."""
    if df.empty or len(df) < 50:
        return -999

    close = df["Close"].iloc[-1]
    lookback = min(len(df) - 1, 126)
    start_price = df["Close"].iloc[-lookback]
    roc = (close - start_price) / start_price

    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    vol = log_ret.std() * np.sqrt(252)

    sma50 = df["Close"].rolling(50).mean().iloc[-1]
    trend_score = 1.0 if close > sma50 else 0.5

    return (roc / max(vol, 0.1)) * trend_score


# ── Entry signal scoring (Institutional Swing — 8 points) ───────────────────
def score_setup(row, relative_strength=None, volume_contracting=None, fundamentals=None,
                daily_sma50=None):
    """Score a potential entry from 0-8 based on institutional-grade confirmations.

    The 8 criteria:
      1. Uptrend: price > daily SMA-50 (50 trading days, real trend)
      2. RSI pullback zone: 30-45 (dip in uptrend, not free-fall)
      3. MACD histogram positive or increasing (momentum turning)
      4. Volume conviction: reversal bar volume > 20-period average
      5. Reversal candle: close > open with meaningful body (>0.3%)
      6. Relative strength: outperforming SPY over 20 days
      7. Quiet pullback: volume contracted during dip (last 3 bars < avg)
      8. PEG valuation: P/E <= revenue growth rate (Peter Lynch rule)

    Returns (score, reasons_dict).
    """
    score = 0
    reasons = {}

    try:
        close = float(row["Close"])
        opn = float(row["Open"])

        # 1. Uptrend (daily SMA-50 = 50 trading days, preferred over hourly)
        sma50 = daily_sma50  # use daily if provided
        if sma50 is None and not pd.isna(row.get("SMA_50")):
            sma50 = float(row["SMA_50"])  # fallback to hourly for backtesting
        if sma50 is not None and close > sma50:
            pct_above = (close / sma50 - 1) * 100
            score += 1
            reasons["trend"] = f"Above Daily SMA50 (+{pct_above:.1f}%)"

        # 2. RSI pullback zone (gradient: deeper dip = more conviction)
        if not pd.isna(row.get("RSI")):
            rsi = float(row["RSI"])
            if 30 <= rsi <= 35:
                score += 1
                reasons["rsi"] = f"RSI {rsi:.1f} (sweet spot pullback)"
            elif 35 < rsi <= 40:
                score += 0.75
                reasons["rsi"] = f"RSI {rsi:.1f} (decent pullback)"
            elif 40 < rsi <= 45:
                score += 0.5
                reasons["rsi"] = f"RSI {rsi:.1f} (shallow dip)"
            elif 25 <= rsi < 30:
                score += 0.5
                reasons["rsi"] = f"RSI {rsi:.1f} (deeply oversold — caution)"

        # 3. MACD momentum turning up
        if not pd.isna(row.get("MACD_Hist")):
            hist = float(row["MACD_Hist"])
            if hist > 0:
                score += 1
                reasons["macd"] = f"MACD Hist +{hist:.4f} (bullish momentum)"

        # 4. Volume conviction on reversal bar
        if not pd.isna(row.get("Vol_MA")) and float(row["Vol_MA"]) > 0:
            vol_ratio = float(row["Volume"]) / float(row["Vol_MA"])
            if vol_ratio > 1.2:
                score += 1
                reasons["volume"] = f"Vol {vol_ratio:.1f}x avg (strong conviction)"
            elif vol_ratio > 1.0:
                score += 0.5
                reasons["volume"] = f"Vol {vol_ratio:.1f}x avg (mild conviction)"

        # 5. Reversal candle (meaningful green body)
        if close > opn:
            candle_pct = (close - opn) / opn * 100
            if candle_pct >= 0.3:
                score += 1
                reasons["candle"] = f"+{candle_pct:.2f}% reversal candle"

        # 6. Relative strength vs SPY
        if relative_strength is not None:
            if relative_strength > 1.2:
                score += 1
                reasons["rs"] = f"RS {relative_strength:.2f}x SPY (strong leader)"
            elif relative_strength > 1.0:
                score += 0.5
                reasons["rs"] = f"RS {relative_strength:.2f}x SPY (outperforming)"

        # 7. Quiet pullback (volume contraction before reversal)
        if volume_contracting is not None and volume_contracting:
            score += 1
            reasons["quiet_dip"] = "Vol contracted during pullback (institutional pattern)"

        # 8. PEG valuation: P/E <= revenue growth rate (Peter Lynch)
        if fundamentals is not None:
            pe = fundamentals.get("pe")
            rev_g = fundamentals.get("revenue_growth")  # already in %, e.g. 60 for 60%
            if pe is not None and rev_g is not None and rev_g > 0:
                if pe <= rev_g:
                    score += 1
                    reasons["peg"] = f"P/E {pe:.1f} <= Rev Growth {rev_g:.0f}% (PEG fair)"
                elif pe <= rev_g * 1.2:
                    score += 0.5
                    reasons["peg"] = f"P/E {pe:.1f} ~ Rev Growth {rev_g:.0f}% (PEG near fair)"

    except (KeyError, TypeError, ValueError):
        return 0, {}

    return score, reasons


# Minimum score to trigger a buy (out of 8)
MIN_ENTRY_SCORE = 5


def check_buy_signal(row, relative_strength=None, volume_contracting=None,
                     fundamentals=None, daily_sma50=None):
    """Check if setup meets minimum 5/8 institutional entry criteria."""
    score, _ = score_setup(row, relative_strength, volume_contracting, fundamentals, daily_sma50)
    return score >= MIN_ENTRY_SCORE


def check_buy_signal_detailed(row, relative_strength=None, volume_contracting=None,
                              fundamentals=None, daily_sma50=None):
    """Full scoring with reasons for logging."""
    score, reasons = score_setup(row, relative_strength, volume_contracting, fundamentals, daily_sma50)
    return score >= MIN_ENTRY_SCORE, score, reasons


def check_volume_contraction(df):
    """Check if the last 3 bars had below-average volume (quiet pullback).
    Returns True if average volume of last 3 bars is below 20-period average."""
    if df is None or len(df) < 20:
        return False
    try:
        vol_3bar = float(df["Vol_3bar"].iloc[-1])
        vol_avg = float(df["Vol_MA"].iloc[-1])
        if pd.isna(vol_3bar) or pd.isna(vol_avg) or vol_avg == 0:
            return False
        return vol_3bar < vol_avg * 0.85  # 15%+ below average = quiet
    except (KeyError, IndexError):
        return False
