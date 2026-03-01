import pytest
from financer.analytics.metrics import compute_max_drawdown_pct

def test_compute_max_drawdown_pct_synthetic():
    # Equity curve:
    # 100.0 (peak: 100.0, dd: 0.0)
    # 105.0 (peak: 105.0, dd: 0.0)
    # 94.5  (peak: 105.0, dd: (105.0 - 94.5) / 105.0 = 10.5 / 105.0 = 10.0%)
    # 120.0 (peak: 120.0, dd: 0.0)
    # 96.0  (peak: 120.0, dd: (120.0 - 96.0) / 120.0 = 24.0 / 120.0 = 20.0%)
    # 150.0 (peak: 150.0, dd: 0.0)
    
    raw_curve = [
        {"equity": 100.0},
        {"equity": 105.0},
        {"equity": 94.5},
        {"equity": 120.0},
        {"equity": 96.0},
        {"equity": 150.0},
    ]
    
    max_dd = compute_max_drawdown_pct(raw_curve)
    
    assert max_dd == pytest.approx(20.0, abs=1e-6)

def test_compute_max_drawdown_pct_empty():
    assert compute_max_drawdown_pct([]) == 0.0

def test_compute_max_drawdown_pct_missing_keys():
    # Should ignore missing keys
    raw_curve = [
        {"equity": 100.0},
        {"other": 90.0},
        {"equity": 80.0},  # DD: 20%
    ]
    
    max_dd = compute_max_drawdown_pct(raw_curve)
    
    assert max_dd == pytest.approx(20.0, abs=1e-6)
