"""Pure position-sizing math — no side effects, no I/O.

Constants are duplicated from portfolio.py intentionally so that the
financer/ package has zero imports from root-level legacy scripts.
Once portfolio.py migrates into financer/, these become the single source.
"""

from __future__ import annotations

from .enums import Regime

# ── Constants (mirrored from portfolio.py) ───────────────────────────────────
ATR_STOP_MULTIPLIER: float = 1.5
FALLBACK_STOP_PCT: float = 0.05
SLIPPAGE_PCT: float = 0.0005
CAUTIOUS_SIZE_MULT: float = 0.75

RISK_BY_SCORE: dict[int, float] = {
    5: 0.010,   # 1.0% equity at risk
    6: 0.015,   # 1.5%
    7: 0.020,   # 2.0%
    8: 0.025,   # 2.5%
}

MAX_POSITION_BY_SCORE: dict[int, float] = {
    5: 0.05,    # 5% of equity max notional
    6: 0.07,    # 7%
    7: 0.085,   # 8.5%
    8: 0.10,    # 10%
}

# ── TP multipliers (relative to ATR_STOP_MULTIPLIER) ────────────────────────
_TP1_RATIO: float = 2.0 / 1.5   # ~1.333
_TP2_RATIO: float = 3.0 / 1.5   # 2.0
_TP3_RATIO: float = 4.0 / 1.5   # ~2.667


def position_size(
    price: float,
    atr: float | None,
    equity: float,
    regime: Regime = Regime.RISK_ON,
    score: int = 5,
    risk_per_trade_pct: float | None = None,
) -> dict[str, float | int | None]:
    """Compute position qty, stop-loss, and take-profit levels.

    Returns a dict with keys:
        qty, sl, tp1, tp2, tp3, risk_per_share, atr_used
    """
    if price <= 0 or equity <= 0:
        return {
            "qty": 0, "sl": 0.0, "tp1": 0.0, "tp2": 0.0, "tp3": 0.0,
            "risk_per_share": 0.0, "atr_used": atr,
        }

    # Clamp score to valid range
    score = max(5, min(8, score))

    risk_pct = risk_per_trade_pct if risk_per_trade_pct is not None else RISK_BY_SCORE[score]
    cap_pct = MAX_POSITION_BY_SCORE[score]

    # Stop distance
    if atr and atr > 0:
        stop_distance = atr * ATR_STOP_MULTIPLIER
    else:
        stop_distance = price * FALLBACK_STOP_PCT

    # Qty by risk budget vs qty by notional cap — take the smaller
    risk_budget = equity * risk_pct
    qty_by_risk = int(risk_budget / stop_distance) if stop_distance > 0 else 0
    qty_by_cap = int((equity * cap_pct) / price)
    qty = max(1, min(qty_by_risk, qty_by_cap))

    # Regime adjustment
    if regime == Regime.CAUTIOUS:
        qty = max(1, int(qty * CAUTIOUS_SIZE_MULT))
    elif regime == Regime.RISK_OFF:
        qty = 0

    # Price levels
    sl = round(price - stop_distance, 2)
    tp1 = round(price + stop_distance * _TP1_RATIO, 2)
    tp2 = round(price + stop_distance * _TP2_RATIO, 2)
    tp3 = round(price + stop_distance * _TP3_RATIO, 2)

    return {
        "qty": qty,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_per_share": round(stop_distance, 4),
        "atr_used": atr,
    }


# ── Entry readiness check ───────────────────────────────────────────────────

# The columns an engine must verify are non-NaN before entering.
# Imported from financer.features.build at runtime would create a circular
# dependency, so we duplicate the list here (single source is build.py).
_ENTRY_REQUIRED: tuple[str, ...] = (
    "atr_14",
    "sma_50",
    "above_50",
    "regime",
    "rs_20",
)


def check_entry_readiness(row: dict[str, object]) -> tuple[bool, list[str]]:
    """Check whether a feature row has all required fields for entry.

    Returns (ready, missing) where *missing* lists column names that
    are NaN or absent.  If not ready, the engine must score the bar as
    0 and skip entry.

    This is a pure function — no side effects.
    """
    import math  # noqa: PLC0415  (stdlib, no cost)

    missing: list[str] = []
    for col in _ENTRY_REQUIRED:
        val = row.get(col)
        if val is None:
            missing.append(col)
            continue
        try:
            if isinstance(val, float) and math.isnan(val):
                missing.append(col)
        except (TypeError, ValueError):
            pass  # non-numeric (e.g. Regime enum string) — OK

    return (len(missing) == 0, missing)
