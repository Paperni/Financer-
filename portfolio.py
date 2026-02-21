"""
Shared Portfolio engine for the Live Money Machine trading system.
Used by smart_trader.py (backtesting) and live_trader.py (live paper trading).

Strategy: Institutional Swing with ATR-based risk management.
"""

import json
import os
import datetime
import zoneinfo


# ── Configuration (Institutional Swing — 1-week trial) ───────────────────────
MAX_POSITIONS = 8
# Score-based position cap — targets $40-80K total in swings across 8 slots,
# leaving the rest in QQQ. With $100K initial capital:
#   Score 5 →  5% = $5,000   |  8 slots = $40K swing exposure
#   Score 6 →  7% = $7,000   |  8 slots = $56K swing exposure
#   Score 7 →  8.5% = $8,500 |  8 slots = $68K swing exposure
#   Score 8 → 10% = $10,000  |  8 slots = $80K swing exposure
MAX_POSITION_BY_SCORE = {
    5: 0.05,   # $5,000 per slot — minimum conviction
    6: 0.07,   # $7,000 per slot — solid setup
    7: 0.085,  # $8,500 per slot — strong setup
    8: 0.10,   # $10,000 per slot — max conviction
}
MAX_POSITION_PCT = 0.05          # default fallback ($5K)
# Score-based risk scaling: higher conviction = bigger position
RISK_BY_SCORE = {
    5: 0.010,   # 1.0% — minimum conviction
    6: 0.015,   # 1.5% — solid setup
    7: 0.020,   # 2.0% — strong setup
    8: 0.025,   # 2.5% — perfect score, max conviction
}
RISK_PER_TRADE_PCT = 0.010       # default / fallback (used in status display)
ATR_STOP_MULTIPLIER = 1.5        # Stop = entry - 1.5 * ATR
ATR_TP1_MULTIPLIER = 2.0         # TP1 = entry + 2.0 * ATR (2R reward)
ATR_TP2_MULTIPLIER = 3.0         # TP2 = entry + 3.0 * ATR (3R reward)
ATR_TP3_MULTIPLIER = 4.0         # TP3 = entry + 4.0 * ATR (4R reward)
TRAIL_ATR_MULTIPLIER = 1.0       # Trail stop = high - 1.0 * ATR
FALLBACK_STOP_PCT = 0.05         # 5% fallback if no ATR available
FALLBACK_TP1_PCT = 0.04
FALLBACK_TP2_PCT = 0.08
FALLBACK_TP3_PCT = 0.12
TIME_STOP_HOURS = 50             # Kill dead trades after ~2.5 trading days (50 hourly bars)

# Fee modeling — applied as slippage on every trade
SLIPPAGE_PCT = 0.0005            # 0.05% per trade (buy + sell = 0.10% round trip)

# Position sizing for CAUTIOUS regime
CAUTIOUS_SIZE_MULT = 0.75        # 75% size when market is cautious (mild pullback, not bear)

# Portfolio-level drawdown circuit breaker
DRAWDOWN_HALT_PCT = 0.08         # Pause new buys if portfolio drops 8% from initial capital


# ── Timezone helper ──────────────────────────────────────────────────────────
def now_et():
    """Current time in US/Eastern, timezone-aware."""
    return datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York"))


def now_str():
    """ISO-formatted timezone-aware timestamp string."""
    return now_et().isoformat()


# ── Market hours ─────────────────────────────────────────────────────────────
def is_market_open():
    """Check if US stock market is currently open (9:30 AM - 4:00 PM ET, Mon-Fri)."""
    et = now_et()
    if et.weekday() >= 5:
        return False, "Weekend"
    market_open = et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = et.replace(hour=16, minute=0, second=0, microsecond=0)
    if et < market_open:
        return False, f"Pre-Market (opens {market_open.strftime('%H:%M')} ET)"
    if et > market_close:
        return False, f"After-Hours (closed {market_close.strftime('%H:%M')} ET)"
    return True, "Market Open"


def seconds_until_open():
    """Return seconds until next market open (9:30 ET, Mon-Fri). 0 if already open."""
    import datetime
    et = now_et()
    is_open, _ = is_market_open()
    if is_open:
        return 0
    # Next 9:30 ET
    next_open = et.replace(hour=9, minute=30, second=0, microsecond=0)
    if et >= next_open:
        # Already past 9:30 today (after hours) — next business day
        next_open += datetime.timedelta(days=1)
    # Skip weekends
    while next_open.weekday() >= 5:
        next_open += datetime.timedelta(days=1)
    return max(0, int((next_open - et).total_seconds()))


