
import pandas as pd
import numpy as np
import yfinance as yf
import datetime
import plotly.graph_objects as go
import warnings
import time
import news_engine  # Use our existing news engine

warnings.simplefilter(action='ignore', category=FutureWarning)

# ── Universe (70 Stocks + 30 ETFs) ────────────────────────────────────────────
STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "LLY", "AVGO",
    "JPM", "V", "UNH", "XOM", "MA", "JNJ", "HD", "PG", "COST", "ABBV",
    "MRK", "CRM", "AMD", "NFLX", "BAC", "WMT", "ACN", "ADBE", "CVX", "PEP",
    "LIN", "KO", "DIS", "TMO", "MCD", "CSCO", "ABT", "INTC", "WFC", "VZ",
    "CMCSA", "DHR", "INTU", "NKE", "PFE", "TXN", "PM", "AMGN", "IBM", "UNP",
    "NOW", "GE", "SPGI", "CAT", "BA", "HON", "COP", "RTX", "GS", "PLD",
    "AMAT", "BKNG", "ELV", "BLK", "UBER", "MDT", "TJX", "ADP", "GILD", "SBUX"
]

ETFS = [
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "VEA", "VWO", "TLT", "IEF",
    "LQD", "HYG", "GLD", "SLV", "USO", "XLE", "XLF", "XLK", "XLV", "XLI",
    "XLP", "XLY", "XLU", "XLB", "XLRE", "SMH", "IBB", "ARKK", "EEM", "FXI"
]

UNIVERSE = STOCKS + ETFS

# ── Configuration ─────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100000.0
MAX_POSITIONS = 7
POSITION_PCT = 1.0 / MAX_POSITIONS  # ~14% per trade
STOP_LOSS_PCT = 0.025     # 2.5% Hard Stop
TAKE_PROFIT_PCT = 0.050   # 5.0% Target
SIMULATION_DAYS = 14      # Last 2 weeks
TIMEFRAME = "1h"          # Hourly data

# ── Strategy Logic ────────────────────────────────────────────────────────────
def calculate_indicators(df):
    """Adds SMA200, RSI, and Price Change to the dataframe."""
    if df.empty:
        return df
    
    # Needs minimum data
    if len(df) < 200:
        return df

    # SMA 200 (Long-term Trend Filter)
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    
    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

class Portfolio:
    def __init__(self, initial_capital):
        self.cash = initial_capital
        self.holdings = {} # {ticker: {'qty': int, 'entry_price': float}}
        self.trade_log = []
        self.equity_curve = []

    def total_equity(self, current_prices):
        equity = self.cash
        for ticker, pos in self.holdings.items():
            price = current_prices.get(ticker, pos['entry_price'])
            equity += pos['qty'] * price
        return equity

    def update_curve(self, time, equity):
        self.equity_curve.append({'time': time, 'equity': equity})

    def enter(self, ticker, price, time):
        if len(self.holdings) >= MAX_POSITIONS:
            return False
            
        cost = INITIAL_CAPITAL * POSITION_PCT
        if self.cash < cost:
            return False
            
        qty = int(cost / price)
        if qty == 0:
            return False
            
        self.cash -= qty * price
        self.holdings[ticker] = {
            'qty': qty,
            'entry_price': price,
            'entry_time': time,
            'sl': price * (1 - STOP_LOSS_PCT),
            'tp': price * (1 + TAKE_PROFIT_PCT)
        }
        return True

    def exit(self, ticker, price, time, reason):
        if ticker not in self.holdings:
            return
            
        pos = self.holdings[ticker]
        qty = pos['qty']
        proceeds = qty * price
        self.cash += proceeds
        
        pnl = proceeds - (qty * pos['entry_price'])
        pnl_pct = (price - pos['entry_price']) / pos['entry_price']
        
        self.trade_log.append({
            'Ticker': ticker,
            'Entry Time': pos['entry_time'],
            'Exit Time': time,
            'Entry Price': pos['entry_price'],
            'Exit Price': price,
            'PnL': pnl,
            'PnL %': pnl_pct,
            'Reason': reason
        })
        del self.holdings[ticker]

