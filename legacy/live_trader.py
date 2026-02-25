import time
import yfinance as yf
from data_static import BROAD_STOCKS, BROAD_ETFS
import portfolio as pf
from indicators import (
    DataCache, check_buy_signal_detailed, check_volume_contraction,
)
from legacy.core.strategy.config_loader import load_runtime_config
from legacy.core.risk.risk_engine_v2 import RiskEngineV2
from control_center.state_store import ControlStateStore
from control_center.api import run_control_center
from control_center.approvals import ApprovalQueue
from legacy.core.explainability.decision_logger import DecisionLogger
from legacy.core.alerts.notifier import AlertNotifier
from legacy.core.alerts.rules import should_alert

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# ── Configuration ─────────────────────────────────────────────────────────────
_RUNTIME_CFG = {}
INITIAL_CAPITAL = 100000.0
MAX_PER_SECTOR = 3          # max positions in the same sector
_RISK_ENGINE = RiskEngineV2({})
_CONTROL_STORE = ControlStateStore()
_DECISION_LOGGER = DecisionLogger()
_APPROVAL_QUEUE = ApprovalQueue()
_ALERT_NOTIFIER = AlertNotifier({"enabled": True, "channels": ["console", "file"]})


def apply_runtime_config(config_path=None, profile=None, overrides=None):
    """Load runtime config and apply key controls to globals."""
    global _RUNTIME_CFG, INITIAL_CAPITAL, MAX_PER_SECTOR, _RISK_ENGINE
    _RUNTIME_CFG = load_runtime_config(
        config_path=config_path,
        profile=profile,
        overrides=overrides or [],
    )
    INITIAL_CAPITAL = float(_RUNTIME_CFG.get("capital", {}).get("initial_capital", 100000.0))
    MAX_PER_SECTOR = int(_RUNTIME_CFG.get("risk", {}).get("max_positions_per_sector", 3))
    _RISK_ENGINE = RiskEngineV2(_RUNTIME_CFG.get("risk", {}))


def _feature_enabled(name, default=True):
    return bool(_RUNTIME_CFG.get("features", {}).get(name, default))


def _control_state():
    return _CONTROL_STORE.load()


def _alert(event, message, context=None):
    ctx = context or {}
    if should_alert(event, ctx):
        _ALERT_NOTIFIER.send("WARN", message, {"event": event, **ctx})

# ── Shared data cache (persists between cycles) ─────────────────────────────
_cache = DataCache()
ALL_TICKERS = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
apply_runtime_config()


# ── Sound alerts ─────────────────────────────────────────────────────────────
def trade_alert(action, ticker, pnl=0):
    if action == "BUY":
        if HAS_WINSOUND:
            winsound.Beep(800, 300)
        print(f"  {'*'*40}")
        print(f"  *  TRADE ALERT: BOUGHT {ticker}")
        print(f"  {'*'*40}")
    elif pnl >= 0:
        if HAS_WINSOUND:
            winsound.Beep(1000, 200)
            time.sleep(0.1)
            winsound.Beep(1200, 200)
        print(f"  {'$'*40}")
        print(f"  $  PROFIT: SOLD {ticker} (+${pnl:.2f})")
        print(f"  {'$'*40}")
    else:
        if HAS_WINSOUND:
            winsound.Beep(400, 150)
            time.sleep(0.05)
            winsound.Beep(400, 150)
            time.sleep(0.05)
            winsound.Beep(300, 200)
        print(f"  {'!'*40}")
        print(f"  !  LOSS: SOLD {ticker} (-${abs(pnl):.2f})")
        print(f"  {'!'*40}")


# ── Strategy Execution ────────────────────────────────────────────────────────
def update_holdings(wallet):
    """Check stops, TPs, time stops using REAL-TIME 1-min prices."""
    controls = _control_state()
    if controls.get("pause_sells"):
        print("  ControlCenter: pause_sells=true. Exit checks paused.")
        _DECISION_LOGGER.log(event="exits_skipped", reason="pause_sells")
        return
    # Filter out baseline from exit checks (but still update its price)
    holdings = wallet["holdings"]
    if not holdings:
        return
    swing_tickers = [t for t in holdings.keys() if not holdings[t].get("is_baseline")]
    all_tickers_to_price = list(holdings.keys())  # Need prices for baseline too
    if not all_tickers_to_price:
        return
    print(f"  Checking {len(swing_tickers)} swing + {len(all_tickers_to_price) - len(swing_tickers)} baseline (real-time)...")

    # Always fetch fresh 1-min data for held positions (max 5 tickers — fast)
    try:
        data = yf.download(all_tickers_to_price, period="1d", interval="1m",
                           progress=False, group_by='ticker', threads=True)
    except Exception as e:
        print(f"  Error fetching live prices: {e}")
        return
    is_multi = len(all_tickers_to_price) > 1

    # Update all prices (including baseline)
    for ticker in all_tickers_to_price:
        try:
            df = data[ticker] if is_multi else data
            close_col = df["Close"]
            if hasattr(close_col, "columns"):
                close_col = close_col.iloc[:, 0]
            price = float(close_col.dropna().iloc[-1])
            wallet["holdings"][ticker]["last_price"] = price
        except Exception:
            pass

    # Only check exits on swing positions (not baseline)
    for ticker in list(swing_tickers):
        try:
            pos = wallet["holdings"].get(ticker)
            if not pos:
                continue
            price = pos.get("last_price", pos["entry_price"])

            # Pre-earnings safety: reduce to half size if earnings within 2 days
            days_to_earn = None
            if _feature_enabled("earnings_enabled", True):
                days_to_earn = _cache.days_until_earnings(ticker)
                if days_to_earn is not None and days_to_earn <= 2 and not pos.get("earnings_reduced"):
                    half_qty = pos["qty"] // 2
                    if half_qty > 0:
                        pnl = pf.execute_sell(wallet, ticker, price, half_qty,
                                              f"Pre-earnings reduce ({days_to_earn}d)")
                        print(f"  >> PRE-EARNINGS: Reduced {ticker} by {half_qty} sh (earnings in {days_to_earn}d) | PnL: ${pnl:.2f}")
                        if ticker in wallet["holdings"]:
                            wallet["holdings"][ticker]["earnings_reduced"] = True
                        trade_alert("SELL", ticker, pnl)
                        continue  # Skip normal exit check this cycle
                elif days_to_earn is None or days_to_earn > 5:
                    # Earnings passed or unknown — reset flag so future earnings get the reduction
                    if pos.get("earnings_reduced"):
                        pos["earnings_reduced"] = False

            result = pf.check_exits(wallet, ticker, price)
            if result:
                reason, pnl = result
                print(f"  >> EXECUTED SELL: {ticker} ({reason}) @ ${price:.2f} | PnL: ${pnl:.2f}")
                trade_alert("SELL", ticker, pnl)

        except Exception as e:
            print(f"  Warning: Could not update {ticker}: {e}")

    pf.save_wallet(wallet)


