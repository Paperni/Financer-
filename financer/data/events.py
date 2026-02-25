"""Events adapter — earnings dates and event flags.

Never guesses.  Returns empty results when data is unavailable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from financer.models.events import EventFlags

# How many calendar days before/after earnings to set blackout
EARNINGS_BLACKOUT_DAYS: int = 3


def _default_provider(ticker: str) -> list[date]:
    """Fetch earnings dates from yfinance calendar.  Imported lazily."""
    import yfinance as yf  # noqa: PLC0415

    try:
        cal = yf.Ticker(ticker).calendar
    except Exception:
        return []

    if cal is None:
        return []

    dates: list[date] = []

    # yfinance returns either a DataFrame or a dict depending on version
    if hasattr(cal, "iloc"):
        # DataFrame: index = labels, columns = dates
        # Look for "Earnings Date" row
        for col in cal.columns:
            try:
                val = cal[col].iloc[0] if len(cal) > 0 else None
                if val is not None and hasattr(val, "date"):
                    dates.append(val.date() if callable(val.date) else val.date)
                elif val is not None:
                    dates.append(datetime.fromisoformat(str(val)).date())
            except Exception:
                continue
    elif isinstance(cal, dict):
        for key in ("Earnings Date", "earningsDate"):
            vals = cal.get(key, [])
            if not isinstance(vals, list):
                vals = [vals]
            for v in vals:
                try:
                    if hasattr(v, "date"):
                        dates.append(v.date() if callable(v.date) else v.date)
                    else:
                        dates.append(datetime.fromisoformat(str(v)).date())
                except Exception:
                    continue

    return dates


def get_earnings_dates(
    ticker: str,
    start: str = "",
    end: str = "",
    provider: Callable[[str], list[date]] | None = None,
) -> list[date]:
    """Return known earnings dates for a ticker within [start, end].

    Returns an empty list when data is unavailable — never guesses.
    """
    fetch = provider or _default_provider
    try:
        all_dates = fetch(ticker)
    except Exception:
        return []

    if not start and not end:
        return sorted(all_dates)

    start_d = datetime.fromisoformat(start).date() if start else date.min
    end_d = datetime.fromisoformat(end).date() if end else date.max

    return sorted(d for d in all_dates if start_d <= d <= end_d)


def get_event_flags(
    ticker: str,
    asof: str = "",
    earnings_dates: list[date] | None = None,
) -> EventFlags:
    """Build EventFlags for a ticker at a point in time.

    If ``earnings_dates`` is provided, checks whether any fall within
    ``EARNINGS_BLACKOUT_DAYS`` of ``asof``.  All other flags default
    to False — no guessing.
    """
    flags = EventFlags()

    if not asof or earnings_dates is None:
        return flags

    try:
        asof_d = datetime.fromisoformat(asof).date()
    except (ValueError, TypeError):
        return flags

    in_blackout = any(
        abs((d - asof_d).days) <= EARNINGS_BLACKOUT_DAYS
        for d in earnings_dates
    )

    if in_blackout:
        flags.earnings_blackout[ticker] = True

    return flags
