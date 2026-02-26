
import pandas as pd
import yfinance as yf
import warnings

from data_static import BROAD_STOCKS, BROAD_ETFS
from portfolio import Portfolio, MAX_POSITIONS
from indicators import (
    calculate_indicators, calculate_momentum_score, check_buy_signal
)

warnings.simplefilter(action="ignore", category=FutureWarning)

# ── Configuration ─────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100000.0
SIMULATION_DAYS = 7
SELECTION_LOOKBACK = "6mo"
TARGET_STOCKS = 80
TARGET_ETFS = 20


# ── The Brain: Asset Selection ────────────────────────────────────────────────
def draft_assets(tickers, n_select, description):
    print(f"  Scouting {len(tickers)} {description}...", end=" ", flush=True)
    try:
        data = yf.download(
            tickers, period=SELECTION_LOOKBACK, interval="1d",
            group_by="ticker", progress=False, threads=True,
        )
    except Exception as e:
        print(f"Failed: {e}")
        return []

    scores = []
    is_multi = len(tickers) > 1

    for ticker in tickers:
        try:
            df = data[ticker].copy() if is_multi else data.copy()
            df = df.dropna(how="all")
            if df.empty:
                continue
            s = calculate_momentum_score(df)
            scores.append((ticker, s))
        except KeyError:
            continue

    scores.sort(key=lambda x: x[1], reverse=True)
    selected = [x[0] for x in scores[:n_select]]
    print(f"Drafted {len(selected)} best candidates.")
    return selected


def run_draft():
    print(f"\n{'='*60}")
    print(f"  PHASE 1: THE DRAFT (Asset Selection)")
    print(f"{'='*60}")
    univ_stocks = draft_assets(BROAD_STOCKS, TARGET_STOCKS, "Stocks")
    univ_etfs = draft_assets(BROAD_ETFS, TARGET_ETFS, "ETFs")
    final_universe = univ_stocks + univ_etfs
    print(f"\n  >> DRAFT COMPLETE. Selected {len(final_universe)} Assets for Trading.")
    print(f"     Stocks: {', '.join(univ_stocks[:5])}...")
    print(f"     ETFs:   {', '.join(univ_etfs[:3])}...")
    return final_universe


# ── Exported for live_trader compatibility ───────────────────────────────────
def calculate_hourly_indicators(df):
    """Wrapper for backward compatibility with live_trader imports."""
    return calculate_indicators(df, sma_period=50, rsi_period=14)


# ── The Machine: Trading Engine ──────────────────────────────────────────────
def run_simulation(universe):
    print(f"\n{'='*60}")
    print(f"  PHASE 2: THE SIMULATION (Trading the Basket)")
    print(f"  Capital: ${INITIAL_CAPITAL:,.0f} | Period: Last {SIMULATION_DAYS} Days (Hourly)")
    print(f"  Risk: SL 8% | TP: 8%/15%/25% + Runner")
    print(f"{'='*60}")

    print(f"  Downloading hourly data for {len(universe)} assets...")
    try:
        data = yf.download(
            universe, period="1mo", interval="1h",
            group_by="ticker", progress=True, threads=True,
        )
    except Exception as e:
        print(f"Download error: {e}")
        return

    indicators = {}
    valid_tickers = []
    is_multi = len(universe) > 1

    print("  Preparing strategy indicators...")
    for ticker in universe:
        try:
            df = data[ticker].copy() if is_multi else data.copy()
            df = df.dropna(how="all")
            if df.empty:
                continue
            df = calculate_indicators(df, sma_period=50)
            if len(df) > 50:
                indicators[ticker] = df
                valid_tickers.append(ticker)
        except KeyError:
            continue

    if not valid_tickers:
        print("No valid data.")
        return

    timeline = indicators[valid_tickers[0]].iloc[50:].index
    portfolio = Portfolio(INITIAL_CAPITAL)

    print("  Running Hourly Loop...")
    for t in timeline:
        current_prices = {}
        active_positions = list(portfolio.holdings.keys())

        # 1. Update Prices & Check Exits
        for ticker in valid_tickers:
            df = indicators[ticker]
            if t not in df.index:
                continue
            price = df.loc[t]["Close"]
            current_prices[ticker] = price

            if ticker in active_positions:
                portfolio.check_exits(ticker, price, t)

        portfolio.update_curve(t, portfolio.total_equity(current_prices))

        # 2. Entries
        if len(portfolio.holdings) < portfolio.max_positions:
            for ticker in valid_tickers:
                if ticker in portfolio.holdings:
                    continue
                df = indicators[ticker]
                if t not in df.index:
                    continue
                row = df.loc[t]

                if check_buy_signal(row):
                    if portfolio.enter(ticker, row["Close"], t):
                        if len(portfolio.holdings) >= portfolio.max_positions:
                            break

    # Close all at end
    last_time = timeline[-1]
    for ticker in list(portfolio.holdings.keys()):
        price = current_prices.get(ticker, portfolio.holdings[ticker]["entry_price"])
        portfolio.exit(ticker, price, last_time, "End of Sim")

    generate_report(portfolio, indicators, valid_tickers)