def check_pyramids(wallet):
    """Check if any TP1-hit positions qualify for a pyramid add (50% of original size)."""
    for ticker, pos in list(wallet["holdings"].items()):
        if not pos.get("pyramid_eligible") or pos.get("pyramided"):
            continue
        if pos.get("is_baseline"):
            continue

        # Re-score with fresh data
        row = _cache.get_latest_row(ticker)
        if row is None:
            continue
        rs = _cache.get_relative_strength(ticker)
        df = _cache.get(ticker)
        vol_c = check_volume_contraction(df) if df is not None else False
        fundies = _cache.get_fundamentals(ticker)
        dsma50 = _cache.get_daily_sma50(ticker)
        _, score, reasons = check_buy_signal_detailed(row, rs, vol_c, fundies, daily_sma50=dsma50)

        if score >= 5:
            price = pos.get("last_price", pos["entry_price"])
            atr = _cache.get_atr(ticker)
            pyramid_cost = pos["initial_qty"] * pos["entry_price"] * 0.5
            pyramid_qty = int(pyramid_cost / (price * (1 + pf.SLIPPAGE_PCT)))
            if pyramid_qty > 0 and wallet["cash"] > pyramid_qty * price * (1 + pf.SLIPPAGE_PCT):
                fee = pyramid_qty * price * pf.SLIPPAGE_PCT
                cost = pyramid_qty * price * (1 + pf.SLIPPAGE_PCT)
                wallet["cash"] -= cost
                wallet["total_fees"] = wallet.get("total_fees", 0) + fee
                # Weighted average entry price
                old_cost = pos["qty"] * pos["entry_price"]
                new_cost = pyramid_qty * price
                total_qty = pos["qty"] + pyramid_qty
                pos["entry_price"] = round((old_cost + new_cost) / total_qty, 4)
                pos["qty"] = total_qty
                pos["pyramided"] = True
                # Recalculate levels from current price
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
                trade_alert("BUY", ticker)
    pf.save_wallet(wallet)


