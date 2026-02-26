import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from financer.cli.run_live import main
from financer.engines.swing.engine import SwingEngine
from financer.live.config import CONSERVATIVE_PROFILE, ExecutionMode
from financer.live.loop import run_live_once
from financer.models.portfolio import PortfolioSnapshot, PositionState
from financer.models.risk import RiskState
from financer.models.enums import EngineSource


@pytest.fixture
def mock_features():
    dates = pd.date_range("2025-01-01", periods=1, tz=timezone.utc)
    return pd.DataFrame({
        "Close": [100.0], "atr_14": [2.0], "sma_50": [90.0], "above_50": [True],
        "regime": ["RISK_ON"], "rsi_14": [35.0], "macd_hist": [0.5], "rs_20": [1.1],
        "peg_proxy": [1.0], "earnings_within_7d": [False], "roc_20": [0.15]
    }, index=dates)


@pytest.fixture
def base_context():
    config = CONSERVATIVE_PROFILE.model_copy()
    config.artifact_root = "tmp_artifacts"
    config.universe = ["SPY"]
    
    port = PortfolioSnapshot(cash=100_000.0, positions=[])
    risk = RiskState()
    
    from financer.core.orchestrator import CIOOrchestrator
    from financer.execution.broker_sim import SimBroker
    from financer.execution.position_manager import PositionManager
    
    return {
        "config": config,
        "portfolio": port,
        "risk_state": risk,
        "engine": SwingEngine(min_entry_score=4.0),
        "orchestrator": CIOOrchestrator(),
        "pos_manager": PositionManager(),
        "broker": SimBroker()
    }


def test_live_loop_dry_run_generates_artifacts(tmp_path, mock_features, base_context):
    ctx = base_context
    ctx["config"].artifact_root = str(tmp_path)
    ctx["config"].mode = ExecutionMode.DRY_RUN
    
    run_dir = tmp_path / ctx["config"].run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    with patch("financer.live.loop.build_features", return_value=mock_features):
        port = run_live_once(**ctx, run_dir=run_dir)
        
    assert port.cash == 100_000.0
    assert len(port.positions) == 0  # Dry run means NO execution
    
    # Check artifacts written
    assert (run_dir / "lifecycle.jsonl").exists()
    assert (run_dir / "cycle_logs.jsonl").exists()
    assert (run_dir / "positions.json").exists()
    
    with open(run_dir / "lifecycle.jsonl", "r") as f:
        log_line = json.loads(f.readline())
        assert len(log_line["created_orders"]) > 0
        assert "dry_run" in log_line["created_orders"][0]["veto_reason"]


def test_kill_switch_vetoes_entries_but_allows_exits(tmp_path, mock_features, base_context):
    ctx = base_context
    ctx["config"].artifact_root = str(tmp_path)
    ctx["config"].mode = ExecutionMode.AUTO
    ctx["config"].universe = ["SPY", "QQQ"]  # Add QQQ so builder evaluates it
    run_dir = tmp_path / ctx["config"].run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Pre-existing position that hit stop loss
    pos = PositionState(
        ticker="QQQ", qty=10, entry_price=100.0, current_price=100.0, stop_loss=90.0,
        source=EngineSource.SWING, opened_at=datetime(2025,1,1, tzinfo=timezone.utc)
    )
    ctx["portfolio"].positions.append(pos)
    
    def my_build(*args):
        if args[0] == "SPY": return mock_features # SPY generates a BUY intent
        return pd.DataFrame({"Close": [85.0], "atr_14": [2.0]}, index=mock_features.index) # Stop out QQQ
        
    with patch("financer.live.loop.build_features", side_effect=my_build):
        with patch("pathlib.Path.cwd") as mock_cwd:
            # Fake the kill switch file existing
            mock_cwd.return_value = tmp_path
            (tmp_path / "KILL_SWITCH").touch()
            
            port = run_live_once(**ctx, run_dir=run_dir)
            
    # SPY should NOT be bought. QQQ should be SOLD.
    assert len(port.positions) == 0
    
    # Read log
    with open(run_dir / "lifecycle.jsonl", "r") as f:
        log_line = json.loads(f.readline())
        # QQQ Sell was filled
        assert len(log_line["filled_orders"]) == 1
        assert log_line["filled_orders"][0]["ticker"] == "QQQ"
        assert log_line["filled_orders"][0]["direction"] == "SELL"


def test_flatten_now_liquidates_and_ignores_entries(tmp_path, mock_features, base_context):
    ctx = base_context
    ctx["config"].artifact_root = str(tmp_path)
    ctx["config"].mode = ExecutionMode.AUTO
    run_dir = tmp_path / ctx["config"].run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    pos = PositionState(
        ticker="AAPL", qty=10, entry_price=100.0, current_price=100.0,
        source=EngineSource.SWING, opened_at=datetime(2025,1,1, tzinfo=timezone.utc)
    )
    ctx["portfolio"].positions.append(pos)
    
    # We ignore standard stop loss, we just FLATTEN
    with patch("financer.live.loop.build_features", return_value=mock_features):
        with patch("pathlib.Path.cwd") as mock_cwd:
            mock_cwd.return_value = tmp_path
            (tmp_path / "FLATTEN_NOW").touch()
            
            port = run_live_once(**ctx, run_dir=run_dir)
            
    assert len(port.positions) == 0
    
    with open(run_dir / "lifecycle.jsonl", "r") as f:
        log_line = json.loads(f.readline())
        assert len(log_line["filled_orders"]) == 1
        assert log_line["filled_orders"][0]["ticker"] == "AAPL"


def test_max_daily_drawdown_vetoes_entries(tmp_path, mock_features, base_context):
    ctx = base_context
    ctx["config"].artifact_root = str(tmp_path)
    ctx["config"].mode = ExecutionMode.AUTO
    ctx["config"].max_daily_dd_pct = 0.02
    run_dir = tmp_path / ctx["config"].run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    ctx["portfolio"].initial_capital = 100_000.0
    # Simulate a port equity crash of 5% (> 2% limit) today
    ctx["portfolio"].cash = 95_000.0 
    
    with patch("financer.live.loop.build_features", return_value=mock_features):
        port = run_live_once(**ctx, run_dir=run_dir)
        
    # Should not buy SPY
    assert len(port.positions) == 0


def test_manual_mode_filters_unapproved_intents(tmp_path, mock_features, base_context):
    ctx = base_context
    ctx["config"].artifact_root = str(tmp_path)
    ctx["config"].mode = ExecutionMode.MANUAL
    run_dir = tmp_path / ctx["config"].run_id
    app_dir = run_dir / "approvals"
    app_dir.mkdir(parents=True, exist_ok=True)
    
    # SPY generates an intent, but we do NOT provide an approval file
    with patch("financer.live.loop.build_features", return_value=mock_features):
        port = run_live_once(**ctx, run_dir=run_dir)
        
    assert len(port.positions) == 0
    with open(run_dir / "lifecycle.jsonl", "r") as f:
        log_line = json.loads(f.readline())
        # The Orchestrator formulated the order, but it got VETOED by manual review filter
        # And the created_orders logs the OrderStatus veto string, not the intent.
        assert len(log_line["created_orders"]) > 0
        assert any("manual_approval" in o.get("veto_reason", "") for o in log_line["created_orders"])
