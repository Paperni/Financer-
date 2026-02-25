"""
Historical Data Cache for Backtesting

Provides time-aware data caching that respects simulation time boundaries.
Downloads data in rolling windows and only returns data up to current simulation time.
"""

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional
from tqdm import tqdm

try:
    from indicators import DataCache, calculate_indicators
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from indicators import DataCache, calculate_indicators


class HistoricalDataCache:
    """Historical data cache that respects simulation time boundaries."""
    
    def __init__(self, current_time: datetime, enable_news: bool = False, enable_earnings: bool = False):
        """
        Initialize historical data cache.
        
        Args:
            current_time: Current simulation time (used to slice data)
            enable_news: Whether to enable news sentiment (default: False, returns neutral)
            enable_earnings: Whether to enable earnings calendar (default: False, returns None)
        """
        self.current_time = current_time
        self.enable_news = enable_news
        self.enable_earnings = enable_earnings
        
        # Use composition to wrap DataCache
        self._base_cache = DataCache()
        
        # Store full historical data (not time-sliced yet)
        self._hourly_full = {}  # ticker -> full DataFrame
        self._daily_full = {}   # ticker -> full DataFrame
        
        # Cache for time-sliced views
        self._hourly_sliced = {}  # ticker -> sliced DataFrame (up to current_time)
        self._daily_sliced = {}   # ticker -> sliced DataFrame
    
    def update_time(self, new_time: datetime):
        """Update current simulation time and invalidate sliced caches."""
        if new_time != self.current_time:
            self.current_time = new_time
            self._hourly_sliced.clear()
            self._daily_sliced.clear()
            # Update base cache's internal state for regime calculations
            self._update_base_cache_slice()
    
    def _slice_dataframe(self, df: pd.DataFrame, max_time: datetime) -> pd.DataFrame:
        """Slice dataframe to only include rows up to max_time."""
        if df.empty:
            return df
        # Convert index to datetime if needed
        if not isinstance(df.index, pd.DatetimeIndex):
            return df
        # Filter to rows <= max_time
        max_ts = pd.Timestamp(max_time)
        if df.index.tz is not None and max_ts.tz is None:
            max_ts = max_ts.tz_localize(df.index.tz)
        elif df.index.tz is None and max_ts.tz is not None:
            max_ts = max_ts.tz_localize(None)
        
        mask = df.index <= max_ts
        return df[mask].copy()
    
    def _update_base_cache_slice(self):
        """Update base cache's internal hourly/daily dicts with sliced data."""
        # This allows base cache methods to work with time-sliced data
        self._base_cache._hourly = self._hourly_sliced.copy()
        self._base_cache._daily = self._daily_sliced.copy()
    
    def download_historical_data(self, tickers: list, start_date: datetime, end_date: datetime,
                                 progress: bool = True):
        """
        Download historical data for all tickers in rolling windows.
        
        Args:
            tickers: List of ticker symbols
            start_date: Start date for historical data
            end_date: End date for historical data
            progress: Show progress bar
        """
        print(f"  [Historical Cache] Downloading data for {len(tickers)} tickers...")
        print(f"     Period: {start_date.date()} to {end_date.date()}")
        
        # Download hourly data in 1-month rolling windows
        current = start_date
        window_days = 30
        
        all_hourly_data = {}
        all_daily_data = {}
        
        iterable = tqdm(range(0, (end_date - start_date).days, window_days), 
                       desc="Downloading windows", disable=not progress)
        
        for _ in iterable:
            window_end = min(current + timedelta(days=window_days), end_date)
            
            # Download hourly data
            try:
                period_str = f"{(window_end - current).days}d"
                hourly = yf.download(
                    tickers, start=current, end=window_end, interval="1h",
                    group_by="ticker", progress=False, threads=True,
                )
                
                is_multi = len(tickers) > 1
                for ticker in tickers:
                    try:
                        df = hourly[ticker].copy() if is_multi else hourly.copy()
                        df = df.dropna(how="all")
                        if df.empty:
                            continue
                        
                        # Calculate indicators
                        df = calculate_indicators(df)
                        
                        # Merge with existing data
                        if ticker in all_hourly_data:
                            combined = pd.concat([all_hourly_data[ticker], df])
                            combined = combined[~combined.index.duplicated(keep="last")]
                            combined = combined.sort_index()
                            all_hourly_data[ticker] = combined
                        else:
                            all_hourly_data[ticker] = df
                    except (KeyError, IndexError, TypeError):
                        continue
            except Exception as e:
                if progress:
                    print(f"  Warning: Error downloading window {current.date()}: {e}")
            
            # Download daily data (for regime/RS calculations)
            try:
                daily = yf.download(
                    tickers, start=current, end=window_end, interval="1d",
                    group_by="ticker", progress=False, threads=True,
                )
                
                is_multi = len(tickers) > 1
                for ticker in tickers:
                    try:
                        df = daily[ticker].copy() if is_multi else daily.copy()
                        df = df.dropna(how="all")
                        if df.empty:
                            continue
                        
                        if ticker in all_daily_data:
                            combined = pd.concat([all_daily_data[ticker], df])
                            combined = combined[~combined.index.duplicated(keep="last")]
                            combined = combined.sort_index()
                            all_daily_data[ticker] = combined
                        else:
                            all_daily_data[ticker] = df
                    except (KeyError, IndexError, TypeError):
                        continue
            except Exception as e:
                pass  # Daily data errors are less critical
            
            current = window_end
        
        # Store full data
        self._hourly_full = all_hourly_data
        self._daily_full = all_daily_data
        
        # Initial slice to current time
        self._refresh_slices()
        
        print(f"  [Historical Cache] Loaded {len(self._hourly_full)} tickers")
    
    def _refresh_slices(self):
        """Refresh time-sliced views based on current_time."""
        self._hourly_sliced.clear()
        self._daily_sliced.clear()
        
        for ticker, df in self._hourly_full.items():
            self._hourly_sliced[ticker] = self._slice_dataframe(df, self.current_time)
        
        for ticker, df in self._daily_full.items():
            self._daily_sliced[ticker] = self._slice_dataframe(df, self.current_time)
        
        # Update base cache
        self._update_base_cache_slice()
        
        # Update SPY regime data in base cache
        if "SPY" in self._daily_sliced:
            spy = self._daily_sliced["SPY"]
            if len(spy) >= 200:
                sma50 = spy["Close"].rolling(50).mean().iloc[-1]
                sma200 = spy["Close"].rolling(200).mean().iloc[-1]
                self._base_cache._spy_sma50 = float(sma50) if not pd.isna(sma50) else None
                self._base_cache._spy_sma200 = float(sma200) if not pd.isna(sma200) else None
            elif len(spy) >= 50:
                sma50 = spy["Close"].rolling(50).mean().iloc[-1]
                self._base_cache._spy_sma50 = float(sma50) if not pd.isna(sma50) else None
                self._base_cache._spy_sma200 = None
            else:
                self._base_cache._spy_sma50 = None
                self._base_cache._spy_sma200 = None
            
            if len(spy) > 0:
                close_val = spy["Close"].iloc[-1]
                self._base_cache._spy_close = float(close_val) if not pd.isna(close_val) else None
            else:
                self._base_cache._spy_close = None
            
            # SPY 20-day return
            if len(spy) >= 21:
                close_now = spy["Close"].iloc[-1]
                close_21 = spy["Close"].iloc[-21]
                if not pd.isna(close_now) and not pd.isna(close_21) and close_21 > 0:
                    self._base_cache._spy_return_20d = float(close_now) / float(close_21) - 1
                else:
                    self._base_cache._spy_return_20d = None
            else:
                self._base_cache._spy_return_20d = None
    
    # Delegate methods to base cache, but with time-aware slicing
    def get(self, ticker: str) -> Optional[pd.DataFrame]:
        """Get hourly data for ticker (sliced to current_time)."""
        return self._hourly_sliced.get(ticker)
    
    def get_latest_price(self, ticker: str) -> Optional[float]:
        """Get latest price for ticker (up to current_time)."""
        df = self._hourly_sliced.get(ticker)
        if df is not None and not df.empty:
            return float(df["Close"].dropna().iloc[-1])
        return None
    
    def get_latest_row(self, ticker: str) -> Optional[pd.Series]:
        """Get latest row for ticker (up to current_time)."""
        df = self._hourly_sliced.get(ticker)
        if df is not None and not df.empty:
            return df.iloc[-1]
        return None
    
    def get_relative_strength(self, ticker: str) -> Optional[float]:
        """Get relative strength (delegates to base cache)."""
        return self._base_cache.get_relative_strength(ticker)
    
    def get_atr(self, ticker: str) -> Optional[float]:
        """Get ATR (delegates to base cache)."""
        return self._base_cache.get_atr(ticker)
    
    def get_daily_sma50(self, ticker: str) -> Optional[float]:
        """Get daily SMA-50 (delegates to base cache)."""
        return self._base_cache.get_daily_sma50(ticker)
    
    def get_fundamentals(self, ticker: str) -> Optional[dict]:
        """Get fundamentals (delegates to base cache)."""
        return self._base_cache.get_fundamentals(ticker)
    
    def get_market_regime(self) -> str:
        """Get market regime (delegates to base cache)."""
        return self._base_cache.get_market_regime()
    
    def get_earnings_date(self, ticker: str) -> Optional[datetime]:
        """Get earnings date (disabled in historical mode by default)."""
        if not self.enable_earnings:
            return None
        return self._base_cache.get_earnings_date(ticker)
    
    def days_until_earnings(self, ticker: str) -> Optional[int]:
        """Get days until earnings (disabled in historical mode by default)."""
        if not self.enable_earnings:
            return None
        # For historical mode, we'd need historical earnings data
        # For now, return None (no earnings blocking)
        return None
    
    def get_news_sentiment(self, ticker: str) -> dict:
        """Get news sentiment (disabled in historical mode by default)."""
        if not self.enable_news:
            # Return neutral sentiment
            import time as _time
            return {
                "sentiment": "NEUTRAL",
                "score": 0.0,
                "adjustment": 0,
                "headline_count": 0,
                "top_headline": "",
                "cached_at": _time.time(),
            }
        # In historical mode, fetching historical news is complex
        # For now, return neutral
        import time as _time
        return {
            "sentiment": "NEUTRAL",
            "score": 0.0,
            "adjustment": 0,
            "headline_count": 0,
            "top_headline": "",
            "cached_at": _time.time(),
        }
    
    @property
    def tickers(self) -> list:
        """Get list of available tickers."""
        return list(self._hourly_sliced.keys())
    
    def clear(self):
        """Clear all cached data."""
        self._hourly_full.clear()
        self._daily_full.clear()
        self._hourly_sliced.clear()
        self._daily_sliced.clear()
        self._base_cache.clear()