def scan_and_buy(wallet, regime):
    """Scan all assets with institutional-grade scoring. Market regime is a gate."""

    swing_count = pf.count_swing_positions(wallet)
    if swing_count >= pf.MAX_POSITIONS:
        print(f"  Max swing positions ({pf.MAX_POSITIONS}) reached. Skipping scan.")
        _DECISION_LOGGER.log(event="scan_skipped", reason="max_positions_reached")
        return

    # Drawdown circuit breaker
    halted, dd_pct = pf.check_drawdown_halt(wallet)
    if halted:
        print(f"  CIRCUIT BREAKER: Portfolio down {dd_pct:.1%} (limit {pf.DRAWDOWN_HALT_PCT:.0%}). No new buys.")
        _DECISION_LOGGER.log(event="scan_skipped", reason="drawdown_circuit_breaker", context={"drawdown_pct": dd_pct})
        _alert("drawdown_circuit_breaker", f"Drawdown breaker active at {dd_pct:.1%}", {"drawdown_pct": dd_pct})
        return

    # Additional portfolio-level risk checks
    risk_ok, risk_reason = _RISK_ENGINE.can_open_new_positions(wallet)
    if not risk_ok:
        print(f"  {risk_reason}. No new buys.")
        _DECISION_LOGGER.log(event="scan_skipped", reason=risk_reason)
        _alert("risk_halt", risk_reason, {})
        return

    # RISK_OFF gate: no new buys when market is in downtrend
    if regime == "RISK_OFF":
        print("  RISK OFF: SPY below SMA-200. No new buys.")
        _DECISION_LOGGER.log(event="scan_skipped", reason="risk_off_regime")
        return

    # Phase 1: Technical screen (8-point, fast — no API calls per ticker)
    pre_candidates = []
    for ticker in ALL_TICKERS:
        if ticker in wallet["holdings"]:
            continue

        row = _cache.get_latest_row(ticker)
        if row is None:
            continue

        rs = _cache.get_relative_strength(ticker)
        df = _cache.get(ticker)
        vol_contracting = check_volume_contraction(df) if df is not None else False
        dsma50 = _cache.get_daily_sma50(ticker)

        passed, score, reasons = check_buy_signal_detailed(row, rs, vol_contracting,
                                                           daily_sma50=dsma50)
        if passed or score >= 4:  # pre-filter: 4+ on technicals alone
            atr = _cache.get_atr(ticker)
            pre_candidates.append((ticker, score, reasons, row, atr, rs, vol_contracting, dsma50))

    # Phase 2: PEG enrichment (only for pre-filtered candidates — lazy API calls)
    candidates = []
    for ticker, score, reasons, row, atr, rs, vol_c, dsma50 in pre_candidates:
        fundies = _cache.get_fundamentals(ticker)
        # Re-score with fundamentals for the 8th point
        _, full_score, full_reasons = check_buy_signal_detailed(row, rs, vol_c, fundies,
                                                                daily_sma50=dsma50)
        if full_score >= 5:
            candidates.append((ticker, full_score, full_reasons, row, atr, rs, fundies))

    # Sort by score descending — highest conviction first
    candidates.sort(key=lambda x: x[1], reverse=True)

    slots = pf.MAX_POSITIONS - pf.count_swing_positions(wallet)
    found = 0

    # Build sector count from current SWING holdings (exclude baseline QQQ)
    sector_count = {}
    for held_ticker, held_pos in wallet["holdings"].items():
        if held_pos.get("is_baseline"):
            continue
        held_fundies = _cache.get_fundamentals(held_ticker)
        sec = held_fundies.get("sector", "Unknown") if held_fundies else "Unknown"
        sector_count[sec] = sector_count.get(sec, 0) + 1

    for ticker, score, reasons, row, atr, rs, fundies in candidates:
        if found >= slots:
            break

        candidate_sector = fundies.get("sector", "Unknown") if fundies else "Unknown"
        close = float(row["Close"])
        entry_ok, entry_reason = _RISK_ENGINE.can_take_entry(
            wallet=wallet,
            candidate_sector=candidate_sector,
            sector_count=sector_count,
            price=close,
            atr=atr,
        )
        if not entry_ok:
            print(f"  Skip {ticker}: {entry_reason}")
            _DECISION_LOGGER.log(event="candidate_skipped", ticker=ticker, reason=entry_reason)
            continue

        # Earnings calendar gate — avoid binary event risk
        days_to_earn = None
        if _feature_enabled("earnings_enabled", True):
            days_to_earn = _cache.days_until_earnings(ticker)
            if days_to_earn is not None and days_to_earn <= 3:
                print(f"  Skip {ticker}: earnings in {days_to_earn} days (binary risk)")
                _DECISION_LOGGER.log(
                    event="candidate_skipped",
                    ticker=ticker,
                    reason="earnings_gate",
                    context={"days_to_earnings": days_to_earn},
                )
                continue

        # News sentiment gate — FinBERT analysis
        if _feature_enabled("news_enabled", True):
            news = _cache.get_news_sentiment(ticker)
        else:
            news = {"sentiment": "NEUTRAL", "adjustment": 0}
        if news["sentiment"] == "DANGER":
            print(f"  BLOCKED {ticker}: {news['sentiment']} -- {news.get('top_headline', 'N/A')[:60]}")
            _DECISION_LOGGER.log(event="candidate_blocked", ticker=ticker, reason="danger_news")
            continue
        score += news["adjustment"]
        if news["adjustment"] != 0:
            reasons["news"] = f"News: {news['sentiment']} ({news['adjustment']:+.1f})"
        if score < 5:
            print(f"  Skip {ticker}: score dropped to {score:.1f}/8 after news penalty")
            _DECISION_LOGGER.log(
                event="candidate_skipped",
                ticker=ticker,
                reason="score_below_threshold_after_news",
                context={"score": score},
            )
            continue

        reason_str = " | ".join(reasons.values())

        # Build info strings for reasoning
        atr_str = f"ATR=${atr:.2f}" if atr else "ATR=N/A"
        rs_str = f"RS={rs:.2f}x" if rs else "RS=N/A"
        peg_str = ""
        if fundies and fundies.get("pe") and fundies.get("revenue_growth"):
            peg_str = f" | P/E={fundies['pe']:.1f} RevG={fundies['revenue_growth']:.0f}%"
        news_str = f" | News:{news['sentiment']}" if news["adjustment"] != 0 else ""

        signals = {
            "score": score,
            "rsi": round(float(row["RSI"]), 1),
            "sma50": round(float(row["SMA_50"]), 2),
            "close": round(close, 2),
            "atr": round(atr, 2) if atr else None,
            "relative_strength": round(rs, 2) if rs else None,
            "sector": candidate_sector,
            "news_sentiment": news["sentiment"],
            "news_adjustment": news["adjustment"],
            "days_to_earnings": days_to_earn,
            "reasoning": f"[{score}/8 | {regime}] {reason_str} | {atr_str} | {rs_str}{peg_str}{news_str}",
        }

        controls = _control_state()
        if controls.get("approval_mode", "auto") == "manual":
            approval = _APPROVAL_QUEUE.create(
                {
                    "ticker": ticker,
                    "signals": signals,
                    "candidate_sector": candidate_sector,
                    "score": score,
                    "regime": regime,
                    "proposed_price": close,
                }
            )
            print(f"  Approval queued for {ticker} (id={approval['id']})")
            _DECISION_LOGGER.log(
                event="candidate_queued_for_approval",
                ticker=ticker,
                reason="manual_approval_mode",
                context={"approval_id": approval["id"], "score": score},
            )
            continue

        if pf.execute_buy(wallet, ticker, close, atr=atr, regime=regime, signals=signals):
            pos = wallet["holdings"][ticker]
            sector_count[candidate_sector] = sector_count.get(candidate_sector, 0) + 1
            print(f"  >> EXECUTED BUY: {ticker} @ ${close:.2f} (Score: {score}/8, {regime}, {candidate_sector})")
            print(f"     SL: ${pos['sl']:.2f} | TP1: ${pos['tp1']:.2f} (2R) | TP2: ${pos['tp2']:.2f} (3R) | TP3: ${pos['tp3']:.2f} (4R)")
            print(f"     {reason_str}")
            _DECISION_LOGGER.log(
                event="buy_executed",
                ticker=ticker,
                reason="score_passed",
                context={
                    "score": score,
                    "regime": regime,
                    "sector": candidate_sector,
                    "reasoning": reason_str,
                },
            )
            trade_alert("BUY", ticker)
            found += 1

    if candidates:
        print(f"  Scan: {len(pre_candidates)} pre-filtered, {len(candidates)} scored 5+/8. Bought top {found}. ({regime})")
    else:
        print(f"  Scan: No setups scored 5+/8 this cycle. ({regime})")
    pf.save_wallet(wallet)


