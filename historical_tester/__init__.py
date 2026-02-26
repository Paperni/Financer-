"""
Historical Trading Tester Module

Provides tools for testing the live trading bot on historical data
in accelerated mode with comprehensive performance metrics.
"""

try:
    from .tester import HistoricalTester
    from .time_simulator import TimeSimulator
    from .historical_cache import HistoricalDataCache
    from .metrics import MetricsCollector
    from .report_generator import ReportGenerator
except ModuleNotFoundError:
    # Allow lightweight imports (for --help / static inspection) when optional
    # runtime dependencies like yfinance are not installed.
    HistoricalTester = None
    TimeSimulator = None
    HistoricalDataCache = None
    MetricsCollector = None
    ReportGenerator = None

__all__ = [
    'HistoricalTester',
    'TimeSimulator',
    'HistoricalDataCache',
    'MetricsCollector',
    'ReportGenerator',
]
