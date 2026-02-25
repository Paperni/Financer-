import yfinance as yf
from indicators import calculate_indicators, check_buy_signal_detailed
import pandas as pd

def diagnose_signals():
    tickers = ["SPY", "NVDA", "META", "AMZN"]
    print(f"Downloading hourly data for {tickers} from 2024-01-01 to 2024-03-01...")
    
    # Download the exact same hourly data the backtester used
    data = yf.download(
        tickers, start="2024-01-01", end="2024-03-01", interval="1h",
        group_by="ticker", progress=False, threads=True
    )
    
    # Download daily data for SPY regime & SMA50
    daily_data = yf.download(
        tickers, start="2023-01-01", end="2024-03-01", interval="1d",
        group_by="ticker", progress=False, threads=True
    )
    
    for ticker in tickers:
        print(f"\n--- Analyzing {ticker} ---")
        if ticker not in data or data[ticker].dropna(how="all").empty:
            print("No hourly data.")
            continue
            
        df_hourly = data[ticker].dropna(how="all").copy()
        df_hourly = calculate_indicators(df_hourly)
        
        df_daily = daily_data[ticker].dropna(how="all").copy() if ticker in daily_data else pd.DataFrame()
        
        # Test every hourly bar
        max_score = 0
        best_reasons = {}
        best_time = None
        
        for idx, row in df_hourly.iterrows():
            # Get daily SMA50 roughly matching this time
            daily_sma50 = None
            if not df_daily.empty:
                # Find the closest preceding daily bar
                daily_mask = df_daily.index <= idx
                if daily_mask.any():
                    past_daily = df_daily[daily_mask]
                    if len(past_daily) >= 50:
                        daily_sma50 = past_daily["Close"].rolling(50).mean().iloc[-1]
            
            # Use mock relative strength and peg to see if base technicals ever trigger
            is_buy, score, reasons = check_buy_signal_detailed(
                row, 
                relative_strength=1.1,  # Mock passing
                volume_contracting=True, # Mock passing
                fundamentals={"pe": 15, "revenue_growth": 20}, # Mock passing
                daily_sma50=daily_sma50
            )
            
            if score > max_score:
                max_score = score
                best_reasons = reasons
                best_time = idx
                
        print(f"Max score achieved: {max_score} / 8 at {best_time}")
        print(f"Reasons met: {best_reasons}")

if __name__ == "__main__":
    diagnose_signals()