# ── Dashboard ─────────────────────────────────────────────────────────────────
def update_dashboard_html(wallet, regime="UNKNOWN"):
    """Updates dashboard.html with latest wallet state."""
    equity = pf.calc_equity(wallet)
    initial = wallet.get("initial_capital", INITIAL_CAPITAL)
    ret_pct = (equity - initial) / initial
    timestamp = pf.now_et().strftime("%H:%M:%S ET")
    regime_colors = {"RISK_ON": "#4CAF50", "CAUTIOUS": "#FF9800", "RISK_OFF": "#ff5252", "UNKNOWN": "#888"}
    regime_color = regime_colors.get(regime, "#888")

    # Compute fee + PnL summary
    fees = wallet.get("total_fees", 0)
    realized = sum(t["PnL"] for t in wallet["history"] if t["Action"] == "SELL")
    unrealized = sum((pos.get("last_price", pos["entry_price"]) - pos["entry_price"]) * pos["qty"]
                     for pos in wallet["holdings"].values())
    gross_pnl = realized + unrealized
    net_pnl = gross_pnl - fees

    # Separate baseline from swing positions
    baseline_pos = None
    swing_positions = {}
    for t, p in wallet["holdings"].items():
        if p.get("is_baseline"):
            baseline_pos = (t, p)
        else:
            swing_positions[t] = p
    swing_count = len(swing_positions)

    # News sentiment colors
    news_colors = {"DANGER": "#ff5252", "NEGATIVE": "#FF9800", "POSITIVE": "#4CAF50", "NEUTRAL": "#666"}

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="10">
        <title>Live Money Machine v3</title>
        <style>
            body {{ background: #0f0f13; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
            .card {{ background: #1e1e24; padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
            h2 {{ border-bottom: 1px solid #333; padding-bottom: 10px; }}
            .metric {{ font-size: 2.5rem; font-weight: bold; }}
            .sub {{ font-size: 1rem; color: #888; }}
            .row {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 20px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th {{ text-align: left; color: #888; padding: 10px; border-bottom: 1px solid #333; }}
            td {{ padding: 12px 10px; border-bottom: 1px solid #2a2a30; }}
            .green {{ color: #4CAF50; }}
            .red {{ color: #ff5252; }}
            .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; background: #333; display: inline-block; }}
            .earn-flag {{ color: #FF9800; font-weight: bold; font-size: 0.75rem; }}
        </style>
    </head>
    <body>
        <div class="card row">
            <div>
                <div class="sub">Total Equity</div>
                <div class="metric {'green' if ret_pct >= 0 else 'red'}">${equity:,.2f}</div>
                <div class="sub {'green' if ret_pct >= 0 else 'red'}">{ret_pct:+.2%} from ${initial:,.0f}</div>
            </div>
            <div>
                <div class="sub">Cash</div>
                <div style="font-size:1.5rem; font-weight:bold;">${wallet["cash"]:,.2f}</div>
            </div>
            <div>
                <div class="sub">Gross PnL / Fees / Net</div>
                <div style="font-size:1.1rem;">
                    <span class="{'green' if gross_pnl >= 0 else 'red'}">${gross_pnl:+,.2f}</span>
                    <span class="sub"> - ${fees:,.2f} = </span>
                    <span class="{'green' if net_pnl >= 0 else 'red'}" style="font-weight:bold;">${net_pnl:+,.2f}</span>
                </div>
            </div>
            <div style="text-align:right">
                <div class="sub">Market Regime</div>
                <div style="font-size: 1.4rem; font-weight: bold; color: {regime_color};">{regime}</div>
                <div class="sub">{timestamp}</div>
            </div>
        </div>
    """

    # Baseline section
    if baseline_pos:
        bl_ticker, bl = baseline_pos
        bl_curr = bl.get("last_price", bl["entry_price"])
        bl_val = bl["qty"] * bl_curr
        bl_pnl = (bl_curr - bl["entry_price"]) * bl["qty"]
        bl_c = "green" if bl_pnl >= 0 else "red"
        html += f"""
        <div class="card" style="border-left: 3px solid #1565c0;">
            <h2>Baseline Position ({bl_ticker})</h2>
            <div class="row">
                <div>{bl["qty"]} shares @ ${bl["entry_price"]:.2f}</div>
                <div>Value: <b>${bl_val:,.0f}</b></div>
                <div class="{bl_c}">PnL: ${bl_pnl:+,.2f} ({bl_pnl/max(bl["qty"]*bl["entry_price"],1):+.2%})</div>
            </div>
        </div>
        """

    # Swing positions
    html += f"""
        <div class="card">
            <h2>Swing Positions ({swing_count}/{pf.MAX_POSITIONS})</h2>
            <table>
                <thead><tr><th>Ticker</th><th>Qty</th><th>Entry</th><th>Price</th><th>SL</th><th>PnL</th><th>Status</th><th>News</th></tr></thead>
                <tbody>
    """

    for ticker, pos in swing_positions.items():
        curr = pos.get("last_price", pos["entry_price"])
        val = pos["qty"] * curr
        entry_val = pos["qty"] * pos["entry_price"]
        pnl = val - entry_val
        pnl_pct = pnl / entry_val if entry_val > 0 else 0
        c = "green" if pnl >= 0 else "red"

        status = []
        if pos.get("pyramided"): status.append("Pyramided")
        if pos.get("tp3_hit"): status.append("TP3 - Runner")
        elif pos.get("tp2_hit"): status.append("TP2 hit")
        elif pos.get("tp1_hit"): status.append("TP1 (SL@BE)")
        else: status.append("Open")
        if pos.get("trail_high"): status.append(f"Trail: ${pos['trail_high']:.0f}")

        # Earnings flag
        earn_flag = ""
        days_e = _cache.days_until_earnings(ticker) if _cache else None
        if days_e is not None and days_e <= 7:
            earn_flag = f' <span class="earn-flag">EARN {days_e}d</span>'

        # News sentiment badge
        sigs = pos.get("signals", {})
        news_sent = sigs.get("news_sentiment", "")
        nc = news_colors.get(news_sent, "#666")
        news_badge = f'<span class="badge" style="background:{nc};color:#fff;">{news_sent}</span>' if news_sent else "--"

        html += f"""
        <tr>
            <td><b>{ticker}</b>{earn_flag}</td>
            <td>{pos["qty"]}</td>
            <td>${pos["entry_price"]:.2f}</td>
            <td>${curr:.2f}</td>
            <td>${pos["sl"]:.2f}</td>
            <td class="{c}">${pnl:+.2f} ({pnl_pct:+.2%})</td>
            <td>{', '.join(status)}</td>
            <td>{news_badge}</td>
        </tr>
        <tr>
            <td colspan="8" style="padding: 4px 10px 12px 20px; color: #888; font-size: 0.85rem; border-bottom: 1px solid #2a2a30;">
                {pos.get('reasoning', 'N/A')}
            </td>
        </tr>
        """

    html += """
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2>Trade History</h2>
            <table>
                <thead><tr><th>Time</th><th>Action</th><th>Ticker</th><th>Price</th><th>PnL</th><th>Fee</th><th>Reason</th></tr></thead>
                <tbody>
    """

    for trade in reversed(wallet["history"][-20:]):
        c = "green" if trade["PnL"] > 0 else "red" if trade["PnL"] < 0 else ""
        t = trade["Time"]
        display_time = t.split("T")[0] + " " + t.split("T")[1][:8] if "T" in t else t.split(".")[0]
        fee_str = f"${trade.get('Fee', 0):.2f}"
        html += f"""
        <tr>
            <td>{display_time}</td>
            <td><span class="badge" style="background:{'#2e7d32' if trade['Action']=='SELL' else '#1565c0'};color:#fff;">{trade["Action"]}</span></td>
            <td>{trade["Ticker"]}</td>
            <td>${trade["Price"]:.2f}</td>
            <td class="{c}">${trade["PnL"]:+.2f}</td>
            <td class="sub">{fee_str}</td>
            <td>{trade["Reason"][:80]}</td>
        </tr>
        """

    html += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """

    with open("docs/dashboards/dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)


# ── Main Loop ─────────────────────────────────────────────────────────────────
def premarket_warmup():
    """Pre-market prep: load cache, compute regime, pre-screen candidates, pre-fetch fundamentals."""
    print(f"\n{'='*60}")
    print(f"  PRE-MARKET WARMUP")
    print(f"{'='*60}")

    # 1. Bulk download all tickers (hourly data for indicators)
    print(f"\n  [1/6] Downloading data for {len(ALL_TICKERS)} tickers...")
    t0 = time.time()
    _cache.bulk_download(ALL_TICKERS, period="1mo", interval="1h")
    loaded = sum(1 for t in ALL_TICKERS if _cache.get(t) is not None)
    print(f"        Loaded {loaded}/{len(ALL_TICKERS)} tickers in {time.time()-t0:.0f}s")

    # 2. Market regime
    print(f"\n  [2/6] Market regime...")
    regime = _cache.get_market_regime()
    print(f"        Regime: {regime}")

    # 3. Pre-screen on technicals (7 criteria, no fundamentals yet)
    print(f"\n  [3/6] Technical pre-screen...")
    pre_candidates = []
    for ticker in ALL_TICKERS:
        row = _cache.get_latest_row(ticker)
        if row is None:
            continue
        rs = _cache.get_relative_strength(ticker)
        df = _cache.get(ticker)
        vol_c = check_volume_contraction(df) if df is not None else False
        dsma50 = _cache.get_daily_sma50(ticker)
        passed, score, reasons = check_buy_signal_detailed(row, rs, vol_c, daily_sma50=dsma50)
        if score >= 4:
            pre_candidates.append((ticker, score, reasons, dsma50))

    pre_candidates.sort(key=lambda x: x[1], reverse=True)
    print(f"        {len(pre_candidates)} tickers scored 4+ on technicals")

    # 4. Pre-fetch fundamentals + news + earnings for top candidates
    print(f"\n  [4/6] Fetching fundamentals for top candidates...")
    enriched = []
    for ticker, score, reasons, dsma50 in pre_candidates[:30]:  # top 30 to save API calls
        fundies = _cache.get_fundamentals(ticker)
        pe = fundies.get("pe", "N/A") if fundies else "N/A"
        rg = fundies.get("revenue_growth", "N/A") if fundies else "N/A"
        sector = fundies.get("sector", "?") if fundies else "?"

        # Re-score with PEG
        row = _cache.get_latest_row(ticker)
        rs = _cache.get_relative_strength(ticker)
        df = _cache.get(ticker)
        vol_c = check_volume_contraction(df) if df is not None else False
        _, full_score, full_reasons = check_buy_signal_detailed(row, rs, vol_c, fundies, daily_sma50=dsma50)
        enriched.append((ticker, full_score, full_reasons, pe, rg, sector))

    enriched.sort(key=lambda x: x[1], reverse=True)

    # 5. Pre-fetch news + earnings for top 15 candidates
    print(f"\n  [5/6] Fetching news sentiment + earnings calendar...")
    news_data = {}
    earn_data = {}
    for ticker, score, *_ in enriched[:15]:
        news_data[ticker] = _cache.get_news_sentiment(ticker)
        earn_data[ticker] = _cache.days_until_earnings(ticker)

    # 6. Print briefing
    print(f"\n  [6/6] Pre-Market Briefing")
    print(f"  {'-'*80}")
    print(f"  {'Ticker':<7} {'Score':>5} {'P/E':>7} {'RevG%':>6} {'News':<9} {'Earn':>5} {'Sector':<18} Signals")
    print(f"  {'-'*80}")
    shown = 0
    for ticker, score, reasons, pe, rg, sector in enriched:
        if score < 4:
            continue
        pe_str = f"{pe:.1f}" if isinstance(pe, (int, float)) else "N/A"
        rg_str = f"{rg:.0f}%" if isinstance(rg, (int, float)) else "N/A"
        news = news_data.get(ticker)
        news_str = news["sentiment"][:8] if news else "--"
        earn = earn_data.get(ticker)
        earn_str = f"{earn}d" if earn is not None else "--"
        sig = " | ".join(list(reasons.values())[:3])
        marker = " <<" if score >= 5 else ""
        blocked = " XX" if (earn is not None and earn <= 3) or (news and news["sentiment"] == "DANGER") else ""
        print(f"  {ticker:<7} {score:>5}/8 {pe_str:>7} {rg_str:>6} {news_str:<9} {earn_str:>5} {sector:<18} {sig}{marker}{blocked}")
        shown += 1
        if shown >= 15:
            break

    buyable = sum(1 for t, s, *_ in enriched if s >= 5)
    print(f"  {'-'*80}")
    print(f"  {buyable} candidates scoring 5+ (buy-ready at open)")
    if regime == "RISK_OFF":
        print(f"  WARNING: Regime is RISK_OFF — no buys will execute at open")
    elif regime == "CAUTIOUS":
        print(f"  NOTE: Regime is CAUTIOUS — position sizes halved")

    print(f"\n  Cache is HOT. Ready for market open. Manual deploy ready: --deploy-baseline")
    print(f"{'='*60}\n")


def run_live_cycle():
    print(f"\n[{pf.now_et().strftime('%H:%M:%S ET')}] Heartbeat...")
    controls = _control_state()
    if not controls.get("running", True):
        print("  ControlCenter: running=false. Cycle skipped.")
        _DECISION_LOGGER.log(event="cycle_skipped", reason="control_running_false")
        return

    market_open, status = pf.is_market_open()
    if not market_open:
        print(f"  Market Status: {status}.")
        wallet = pf.load_wallet()
        regime = _cache.get_market_regime() if _cache.tickers else "UNKNOWN"
        update_dashboard_html(wallet, regime)
        return

    wallet = pf.load_wallet()
    if controls.get("emergency_flatten"):
        print("  ControlCenter: emergency_flatten=true. Flattening all swing positions...")
        _flatten_all_positions(wallet)
        controls["emergency_flatten"] = False
        _CONTROL_STORE.save(controls)
        _DECISION_LOGGER.log(event="emergency_flatten_triggered", reason="control_state_flag")
        _alert("emergency_flatten_triggered", "Emergency flatten executed", {})

    # 1. Refresh cache (hourly data + daily for regime/RS)
    if _cache.tickers:
        _cache.refresh(ALL_TICKERS, period="5d", interval="1h")
    else:
        _cache.bulk_download(ALL_TICKERS, period="1mo", interval="1h")

    # 2. Check market regime
    regime = _cache.get_market_regime()
    print(f"  Market Regime: {regime}")

    # Manual approval workflow: execute pre-approved entries before new scan
    _process_approved_entries(wallet, regime)

    # 3. Update Existing Positions
    update_holdings(wallet)

    # 3.5 Pyramid into winners (TP1-hit positions with fresh score 5+)
    check_pyramids(wallet)

    # 4. Record Equity
    equity = pf.calc_equity(wallet)
    pf.append_equity(equity)
    pf.save_wallet(wallet)

    # 5. Update Dashboard
    update_dashboard_html(wallet, regime)

    # 6. Scan & Buy (regime gate is inside scan_and_buy)
    swing_count = pf.count_swing_positions(wallet)
    if controls.get("pause_buys"):
        print("  ControlCenter: pause_buys=true. Skipping new entries.")
        _DECISION_LOGGER.log(event="entries_skipped", reason="pause_buys")
    elif swing_count < pf.MAX_POSITIONS and wallet["cash"] > 1000:
        # Free baseline cash if needed for a swing trade
        if wallet["cash"] < 5000 and pf.BASELINE_TICKER in wallet["holdings"]:
            qqq_price = _cache.get_latest_price(pf.BASELINE_TICKER) or _get_live_price(pf.BASELINE_TICKER)
            freed = pf.free_baseline(wallet, 15000, qqq_price)
            if freed > 0:
                print(f"  Freed ${freed:,.0f} from QQQ baseline for swing trades")

        scan_and_buy(wallet, regime)

    pf.save_wallet(wallet)
    update_dashboard_html(wallet, regime)

    swing_count = pf.count_swing_positions(wallet)
    fees = wallet.get('total_fees', 0)
    print(f"  Cycle Complete. Equity: ${equity:,.0f} | Fees: ${fees:,.2f} | Swing: {swing_count}/{pf.MAX_POSITIONS} ({regime})")


def _flatten_all_positions(wallet):
    """Emergency flatten all non-baseline positions."""
    for ticker in list(wallet["holdings"].keys()):
        pos = wallet["holdings"].get(ticker)
        if not pos or pos.get("is_baseline"):
            continue
        try:
            price = _cache.get_latest_price(ticker) or _get_live_price(ticker)
            qty = pos.get("qty", 0)
            if qty > 0:
                pnl = pf.execute_sell(wallet, ticker, price, qty, "Emergency Flatten")
                _DECISION_LOGGER.log(
                    event="emergency_flatten_sell",
                    ticker=ticker,
                    reason="ControlCenter emergency_flatten",
                    context={"pnl": pnl, "qty": qty, "price": price},
                )
        except Exception as e:
            print(f"  Flatten warning for {ticker}: {e}")
    pf.save_wallet(wallet)


def _process_approved_entries(wallet, regime):
    """Execute approved manual entries from approval queue."""
    approved = _APPROVAL_QUEUE.list(status="approved")
    if not approved:
        return
    for item in approved:
        payload = item.get("payload", {})
        ticker = payload.get("ticker")
        if not ticker or ticker in wallet["holdings"]:
            _APPROVAL_QUEUE.mark_executed(item["id"], "skipped (invalid or already held)")
            continue
        row = _cache.get_latest_row(ticker)
        if row is None:
            _APPROVAL_QUEUE.mark_executed(item["id"], "skipped (no market row)")
            continue
        price = float(row.get("Close"))
        atr = _cache.get_atr(ticker)
        signals = payload.get("signals", {"reasoning": "Approved manual entry"})
        ok = pf.execute_buy(wallet, ticker, price, atr=atr, regime=regime, signals=signals)
        if ok:
            _DECISION_LOGGER.log(
                event="buy_executed",
                ticker=ticker,
                reason="manual_approval",
                context={"approval_id": item["id"]},
            )
            _APPROVAL_QUEUE.mark_executed(item["id"], "executed")
        else:
            _APPROVAL_QUEUE.mark_executed(item["id"], "skipped (buy failed)")
    pf.save_wallet(wallet)


def _get_live_price(ticker):
    data = yf.download(ticker, period="1d", interval="1m", progress=False)
    close_col = data["Close"]
    if hasattr(close_col, "columns"):
        close_col = close_col.iloc[:, 0]
    return float(close_col.dropna().iloc[-1])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Live Money Machine - Institutional Swing")
    parser.add_argument("--config", type=str, help="Path to runtime YAML config")
    parser.add_argument("--profile", type=str, help="Config profile name (conservative|balanced|aggressive)")
    parser.add_argument("--set", action="append", default=[], help="Override config key=value (repeatable)")
    parser.add_argument("--reset", action="store_true", help="Reset wallet to $100k")
    parser.add_argument("--loop", action="store_true", help="Run in infinite loop")
    parser.add_argument("--buy", type=str, help="Force buy a ticker (e.g. --buy NVDA)")
    parser.add_argument("--sell", type=str, help="Force sell all shares of a ticker")
    parser.add_argument("--status", action="store_true", help="Show current portfolio status")
    parser.add_argument("--warmup", action="store_true", help="Run pre-market warmup (cache + briefing)")
    parser.add_argument("--deploy-baseline", action="store_true", help="Deploy idle cash to QQQ baseline")
    parser.add_argument("--control-api", action="store_true", help="Run local control center API server")
    args = parser.parse_args()
    apply_runtime_config(args.config, args.profile, args.set)

    if args.reset:
        pf.reset_wallet(INITIAL_CAPITAL)
        print("Wallet reset to $100,000.")

    elif args.control_api:
        run_control_center()

    elif args.buy:
        ticker = args.buy.upper()
        print(f"Force buying {ticker}...")
        wallet = pf.load_wallet()
        if ticker in wallet["holdings"]:
            print(f"  Already holding {ticker}.")
        elif len(wallet["holdings"]) >= pf.MAX_POSITIONS:
            print(f"  Max positions ({pf.MAX_POSITIONS}) reached.")
        else:
            try:
                price = _get_live_price(ticker)
                if pf.execute_buy(wallet, ticker, price, signals={"reasoning": "Manual Buy"}):
                    pf.save_wallet(wallet)
                    update_dashboard_html(wallet)
                    print(f"  Done. Cash: ${wallet['cash']:,.2f}")
                    trade_alert("BUY", ticker)
            except Exception as e:
                print(f"  Failed: {e}")

    elif args.sell:
        ticker = args.sell.upper()
        wallet = pf.load_wallet()
        if ticker not in wallet["holdings"]:
            print(f"  Not holding {ticker}.")
        else:
            try:
                price = _get_live_price(ticker)
                qty = wallet["holdings"][ticker]["qty"]
                pnl = pf.execute_sell(wallet, ticker, price, qty, "Manual Sell")
                pf.save_wallet(wallet)
                update_dashboard_html(wallet)
                print(f"  Done. PnL: ${pnl:+.2f} | Cash: ${wallet['cash']:,.2f}")
                trade_alert("SELL", ticker, pnl)
            except Exception as e:
                print(f"  Failed: {e}")

    elif args.status:
        wallet = pf.load_wallet()
        equity = pf.calc_equity(wallet)
        total_pnl = 0
        print(f"\n{'='*60}")
        print(f"  PORTFOLIO STATUS - Institutional Swing")
        print(f"{'='*60}")
        print(f"  Cash: ${wallet['cash']:,.2f}")
        swing_count = pf.count_swing_positions(wallet)
        print(f"  Swing:     {swing_count}/{pf.MAX_POSITIONS}")
        baseline = wallet["holdings"].get(pf.BASELINE_TICKER)
        if baseline and baseline.get("is_baseline"):
            bl_val = baseline["qty"] * baseline.get("last_price", baseline["entry_price"])
            print(f"  Baseline:  {pf.BASELINE_TICKER} {baseline['qty']} sh (${bl_val:,.0f})")
        if wallet["holdings"]:
            print(f"  {'-'*56}")
        for ticker, pos in wallet["holdings"].items():
            if pos.get("is_baseline"):
                continue  # Show baseline separately above
            curr = pos.get("last_price", pos["entry_price"])
            pnl_pct = (curr - pos["entry_price"]) / pos["entry_price"] if pos["entry_price"] > 0 else 0
            pos_pnl = (curr - pos["entry_price"]) * pos["qty"]
            total_pnl += pos_pnl
            st = "Runner" if pos.get("tp3_hit") else "TP2" if pos.get("tp2_hit") else "TP1(SL@BE)" if pos.get("tp1_hit") else "Open"
            atr_str = f"ATR=${pos.get('atr', 0):.2f}" if pos.get("atr") else ""
            print(f"  {ticker:6s} | {pos['qty']:4d} sh | ${pos['entry_price']:.2f}->${curr:.2f} | {pnl_pct:+.2%} (${pos_pnl:+,.0f}) | SL ${pos['sl']:.2f} | {st} {atr_str}")
        realized = sum(t["PnL"] for t in wallet["history"] if t["Action"] == "SELL")
        initial = wallet.get("initial_capital", INITIAL_CAPITAL)
        wins = sum(1 for t in wallet["history"] if t["Action"] == "SELL" and t["PnL"] > 0 and not t.get("Reason", "").startswith("Baseline"))
        losses = sum(1 for t in wallet["history"] if t["Action"] == "SELL" and t["PnL"] <= 0 and not t.get("Reason", "").startswith("Baseline"))
        win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        fees = wallet.get("total_fees", 0)
        print(f"  {'-'*56}")
        print(f"  Total Equity:   ${equity:,.2f}")
        print(f"  Return:         {((equity - initial) / initial):+.2%}")
        print(f"  Unrealized PnL: ${total_pnl:+,.2f}")
        print(f"  Realized PnL:   ${realized:+,.2f}")
        print(f"  Total Fees:     ${fees:,.2f} (slippage)")
        print(f"  Fee Drag:       {fees/initial*100:.3f}%")
        print(f"  Win Rate:       {win_rate:.1f}% ({wins}W / {losses}L)")
        print(f"  Risk/Trade:     1.0%-2.5% (score-based)")
        # Best/Worst trade
        sell_trades = [t for t in wallet["history"] if t["Action"] == "SELL" and not t.get("Reason", "").startswith("Baseline")]
        if sell_trades:
            best = max(sell_trades, key=lambda t: t["PnL"])
            worst = min(sell_trades, key=lambda t: t["PnL"])
            print(f"  Best Trade:     {best['Ticker']} ${best['PnL']:+,.2f}")
            print(f"  Worst Trade:    {worst['Ticker']} ${worst['PnL']:+,.2f}")
        # Average hold time — use the most recent BUY before each SELL
        from datetime import datetime
        hold_times = []
        for t in sell_trades:
            try:
                st = datetime.fromisoformat(t["Time"])
            except Exception:
                continue
            # Find the most recent BUY for this ticker that happened before the sell
            latest_buy_time = None
            for b in wallet["history"]:
                if b["Action"] == "BUY" and b["Ticker"] == t["Ticker"]:
                    try:
                        bt = datetime.fromisoformat(b["Time"])
                        if bt <= st and (latest_buy_time is None or bt > latest_buy_time):
                            latest_buy_time = bt
                    except Exception:
                        pass
            if latest_buy_time is not None:
                hold_times.append((st - latest_buy_time).total_seconds() / 3600)
        if hold_times:
            avg_hold = sum(hold_times) / len(hold_times)
            print(f"  Avg Hold Time:  {avg_hold:.1f}h")
        # Equity curve analytics
        curve = pf.load_equity_curve()
        if len(curve) >= 2:
            vals = [p["equity"] for p in curve]
            # Max drawdown
            peak = vals[0]
            max_dd = 0
            for v in vals:
                if v > peak:
                    peak = v
                dd = (peak - v) / peak
                if dd > max_dd:
                    max_dd = dd
            print(f"  Max Drawdown:   {max_dd:.2%}")
            # Sharpe: group equity curve by calendar day, compute daily returns
            import math
            from datetime import datetime as _dt
            by_date = {}
            for p in curve:
                try:
                    day = _dt.fromisoformat(p["time"]).date()
                    by_date[day] = p["equity"]  # keep last value for each day
                except Exception:
                    pass
            daily_vals = [v for _, v in sorted(by_date.items())]
            if len(daily_vals) >= 3:
                daily_returns = [
                    (daily_vals[i] - daily_vals[i-1]) / daily_vals[i-1]
                    for i in range(1, len(daily_vals)) if daily_vals[i-1] > 0
                ]
                if daily_returns:
                    avg_r = sum(daily_returns) / len(daily_returns)
                    std_r = (sum((r - avg_r)**2 for r in daily_returns) / len(daily_returns)) ** 0.5
                    sharpe = (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0
                    print(f"  Sharpe (est):   {sharpe:.2f}")
        print(f"{'='*60}")

    elif args.warmup:
        premarket_warmup()

    elif args.deploy_baseline:
        wallet = pf.load_wallet()
        if wallet["cash"] > pf.BASELINE_CASH_RESERVE + 500:
            try:
                qqq_price = _get_live_price(pf.BASELINE_TICKER)
                if qqq_price:
                    bought = pf.deploy_baseline(wallet, qqq_price)
                    if bought > 0:
                        pf.save_wallet(wallet)
                        print(f"  Deployed {bought} shares of QQQ @ ${qqq_price:.2f}")
                        print(f"  Cash remaining: ${wallet['cash']:,.2f}")
                    else:
                        print(f"  No shares deployed (check cash/price)")
                else:
                    print(f"  Could not fetch QQQ price")
            except Exception as e:
                print(f"  Deploy failed: {e}")
        else:
            cash = wallet["cash"]
            print(f"  Insufficient cash: ${cash:,.2f} (need >${pf.BASELINE_CASH_RESERVE + 500:,.2f})")

    elif args.loop:
        print(f"\n{'='*60}")
        print(f"  LIVE MONEY MACHINE v3 - Institutional Swing")
        print(f"{'='*60}")
        print(f"  Entry:  8-point scoring (5+ required)")
        print(f"          Market regime gate (SPY SMA-50/200)")
        print(f"          News sentiment gate (3-tier)")
        print(f"          PEG filter (P/E <= revenue growth)")
        print(f"  Risk:   ATR-based stops (1.5x ATR)")
        print(f"          Score-based sizing (1%-2.5% risk)")
        print(f"          Max {MAX_PER_SECTOR} positions per sector")
        print(f"          Circuit breaker at -{pf.DRAWDOWN_HALT_PCT:.0%} drawdown")
        print(f"          Fee model: {pf.SLIPPAGE_PCT:.2%}/trade slippage")
        print(f"  Target: 2R / 3R / 4R + ATR trail")
        print(f"  Exits:  Time stop after {pf.TIME_STOP_HOURS}h if no TP1")
        print(f"          SL moves to breakeven after TP1")
        print(f"  Cash:   Manual baseline deploy (use --deploy-baseline)")
        print(f"  Max:    {pf.MAX_POSITIONS} swing positions + manual QQQ baseline")
        print(f"{'='*60}")
        print("  Press Ctrl+C to stop.\n")

        # Pre-market warmup: load cache, pre-screen, show briefing
        market_open, _ = pf.is_market_open()
        if not market_open:
            premarket_warmup()

        while True:
            try:
                run_live_cycle()
                market_open, _ = pf.is_market_open()
                if market_open:
                    print("  Sleeping 60s...")
                    time.sleep(60)
                else:
                    secs = pf.seconds_until_open()
                    if secs <= 1800 and not getattr(run_live_cycle, '_warmed_up', False):
                        # 30 min before open — run warmup once
                        premarket_warmup()
                        run_live_cycle._warmed_up = True
                        print("  Sleeping 60s...")
                        time.sleep(60)
                    else:
                        # Pre-market: heartbeat every 10 minutes with countdown
                        h, m = divmod(secs // 60, 60)
                        print(f"  Market opens in {h}h {m}m. Next heartbeat in 10m...")
                        time.sleep(600)  # 10 minutes
            except KeyboardInterrupt:
                print("\n  Shutting down gracefully...")
                break
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                time.sleep(10)
    else:
        run_live_cycle()