# ── Engine ────────────────────────────────────────────────────────────────────
def run_simulation():
    print(f"\n{'='*60}")
    print(f"  ULTIMATE TRADER: MONEY MACHINE SIMULATION")
    print(f"  Universe: {len(STOCKS)} Stocks, {len(ETFS)} ETFs")
    print(f"  Strategy: Trend Pullback (SMA200 + RSI<35)")
    print(f"  Risk: 2.5% Stop Loss, 5.0% Take Profit")
    print(f"{'='*60}\n")
    
    print(f"Downloading {SIMULATION_DAYS} days of hourly data...")
    try:
        # Buffer days to ensure we have 200 candles for SMA
        download_period = f"{min(59, SIMULATION_DAYS + 25)}d" 
        data = yf.download(
            " ".join(UNIVERSE), 
            period=download_period, 
            interval=TIMEFRAME, 
            group_by='ticker', 
            progress=True,
            threads=True
        )
    except Exception as e:
        print(f"Download Error: {e}")
        return

    # Process Indicators
    indicators = {}
    print("Computing technical indicators...")
    valid_tickers = []
    
    # Handle single ticker case vs multi-ticker index
    is_multi = len(UNIVERSE) > 1
    
    for ticker in UNIVERSE:
        try:
            if is_multi:
                df = data[ticker].copy()
            else:
                df = data.copy()
                
            df = df.dropna(how='all')
            if df.empty: continue
            
            df = calculate_indicators(df)
            
            # Trim to simulation start (keep buffer for SMA calculation, 
            # but simulation loop starts after SMA is valid)
            if len(df) > 200:
                indicators[ticker] = df
                valid_tickers.append(ticker)
        except KeyError:
            continue
            
    if not valid_tickers:
        print("No valid data.")
        return

    print(f"Ready. Simulating on {len(valid_tickers)} assets...")
    
    # Master Timeline: use intersection of indices to ensure alignment, 
    # or just use the index of a major ETF like SPY
    if "SPY" in valid_tickers:
        timeline = indicators["SPY"].iloc[200:].index # Start after SMA
    else:
        timeline = indicators[valid_tickers[0]].iloc[200:].index
        
    portfolio = Portfolio(INITIAL_CAPITAL)
    
    for t in timeline:
        current_prices = {}
        
        # 1. Update Prices & Check Exits
        # Iterate snapshot of keys to allow deletion
        active_positions = list(portfolio.holdings.keys())
        
        for ticker in valid_tickers:
            df = indicators[ticker]
            if t not in df.index: continue
            
            price = df.loc[t]['Close']
            current_prices[ticker] = price
            
            if ticker in active_positions:
                pos = portfolio.holdings[ticker]
                if price <= pos['sl']:
                    portfolio.exit(ticker, price, t, "Stop Loss")
                elif price >= pos['tp']:
                    portfolio.exit(ticker, price, t, "Take Profit")
                # Time Stop / End of Sim logic is handled at very end
        
        portfolio.update_curve(t, portfolio.total_equity(current_prices))
        
        # 2. Check Entries
        if len(portfolio.holdings) < MAX_POSITIONS:
            for ticker in valid_tickers:
                if ticker in portfolio.holdings: continue
                
                df = indicators[ticker]
                if t not in df.index: continue
                
                row = df.loc[t]
                
                # DATA GAP CHECK
                if pd.isna(row['Close']) or pd.isna(row['SMA_200']) or pd.isna(row['RSI']):
                    continue
                    
                # STRATEGY:
                # 1. TREND: Price > SMA 200 (Only Buy Uptrends)
                if row['Close'] <= row['SMA_200']:
                    continue
                    
                # 2. SETUP: RSI < 35 (Oversold Pullback)
                if row['RSI'] >= 35:
                    continue
                    
                # 3. TRIGGER: Reversal Candle (Close > Open) - Primitive verification of support
                # Note: In hourly data, this means we buy at the CLOSE of a green hour
                if row['Close'] <= row['Open']:
                    continue
                
                # (Optional) Check News Sentiment
                # For simulation speed, we skip live network calls here, 
                # but in Live Mode we would check news_engine.
                
                if portfolio.enter(ticker, row['Close'], t):
                    if len(portfolio.holdings) >= MAX_POSITIONS:
                        break

    # Close all at end
    last_time = timeline[-1]
    for ticker in list(portfolio.holdings.keys()):
        price = current_prices.get(ticker, portfolio.holdings[ticker]['entry_price'])
        portfolio.exit(ticker, price, last_time, "End of Simulation")
        
    generate_report(portfolio)
    scan_live(indicators, valid_tickers)