# ── Wallet persistence (atomic writes) ──────────────────────────────────────
WALLET_FILE = "wallet.json"
EQUITY_FILE = "equity_curve.json"


def load_wallet():
    if not os.path.exists(WALLET_FILE):
        return reset_wallet()
    try:
        with open(WALLET_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"  Warning: Wallet corrupted ({e}), resetting.")
        return reset_wallet()


def save_wallet(wallet):
    wallet["last_update"] = now_str()
    tmp = WALLET_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(wallet, f, indent=4)
    os.replace(tmp, WALLET_FILE)


def reset_wallet(initial_capital=100000.0):
    wallet = {
        "cash": initial_capital,
        "initial_capital": initial_capital,
        "holdings": {},
        "history": [],
        "last_update": now_str(),
    }
    save_wallet(wallet)
    save_equity_curve([])
    return wallet


# ── Equity curve (separate file to keep wallet small) ────────────────────────
def load_equity_curve():
    if not os.path.exists(EQUITY_FILE):
        return []
    try:
        with open(EQUITY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def save_equity_curve(curve):
    tmp = EQUITY_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(curve, f)
    os.replace(tmp, EQUITY_FILE)


def append_equity(equity_value, max_points=2000):
    curve = load_equity_curve()
    curve.append({"time": now_str(), "equity": round(equity_value, 2)})
    if len(curve) > max_points:
        curve = curve[-max_points:]
    save_equity_curve(curve)


# ── Portfolio math ───────────────────────────────────────────────────────────
def calc_equity(wallet):
    """Total equity = cash + market value of all holdings."""
    equity = wallet["cash"]
    for pos in wallet["holdings"].values():
        equity += pos["qty"] * pos.get("last_price", pos["entry_price"])
    return equity


def check_drawdown_halt(wallet):
    """Returns True if portfolio has breached the drawdown limit (no new buys allowed).
    Returns (halted: bool, drawdown_pct: float)."""
    equity = calc_equity(wallet)
    initial = wallet.get("initial_capital", 100000.0)
    drawdown = (initial - equity) / initial
    return drawdown >= DRAWDOWN_HALT_PCT, drawdown


# ── Baseline index position (QQQ — idle cash always working) ────────────────
BASELINE_TICKER = "QQQ"
BASELINE_CASH_RESERVE = 2000.0   # Keep $2K cash for slippage / fees headroom


def deploy_baseline(wallet, price):
    """Deploy idle cash into QQQ baseline. Returns shares bought (0 if none)."""
    available = wallet["cash"] - BASELINE_CASH_RESERVE
    if available < price:
        return 0

    qty = int(available / (price * (1 + SLIPPAGE_PCT)))
    if qty <= 0:
        return 0

    fee = qty * price * SLIPPAGE_PCT
    cost = qty * price * (1 + SLIPPAGE_PCT)
    wallet["cash"] -= cost
    wallet["total_fees"] = wallet.get("total_fees", 0) + fee

    # Merge with existing baseline position (if any)
    if BASELINE_TICKER in wallet["holdings"] and wallet["holdings"][BASELINE_TICKER].get("is_baseline"):
        pos = wallet["holdings"][BASELINE_TICKER]
        old_cost = pos["qty"] * pos["entry_price"]
        new_cost = qty * price
        total_qty = pos["qty"] + qty
        pos["entry_price"] = round((old_cost + new_cost) / total_qty, 4)
        pos["qty"] = total_qty
        pos["initial_qty"] = total_qty
        pos["last_price"] = price
    else:
        wallet["holdings"][BASELINE_TICKER] = {
            "qty": qty,
            "initial_qty": qty,
            "entry_price": price,
            "last_price": price,
            "entry_time": now_str(),
            "is_baseline": True,
            "sl": 0,  # No stop on baseline
            "tp1": 999999, "tp2": 999999, "tp3": 999999,
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
            "reasoning": "Baseline QQQ — idle cash deployed",
        }

    wallet["history"].append({
        "Ticker": BASELINE_TICKER,
        "Time": now_str(),
        "Action": "BUY",
        "Price": price,
        "Qty": qty,
        "PnL": 0,
        "PnL_Pct": 0,
        "Fee": round(fee, 2),
        "Reason": "Baseline deploy",
    })
    return qty


def free_baseline(wallet, amount_needed, price):
    """Sell enough QQQ baseline shares to free up cash for a swing trade.
    Returns cash freed (0 if no baseline to sell)."""
    if BASELINE_TICKER not in wallet["holdings"]:
        return 0
    pos = wallet["holdings"][BASELINE_TICKER]
    if not pos.get("is_baseline"):
        return 0

    qty_needed = min(pos["qty"], int(amount_needed / price) + 1)
    if qty_needed <= 0:
        return 0

    effective_price = price * (1 - SLIPPAGE_PCT)
    fee = qty_needed * price * SLIPPAGE_PCT
    proceeds = qty_needed * effective_price
    wallet["cash"] += proceeds
    wallet["total_fees"] = wallet.get("total_fees", 0) + fee

    pnl = proceeds - (qty_needed * pos["entry_price"])

    wallet["history"].append({
        "Ticker": BASELINE_TICKER,
        "Time": now_str(),
        "Action": "SELL",
        "Price": price,
        "Qty": qty_needed,
        "PnL": round(pnl, 2),
        "PnL_Pct": round((price - pos["entry_price"]) / pos["entry_price"], 4),
        "Fee": round(fee, 2),
        "Reason": "Baseline free (swing trade)",
    })

    pos["qty"] -= qty_needed
    if pos["qty"] <= 0:
        del wallet["holdings"][BASELINE_TICKER]

    return proceeds


def count_swing_positions(wallet):
    """Count active swing positions (excludes baseline)."""
    return sum(1 for pos in wallet["holdings"].values() if not pos.get("is_baseline"))


# ── ATR-based position sizing ────────────────────────────────────────────────
def calc_position(price, atr, equity, regime="RISK_ON", score=5):
    """Calculate position size and levels using ATR-based risk management.

    Score-based risk scaling:
    - Score 5/8: risk 1.0% of equity (minimum conviction)
    - Score 6/8: risk 1.5% (solid)
    - Score 7/8: risk 2.0% (strong)
    - Score 8/8: risk 2.5% (perfect, max conviction)
    - CAUTIOUS regime: half size

    Returns dict with qty, sl, tp1, tp2, tp3, risk_per_share.
    """
    if atr and atr > 0:
        stop_distance = ATR_STOP_MULTIPLIER * atr
        tp1_distance = ATR_TP1_MULTIPLIER * atr
        tp2_distance = ATR_TP2_MULTIPLIER * atr
        tp3_distance = ATR_TP3_MULTIPLIER * atr
    else:
        # Fallback to percentage-based
        stop_distance = price * FALLBACK_STOP_PCT
        tp1_distance = price * FALLBACK_TP1_PCT
        tp2_distance = price * FALLBACK_TP2_PCT
        tp3_distance = price * FALLBACK_TP3_PCT

    # Risk budget — scaled by conviction score
    score_key = min(round(score), 8)
    risk_pct = RISK_BY_SCORE.get(score_key, RISK_PER_TRADE_PCT)
    risk_budget = equity * risk_pct
    if regime == "CAUTIOUS":
        risk_budget *= CAUTIOUS_SIZE_MULT

    # Position size from risk
    if stop_distance > 0:
        qty_from_risk = int(risk_budget / stop_distance)
    else:
        qty_from_risk = 0

    # Hard cap — scales with conviction score
    cap_pct = MAX_POSITION_BY_SCORE.get(score_key, MAX_POSITION_PCT)
    max_cap = equity * cap_pct
    if regime == "CAUTIOUS":
        max_cap *= CAUTIOUS_SIZE_MULT
    qty_from_cap = int(max_cap / price) if price > 0 else 0

    qty = min(qty_from_risk, qty_from_cap)

    return {
        "qty": qty,
        "sl": round(price - stop_distance, 2),
        "tp1": round(price + tp1_distance, 2),
        "tp2": round(price + tp2_distance, 2),
        "tp3": round(price + tp3_distance, 2),
        "risk_per_share": round(stop_distance, 2),
        "atr_used": round(atr, 4) if atr else None,
    }


# ── Trade execution ──────────────────────────────────────────────────────────
def execute_buy(wallet, ticker, price, atr=None, regime="RISK_ON", signals=None):
    """Open a position with ATR-based sizing and levels. Returns True if executed."""
    if len(wallet["holdings"]) >= MAX_POSITIONS:
        return False

    equity = calc_equity(wallet)
    trade_score = signals.get("score", 5) if signals else 5
    sizing = calc_position(price, atr, equity, regime, score=trade_score)
    qty = sizing["qty"]

    if qty == 0:
        return False
    # Apply slippage — we "pay" slightly more than market price
    effective_price = price * (1 + SLIPPAGE_PCT)
    cost = qty * effective_price
    if wallet["cash"] < cost:
        qty = int(wallet["cash"] / effective_price)
        if qty == 0:
            return False
        cost = qty * effective_price
    fee = qty * price * SLIPPAGE_PCT

    # Build reasoning
    if signals:
        reasoning = signals.get("reasoning", "")
        if not reasoning:
            reasoning = f"Score {signals.get('score', '?')}/8"
    else:
        reasoning = "Manual / Force Buy"

    wallet["cash"] -= cost
    wallet["total_fees"] = wallet.get("total_fees", 0) + fee
    wallet["holdings"][ticker] = {
        "qty": qty,
        "initial_qty": qty,
        "entry_price": price,
        "last_price": price,
        "entry_time": now_str(),
        "sl": sizing["sl"],
        "tp1": sizing["tp1"],
        "tp2": sizing["tp2"],
        "tp3": sizing["tp3"],
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "atr": sizing["atr_used"],
        "risk_per_share": sizing["risk_per_share"],
        "regime": regime,
        "signals": signals or {},
        "reasoning": reasoning,
    }

    wallet["history"].append({
        "Ticker": ticker,
        "Time": now_str(),
        "Action": "BUY",
        "Price": price,
        "Qty": qty,
        "PnL": 0,
        "PnL_Pct": 0,
        "Fee": round(fee, 2),
        "Reason": reasoning,
    })
    return True


def execute_sell(wallet, ticker, price, qty, reason):
    """Sell qty shares of ticker. Removes position if fully closed. Fee applied."""
    pos = wallet["holdings"][ticker]
    # Apply slippage — we "receive" slightly less than market price
    effective_price = price * (1 - SLIPPAGE_PCT)
    fee = qty * price * SLIPPAGE_PCT
    proceeds = qty * effective_price
    wallet["cash"] += proceeds
    wallet["total_fees"] = wallet.get("total_fees", 0) + fee

    entry_val = qty * pos["entry_price"]
    pnl = proceeds - entry_val
    pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]

    wallet["history"].append({
        "Ticker": ticker,
        "Time": now_str(),
        "Action": "SELL",
        "Price": price,
        "Qty": qty,
        "PnL": round(pnl, 2),
        "PnL_Pct": pnl_pct,
        "Fee": round(fee, 2),
        "Reason": reason,
    })

    pos["qty"] -= qty
    if pos["qty"] <= 0:
        del wallet["holdings"][ticker]

    return pnl


