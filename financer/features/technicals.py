"""Technical indicator calculations — pure DataFrame in, DataFrame out.

All functions accept a normalized bars DataFrame (lowercase columns,
UTC DatetimeIndex) and return/mutate the same frame with new columns.

Formulas match the existing indicators.py (Wilder smoothing for RSI/ATR).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── ATR (Wilder's smoothing) ────────────────────────────────────────────────

def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add ``atr_14`` column using Wilder's smoothing."""
    high, low = df["high"], df["low"]
    prev_close = df["close"].shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(window=period).mean().copy()
    for i in range(period, len(tr)):
        atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period

    df[f"atr_{period}"] = atr
    return df


# ── SMA ─────────────────────────────────────────────────────────────────────

def add_sma(df: pd.DataFrame, period: int = 50) -> pd.DataFrame:
    """Add ``sma_{period}`` and ``above_{period}`` columns."""
    col = f"sma_{period}"
    df[col] = df["close"].rolling(window=period).mean()
    df[f"above_{period}"] = df["close"] > df[col]
    return df


def add_sma_slope(df: pd.DataFrame, period: int = 50, lookback: int = 5) -> pd.DataFrame:
    """Add ``sma{period}_slope`` — simple diff over *lookback* bars."""
    sma_col = f"sma_{period}"
    if sma_col not in df.columns:
        add_sma(df, period)
    df[f"sma{period}_slope"] = df[sma_col].diff(lookback)
    return df


# ── RSI (Wilder's smoothing) ────────────────────────────────────────────────

def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add ``rsi_14`` column using Wilder's exponential smoothing."""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean().copy()
    avg_loss = loss.rolling(window=period).mean().copy()

    for i in range(period, len(df)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss
    df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return df


# ── MACD ────────────────────────────────────────────────────────────────────

def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Add ``macd_hist`` (and ``macd``, ``macd_signal``) columns."""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


# ── ROC (Rate of Change) ───────────────────────────────────────────────────

def add_roc(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Add ``roc_{period}`` — percentage price change over *period* bars."""
    prev = df["close"].shift(period)
    df[f"roc_{period}"] = ((df["close"] - prev) / prev) * 100
    return df


# ── All technicals ──────────────────────────────────────────────────────────

def add_all_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """Add the full V1 technical feature set to a bars DataFrame."""
    add_atr(df, 14)
    add_sma(df, 50)
    add_sma(df, 200)
    add_sma_slope(df, 50, lookback=5)
    add_sma_slope(df, 200, lookback=5)
    add_rsi(df, 14)
    add_macd(df)
    add_roc(df, 20)
    return df