# ── Reporting ─────────────────────────────────────────────────────────────────
def generate_report(portfolio):
    trades = pd.DataFrame(portfolio.trade_log)
    equity_df = pd.DataFrame(portfolio.equity_curve)
    
    final_equity = equity_df.iloc[-1]['equity'] if not equity_df.empty else INITIAL_CAPITAL
    roi = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL
    
    win_rate = 0
    if not trades.empty:
        wins = trades[trades['PnL'] > 0]
        win_rate = len(wins) / len(trades)
    
    print(f"\n{'='*30}")
    print(f"  RESULTS")
    print(f"{'='*30}")
    print(f"  Final Equity: ${final_equity:,.2f}")
    print(f"  Total Return: {roi:+.2%}")
    print(f"  Trades:       {len(trades)}")
    print(f"  Win Rate:     {win_rate:.1%}")
    print(f"{'='*30}\n")
    
    # Save HTML
    html_content = f"""
    <html>
    <head>
        <title>Money Machine Simulation</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; background: #111; color: #eee; padding: 20px; }}
            .card {{ background: #222; border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
            h1 {{ color: #4CAF50; }}
            .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }}
            .stat {{ text-align: center; }}
            .val {{ font-size: 2em; font-weight: bold; }}
            .green {{ color: #4CAF50; }}
            .red {{ color: #f44336; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th {{ background: #333; padding: 10px; text-align: left; }}
            td {{ padding: 10px; border-bottom: 1px solid #333; }}
            tr:hover {{ background: #2a2a2a; }}
        </style>
    </head>
    <body>
        <h1>MONEY MACHINE: SIMULATION REPORT</h1>
        <div class="card stat-grid">
            <div class="stat"><div>Final Equity</div><div class="val">${final_equity:,.0f}</div></div>
            <div class="stat"><div>Return</div><div class="val {'green' if roi>0 else 'red'}">{roi:+.2%}</div></div>
            <div class="stat"><div>Win Rate</div><div class="val">{win_rate:.1%}</div></div>
            <div class="stat"><div>Trades</div><div class="val">{len(trades)}</div></div>
        </div>
        <div class="card">
            <h2>Trade Log</h2>
            <table>
                <thead><tr><th>Ticker</th><th>Entry</th><th>Exit</th><th>Price In</th><th>Price Out</th><th>PnL $</th><th>PnL %</th><th>Reason</th></tr></thead>
                <tbody>
    """
    
    if not trades.empty:
        for _, t in trades.iterrows():
            c = "green" if t['PnL'] > 0 else "red"
            html_content += f"""
            <tr>
                <td><b>{t['Ticker']}</b></td>
                <td>{t['Entry Time']}</td>
                <td>{t['Exit Time']}</td>
                <td>{t['Entry Price']:.2f}</td>
                <td>{t['Exit Price']:.2f}</td>
                <td class="{c}">{t['PnL']:+.2f}</td>
                <td class="{c}">{t['PnL %']:+.2%}</td>
                <td>{t['Reason']}</td>
            </tr>
            """
    html_content += "</tbody></table></div></body></html>"
    
    with open("simulation_results.html", "w", encoding='utf-8') as f:
        f.write(html_content)
    print("Report saved: simulation_results.html")

# ── Live Scanner ──────────────────────────────────────────────────────────────
def scan_live(indicators, valid_tickers):
    print(f"\n{'='*60}")
    print(f"  LIVE SCANNED OPPORTUNITIES (Actionable Now)")
    print(f"{'='*60}")
    
    opportunities = []
    
    for ticker in valid_tickers:
        df = indicators[ticker]
        if df.empty: continue
        
        # Latest completed candle
        row = df.iloc[-1]
        
        # 1. Trend Filter
        if pd.isna(row['SMA_200']) or row['Close'] <= row['SMA_200']:
            continue
            
        # 2. Pullback Setup
        # Slightly wider net for live scanning (RSI < 40) into Watchlist
        if row['RSI'] < 40:
            quality = "HIGH" if row['RSI'] < 30 else "MED"
            
            # Check news sentiment? (Optional live check)
            # sent = news_engine.fetch_and_score(ticker)
            
            opportunities.append({
                'Ticker': ticker,
                'Price': row['Close'],
                'RSI': row['RSI'],
                'Quality': quality,
                'Trend': 'Uptrend (Above SMA200)'
            })
            
    if not opportunities:
        print("No setups found right now. Market might be overextended or in downtrend.")
    else:
        print(f"{'Ticker':<8} {'Price':<10} {'RSI':<6} {'Quality':<10} {'Notes':<20}")
        print("-" * 60)
        for op in opportunities:
            print(f"{op['Ticker']:<8} ${op['Price']:<9.2f} {op['RSI']:<6.1f} {op['Quality']:<10} {op['Trend']}")
    print("\n")

if __name__ == "__main__":
    run_simulation()