def check_exits(wallet, ticker, price):
    """Check stop loss, tiered TPs, trailing stop, and time stop."""
    if ticker not in wallet["holdings"]:
        return None
    pos = wallet["holdings"][ticker]
    atr = pos.get("atr")

    # ── Stop Loss ──
    if price <= pos["sl"]:
        pnl = execute_sell(wallet, ticker, price, pos["qty"], "Stop Loss")
        return ("Stop Loss", pnl)

    # ── Time Stop (dead money killer) ──
    try:
        entry_time = datetime.datetime.fromisoformat(pos["entry_time"])
        now = now_et()
        # Make entry_time timezone-aware if it isn't
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=zoneinfo.ZoneInfo("America/New_York"))
        hours_held = (now - entry_time).total_seconds() / 3600
        if hours_held >= TIME_STOP_HOURS and not pos.get("tp1_hit"):
            # Only time-stop if we haven't hit TP1 (position going nowhere)
            pnl = execute_sell(wallet, ticker, price, pos["qty"],
                               f"Time Stop ({hours_held:.0f}h, no TP1)")
            return ("Time Stop", pnl)
    except (ValueError, TypeError):
        pass  # Can't parse entry_time, skip time stop

    # ── TP1 (2R) — sell 25% to lock in profit, let 75% ride risk-free ──
    if not pos.get("tp1_hit") and price >= pos["tp1"]:
        qty = max(1, min(int(pos["initial_qty"] * 0.25), pos["qty"]))
        r_multiple = (price - pos["entry_price"]) / pos["risk_per_share"] if pos.get("risk_per_share") else "?"
        pnl = execute_sell(wallet, ticker, price, qty,
                           f"TP1 (+{r_multiple:.1f}R)" if isinstance(r_multiple, float) else "TP1")
        if ticker in wallet["holdings"]:
            pos["tp1_hit"] = True
            pos["sl"] = pos["entry_price"]  # Move stop to breakeven
            pos["pyramid_eligible"] = True  # Flag for pyramid add
        return ("TP1", pnl)

    # ── TP2 (3R) — sell 30% more ──
    if not pos.get("tp2_hit") and price >= pos["tp2"]:
        qty = max(1, min(int(pos["initial_qty"] * 0.30), pos["qty"]))
        pnl = execute_sell(wallet, ticker, price, qty, "TP2 (3R)")
        if ticker in wallet["holdings"]:
            pos["tp2_hit"] = True
        return ("TP2", pnl)

    # ── TP3 (4R) — sell 15%, leave ~15% as runner ──
    if not pos.get("tp3_hit") and price >= pos["tp3"]:
        qty = max(1, min(int(pos["initial_qty"] * 0.15), pos["qty"]))
        pnl = execute_sell(wallet, ticker, price, qty, "TP3 (4R)")
        if ticker in wallet["holdings"]:
            pos["tp3_hit"] = True
            pos["trail_high"] = price
        return ("TP3", pnl)

    # ── Trailing stop on runner (ATR-based) ──
    if pos.get("tp3_hit") and pos["qty"] > 0:
        trail_high = pos.get("trail_high", price)
        if price > trail_high:
            pos["trail_high"] = price
            trail_high = price
        # Trail by 1 ATR from peak (or 3% fallback)
        trail_dist = atr * TRAIL_ATR_MULTIPLIER if atr else trail_high * 0.03
        trail_stop = trail_high - trail_dist
        if price <= trail_stop:
            pnl = execute_sell(wallet, ticker, price, pos["qty"],
                               f"Trail Stop (Peak ${trail_high:.2f})")
            return ("Trail Stop", pnl)

    # ── Update tracking ──
    pos["last_price"] = price
    pos["unrealized_pnl"] = (price - pos["entry_price"]) / pos["entry_price"]
    return None


