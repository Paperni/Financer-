from datetime import datetime, timezone
import pandas as pd
from financer.execution.position_manager import PositionManager
from financer.models.portfolio import PortfolioSnapshot, PositionState
from financer.models.enums import EngineSource


def test_position_manager_time_stop():
    pos = PositionState(
        ticker="AAPL", qty=10, entry_price=100.0, current_price=100.0,
        source=EngineSource.SWING,
        opened_at=datetime(2025, 1, 1, tzinfo=timezone.utc)
    )
    port = PortfolioSnapshot(cash=0.0, positions=[pos])
    
    pm = PositionManager()
    
    # 20 days later
    latest = {"AAPL": pd.Series({"Close": 95.0, "atr_14": 2.0})}
    
    exits, trails = pm.evaluate_exits(port, latest, datetime(2025, 1, 25, tzinfo=timezone.utc))
    
    assert len(exits) == 1
    assert exits[0].reasons[0].code == "TIME_STOP"
    assert len(trails) == 0


def test_position_manager_trailing_stop_pure_mutation():
    pos = PositionState(
        ticker="AAPL", qty=10, entry_price=100.0, current_price=100.0,
        stop_loss=90.0, source=EngineSource.SWING,
        opened_at=datetime(2025, 1, 1, tzinfo=timezone.utc)
    )
    port = PortfolioSnapshot(cash=0.0, positions=[pos])
    
    pm = PositionManager()
    
    # 1R = 1.5 * 2.0 = 3.0. TP1 = 100 + (2.0 * 3.0) = 106.
    # Current price = 104. Trail = 104 - (1.0 * 2.0) = 102.
    # 102 > original SL of 90, so it suggests trail update to 102.
    latest = {"AAPL": pd.Series({"Close": 104.0, "atr_14": 2.0})}
    
    exits, trails = pm.evaluate_exits(port, latest, datetime(2025, 1, 3, tzinfo=timezone.utc))
    
    assert len(exits) == 0
    assert "AAPL" in trails
    assert trails["AAPL"] == 102.0
    
    # Ensure port was not mutated inline
    assert port.positions[0].stop_loss == 90.0
