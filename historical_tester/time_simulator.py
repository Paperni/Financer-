"""
Time Simulator for Historical Testing

Mocks time functions to simulate historical time progression during backtesting.
"""

import datetime
import zoneinfo
from contextlib import contextmanager
from unittest.mock import patch


class TimeSimulator:
    """Manages simulation time and mocks time-related functions."""
    
    def __init__(self, start_time: datetime.datetime, speed_multiplier: float = 1.0):
        """
        Initialize time simulator.
        
        Args:
            start_time: Starting datetime for simulation (timezone-aware ET)
            speed_multiplier: Speed multiplier (1.0 = real-time, 10.0 = 10x speed)
        """
        if start_time.tzinfo is None:
            # Assume ET if no timezone
            start_time = start_time.replace(tzinfo=zoneinfo.ZoneInfo("America/New_York"))
        self.current_time = start_time
        self.start_time = start_time
        self.speed_multiplier = speed_multiplier
        self._patches = []
    
    def advance(self, hours: float = 1.0):
        """Advance simulation time by specified hours."""
        delta = datetime.timedelta(hours=hours)
        self.current_time += delta
    
    def advance_to_next_market_hour(self):
        """Advance to next market hour (9:30 AM - 4:00 PM ET, Mon-Fri)."""
        # If weekend, advance to Monday 9:30 AM
        while self.current_time.weekday() >= 5:
            days_ahead = 7 - self.current_time.weekday()
            self.current_time = self.current_time.replace(
                hour=9, minute=30, second=0, microsecond=0
            ) + datetime.timedelta(days=days_ahead)
        
        # If before market open, advance to 9:30 AM
        market_open = self.current_time.replace(hour=9, minute=30, second=0, microsecond=0)
        if self.current_time < market_open:
            self.current_time = market_open
            return
        
        # If after market close, advance to next day 9:30 AM
        market_close = self.current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        if self.current_time >= market_close:
            # Advance to next trading day
            self.current_time = self.current_time + datetime.timedelta(days=1)
            self.current_time = self.current_time.replace(hour=9, minute=30, second=0, microsecond=0)
            # Skip weekends
            while self.current_time.weekday() >= 5:
                self.current_time += datetime.timedelta(days=1)
    
    def is_market_open(self) -> tuple[bool, str]:
        """Check if market is open at current simulation time."""
        if self.current_time.weekday() >= 5:
            return False, "Weekend"
        market_open = self.current_time.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = self.current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        if self.current_time < market_open:
            return False, f"Pre-Market (opens {market_open.strftime('%H:%M')} ET)"
        if self.current_time > market_close:
            return False, f"After-Hours (closed {market_close.strftime('%H:%M')} ET)"
        return True, "Market Open"
    
    def now_et(self) -> datetime.datetime:
        """Get current simulation time in ET."""
        return self.current_time
    
    def now_str(self) -> str:
        """Get current simulation time as ISO string."""
        return self.current_time.isoformat()
    
    @contextmanager
    def mock_time_functions(self):
        """Context manager to mock portfolio time functions."""
        import portfolio as pf
        
        # Create mock functions
        def mock_now_et():
            return self.now_et()
        
        def mock_now_str():
            return self.now_str()
        
        def mock_is_market_open():
            return self.is_market_open()
        
        # Patch the functions
        with patch.object(pf, 'now_et', mock_now_et), \
             patch.object(pf, 'now_str', mock_now_str), \
             patch.object(pf, 'is_market_open', mock_is_market_open):
            yield
    
    def get_elapsed_time(self) -> datetime.timedelta:
        """Get elapsed time since simulation start."""
        return self.current_time - self.start_time
    
    def get_progress_pct(self, end_time: datetime.datetime) -> float:
        """Get simulation progress percentage (0.0 to 1.0)."""
        if end_time <= self.start_time:
            return 1.0
        total = end_time - self.start_time
        elapsed = self.current_time - self.start_time
        return min(1.0, max(0.0, elapsed.total_seconds() / total.total_seconds()))
