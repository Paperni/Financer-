"""Fundamentals adapter — valuation inputs with quality flags.

Computes a PEG proxy and flags data-quality issues so downstream
engines can decide how much to trust the numbers.
"""

from __future__ import annotations

from typing import Any, Callable


def _default_provider(ticker: str) -> dict[str, Any]:
    """Fetch fundamentals from yfinance.  Imported lazily."""
    import yfinance as yf  # noqa: PLC0415

    info = yf.Ticker(ticker).info or {}
    return {
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "revenueGrowth": info.get("revenueGrowth"),  # decimal, e.g. 0.08
    }


def get_valuation_inputs(
    ticker: str,
    asof: str = "",
    provider: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return valuation inputs with a PEG proxy and quality flags.

    Parameters
    ----------
    ticker : str
        Instrument symbol.
    asof : str
        Reserved for future point-in-time lookups (ignored today).
    provider : callable, optional
        ``provider(ticker) -> dict`` with keys ``trailingPE``,
        ``forwardPE``, ``revenueGrowth``.

    Returns
    -------
    dict with keys: ticker, pe_ttm, pe_forward, pe_used,
    revenue_growth_pct, peg_proxy, quality_flags.
    """
    fetch = provider or _default_provider
    try:
        raw = fetch(ticker)
    except Exception:
        raw = {}

    pe_ttm = _to_float(raw.get("trailingPE"))
    pe_forward = _to_float(raw.get("forwardPE"))

    # Prefer forward P/E, fall back to trailing
    pe_used = pe_forward if pe_forward is not None else pe_ttm

    # Revenue growth as percentage (yfinance returns decimal: 0.08 → 8.0)
    raw_growth = _to_float(raw.get("revenueGrowth"))
    revenue_growth_pct: float | None = None
    if raw_growth is not None:
        revenue_growth_pct = round(raw_growth * 100.0, 2)

    # PEG proxy
    peg_proxy: float | None = None
    if pe_used is not None and revenue_growth_pct is not None and revenue_growth_pct > 0:
        peg_proxy = round(pe_used / revenue_growth_pct, 4)

    # Quality flags
    missing_pe = pe_ttm is None and pe_forward is None
    missing_growth = revenue_growth_pct is None
    negative_earnings = pe_used is not None and pe_used < 0
    outlier_growth = (
        revenue_growth_pct is not None
        and (revenue_growth_pct > 100.0 or revenue_growth_pct < -50.0)
    )

    return {
        "ticker": ticker,
        "pe_ttm": pe_ttm,
        "pe_forward": pe_forward,
        "pe_used": pe_used,
        "revenue_growth_pct": revenue_growth_pct,
        "peg_proxy": peg_proxy,
        "quality_flags": {
            "missing_pe": missing_pe,
            "missing_growth": missing_growth,
            "negative_earnings": negative_earnings,
            "outlier_growth": outlier_growth,
        },
    }


def _to_float(val: Any) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        result = float(val)
        if result != result:  # NaN check
            return None
        return result
    except (TypeError, ValueError):
        return None