def generate_report(portfolio, indicators, valid_tickers):
    trades = pd.DataFrame(portfolio.trade_log)
    equity_df = pd.DataFrame(portfolio.equity_curve)

    final_equity = equity_df.iloc[-1]["equity"] if not equity_df.empty else INITIAL_CAPITAL
    roi = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL

    win_rate = 0
    if not trades.empty:
        wins = trades[trades["PnL"] > 0]
        win_rate = len(wins) / len(trades)

    print(f"\n{'='*30}")
    print(f"  SMART TRADER RESULTS")
    print(f"{'='*30}")
    print(f"  Final:    ${final_equity:,.2f}")
    print(f"  Return:   {roi:+.2%}")
    print(f"  Trades:   {len(trades)}")
    print(f"  Batting:  {win_rate:.1%}")
    print(f"{'='*30}\n")

    html = f"""<html><body style='font-family:sans-serif;padding:20px;background:#111;color:#eee'>
    <h1 style='color:#4CAF50'>SMART TRADER REPORT</h1>
    <h2>Performance: {roi:+.2%} (${final_equity:,.0f})</h2>
    <h3>Win Rate: {win_rate:.1%} ({len(trades)} trades)</h3>
    <table style='width:100%;text-align:left;border-collapse:collapse'>
    <thead style='background:#333'><tr><th>Ticker</th><th>PnL $</th><th>PnL %</th><th>Reason</th></tr></thead>
    <tbody>"""

    if not trades.empty:
        for _, t in trades.iterrows():
            c = "#4CAF50" if t["PnL"] > 0 else "#f44336"
            html += f"<tr><td>{t['Ticker']}</td><td style='color:{c}'>{t['PnL']:+.2f}</td><td style='color:{c}'>{t['PnL %']:+.2%}</td><td>{t['Reason']}</td></tr>"

    html += "</tbody></table></body></html>"
    with open("smart_results.html", "w") as f:
        f.write(html)
    print("Report saved (smart_results.html).")

    scan_live(indicators, valid_tickers)


def scan_live(indicators, valid_tickers):
    print(f"\n  >> SCANNING FOR LIVE OPPORTUNITIES (Based on Selected Basket)...")
    opportunities = []
    for ticker in valid_tickers:
        df = indicators[ticker]
        if df.empty:
            continue
        row = df.iloc[-1]

        if check_buy_signal(row):
            opportunities.append({
                "Ticker": ticker,
                "Price": row["Close"],
                "RSI": row["RSI"],
            })

    if not opportunities:
        print("  No setups found right now.")
    else:
        print(f"  Found {len(opportunities)} Actionable Signals:")
        for op in opportunities:
            print(f"  [BUY] {op['Ticker']:<5} @ ${op['Price']:<8.2f} (RSI: {op['RSI']:.1f})")


if __name__ == "__main__":
    basket = run_draft()
    if basket:
        run_simulation(basket)
