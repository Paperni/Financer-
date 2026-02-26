import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from financer.cli.report_run import main

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "runs" / "sample_run_v1"


def test_report_run_command_generates_outputs_deterministically(tmp_path):
    # Copy fixture directly to tmp_path
    run_dir = tmp_path / "mock_run"
    shutil.copytree(FIXTURE_DIR, run_dir)
    
    # Execute CLI logic
    main(str(run_dir))
    
    # 1. Assert Files Extracted
    assert (run_dir / "ledger.csv").exists()
    assert (run_dir / "report.json").exists()
    assert (run_dir / "report.md").exists()
    
    # 2. Assert Ledger Shape
    df = pd.read_csv(run_dir / "ledger.csv")
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "AAPL"
    assert df.iloc[0]["entry_px"] == 150.0
    assert df.iloc[0]["exit_px"] == 165.0
    assert df.iloc[0]["pnl_cash"] == 150.0 # (165 - 150) * 10
    assert df.iloc[0]["hold_days"] == 9
    
    # 3. Assert Report JSON Match
    with open(run_dir / "report.json", "r") as f:
        rep = json.load(f)
        assert rep["schema_version"] == "v1"
        assert rep["portfolio"]["trades_count"] == 1
        assert rep["trades"]["win_rate"] == 1.0 # 1 out of 1
        assert rep["trades"]["avg_win_R"] > 0
        
    # 4. Assert Markup renders correctly without failing
    with open(run_dir / "report.md", "r") as f:
        md = f.read()
        assert "Financer Run Report: `sample_run_v1`" in md
        assert "100.00%" in md # Expected win rate format
