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

# ── Volatility & Kelly Parameters ───────────────────────────────────────────
TARGET_ANNUAL_VOL: float = 0.15      # 15% target annualized portfolio volatility
KELLY_MULTIPLIER: float = 0.25       # Quarter-Kelly scaling
MAX_NOTIONAL_PCT: float = 0.10       # 10% max notional cap per position

# ── TP multipliers (relative to ATR_STOP_MULTIPLIER) ────────────────────────
_TP1_RATIO: float = 2.0 / 1.5   # ~1.333
_TP2_RATIO: float = 3.0 / 1.5   # 2.0
_TP3_RATIO: float = 4.0 / 1.5   # ~2.667


class VolatilityTargetingSizer:
    """Calculates position size using inverse volatility and Quarter-Kelly scaling."""

    def __init__(
        self,
        target_annual_vol: float = TARGET_ANNUAL_VOL,
        kelly_fraction: float = KELLY_MULTIPLIER,
        max_notional_pct: float = MAX_NOTIONAL_PCT,
    ):
        self.target_annual_vol = target_annual_vol
        self.kelly_fraction = kelly_fraction
        self.max_notional_pct = max_notional_pct

    def calculate_qty(
        self, 
        price: float, 
        equity: float, 
        annualized_vol: float,
    ) -> int:
        """Compute quantity based on target vol and kelly fraction."""
        if price <= 0 or equity <= 0 or annualized_vol <= 0:
            return 0
            
        raw_weight = self.target_annual_vol / annualized_vol
        final_weight = min(raw_weight * self.kelly_fraction, self.max_notional_pct)
        target_notional = equity * final_weight
        qty = int(target_notional / price)
        
        return max(0, qty)

    def calculate_weight(self, asset_annual_vol: float) -> float:
        """Calculates theoretical portfolio weight."""
        if asset_annual_vol <= 0:
            return 0.0
        return min((self.target_annual_vol / asset_annual_vol) * self.kelly_fraction, self.max_notional_pct)


def position_size(
    price: float,
    atr: float | None,
    equity: float,
    regime: Regime = Regime.RISK_ON,
    score: int = 5,
    annualized_vol: float | None = None,
) -> dict[str, float | int | None]:
    """Compute position qty, stop-loss, and take-profit levels.

    If *annualized_vol* is provided, uses VolatilityTargetingSizer.
    Otherwise, defaults to a minimal 1% fallback risk.
    """
    if price <= 0 or equity <= 0:
        return {
            "qty": 0, "sl": 0.0, "tp1": 0.0, "tp2": 0.0, "tp3": 0.0,
            "risk_per_share": 0.0, "atr_used": atr,
        }

    # Stop distance
    if atr and atr > 0:
        stop_distance = atr * ATR_STOP_MULTIPLIER
    else:
        stop_distance = price * FALLBACK_STOP_PCT

    # Sizing Logic
    if annualized_vol is not None and annualized_vol > 0:
        sizer = VolatilityTargetingSizer()
        qty = sizer.calculate_qty(price, equity, annualized_vol)
    else:
        # Emergency fallback / Deprecated path
        risk_budget = equity * 0.01
        qty = int(risk_budget / stop_distance) if stop_distance > 0 else 0
        qty = min(qty, int((equity * MAX_NOTIONAL_PCT) / price))

    # Regime adjustment
    if regime == Regime.CAUTIOUS:
        qty = max(0, int(qty * CAUTIOUS_SIZE_MULT))
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