# ── Backtest Portfolio class (for smart_trader simulation) ───────────────────
class Portfolio:
    """In-memory portfolio for backtesting. No file I/O, pure calculation."""

    def __init__(self, initial_capital, max_positions=MAX_POSITIONS):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_positions = max_positions
        self.holdings = {}
        self.trade_log = []
        self.equity_curve = []

    def total_equity(self, current_prices):
        equity = self.cash
        for ticker, pos in self.holdings.items():
            equity += pos["qty"] * current_prices.get(ticker, pos["entry_price"])
        return equity

    def update_curve(self, time, equity):
        self.equity_curve.append({"time": time, "equity": equity})

    def enter(self, ticker, price, time, atr=None):
        if len(self.holdings) >= self.max_positions:
            return False
        equity = self.total_equity({})
        sizing = calc_position(price, atr, equity)
        qty = sizing["qty"]
        if qty == 0:
            return False
        cost = qty * price
        if self.cash < cost:
            qty = int(self.cash / price)
            if qty == 0:
                return False
            cost = qty * price

        self.cash -= cost
        self.holdings[ticker] = {
            "qty": qty,
            "initial_qty": qty,
            "entry_price": price,
            "entry_time": time,
            "sl": sizing["sl"],
            "tp1": sizing["tp1"],
            "tp2": sizing["tp2"],
            "tp3": sizing["tp3"],
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "risk_per_share": sizing["risk_per_share"],
        }
        return True

    def exit(self, ticker, price, time, reason, qty=None):
        if ticker not in self.holdings:
            return
        pos = self.holdings[ticker]
        exit_qty = min(qty or pos["qty"], pos["qty"])

        proceeds = exit_qty * price
        self.cash += proceeds
        pnl = proceeds - (exit_qty * pos["entry_price"])
        pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]

        self.trade_log.append({
            "Ticker": ticker,
            "Entry Time": pos["entry_time"],
            "Exit Time": time,
            "Entry Price": pos["entry_price"],
            "Exit Price": price,
            "PnL": pnl,
            "PnL %": pnl_pct,
            "Reason": reason,
        })

        if exit_qty >= pos["qty"]:
            del self.holdings[ticker]
        else:
            self.holdings[ticker]["qty"] -= exit_qty

    def check_exits(self, ticker, price, time):
        """Check tiered exits for backtesting."""
        if ticker not in self.holdings:
            return
        pos = self.holdings[ticker]

        if price <= pos["sl"]:
            self.exit(ticker, price, time, "Stop Loss")
            return

        if not pos["tp1_hit"] and price >= pos["tp1"]:
            qty = max(1, int(pos["initial_qty"] * 0.25))
            self.exit(ticker, price, time, "TP1 (2R)", qty=qty)
            pos["tp1_hit"] = True
            pos["sl"] = pos["entry_price"]  # Move stop to breakeven
        elif not pos["tp2_hit"] and price >= pos["tp2"]:
            qty = max(1, int(pos["initial_qty"] * 0.30))
            self.exit(ticker, price, time, "TP2 (3R)", qty=qty)
            pos["tp2_hit"] = True
        elif not pos["tp3_hit"] and price >= pos["tp3"]:
            qty = max(1, int(pos["initial_qty"] * 0.15))
            self.exit(ticker, price, time, "TP3 (4R)", qty=qty)
            pos["tp3_hit"] = True
