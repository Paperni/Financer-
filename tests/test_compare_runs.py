import json
import shutil
from pathlib import Path

import pytest

from financer.cli.compare_runs import main

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "runs" / "sample_run_v1"


def test_compare_runs_ranks_deterministically(tmp_path):
    # Setup two mock environments
    run_a = tmp_path / "run_A"
    run_b = tmp_path / "run_B"
    
    shutil.copytree(FIXTURE_DIR, run_a)
    shutil.copytree(FIXTURE_DIR, run_b)
    
    # Manually tilt the config or lifecycle to make B beat A
    # Easiest way in this test: modify the exit price in run B
    with open(run_b / "lifecycle.jsonl", "r") as f:
        lines = f.readlines()
        
    data = json.loads(lines[1])
    data["filled_orders"][0]["price"] = 200.0 # Huge win vs 165.0 in run A
    
    with open(run_b / "lifecycle.jsonl", "w") as f:
        f.writelines([lines[0], json.dumps(data) + "\n"])
        
    # Also fix names
    with open(run_b / "config.json", "r") as f: c = json.load(f)
    c["run_id"] = "run_B"
    with open(run_b / "config.json", "w") as f: json.dump(c, f)
    
    with open(run_a / "config.json", "r") as f: c = json.load(f)
    c["run_id"] = "run_A"
    with open(run_a / "config.json", "w") as f: json.dump(c, f)

    # Output writes to `Path.cwd() / "artifacts/comparisons"`
    # So we patch the output dir temporarily
    import financer.cli.compare_runs
    from unittest.mock import patch
    
    with patch("financer.cli.compare_runs.Path.cwd", return_value=tmp_path):
        main(str(run_a), str(run_b))
        
        comp_json = tmp_path / "artifacts" / "comparisons" / "comparison.json"
        comp_md = tmp_path / "artifacts" / "comparisons" / "comparison.md"
        
        assert comp_json.exists()
        assert comp_md.exists()
        
        with open(comp_json, "r") as f:
            ranked = json.load(f)
            
        assert len(ranked) == 2
        # Run B has a massively higher R expectancy (price 200 > 165 vs 150 entry)
        assert ranked[0]["config"]["run_id"] == "run_B"
        assert ranked[1]["config"]["run_id"] == "run_A"
        
        with open(comp_md, "r") as f:
            text = f.read()
            assert "**run_B** beat **run_A** primarily due to higher Expectancy R" in text
