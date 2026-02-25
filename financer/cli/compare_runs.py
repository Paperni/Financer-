"""CLI tool to scientificially compare multiple Financer run artifacts."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from financer.cli.report_run import main as report_run_main

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def generate_comparison_markdown(ranked_reports: list[dict[str, Any]]) -> str:
    """Generate Markdown for the run comparison rankings."""
    if not ranked_reports:
        return "# Run Comparison\nNo valid runs provided.\n"
        
    md = "# Financer Run Comparison Report\n\n"
    md += "### Strategy Rankings (Expectancy R -> Max Drawdown -> Exposure)\n\n"
    
    md += "| Rank | Run ID | Expectancy (R) | Max DD | Win Rate | Total Return | Trades |\n"
    md += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    
    for i, rep in enumerate(ranked_reports):
        c = rep.get("config", {})
        p = rep.get("portfolio", {})
        t = rep.get("trades", {})
        
        md += f"| #{i+1} | `{c.get('run_id', 'unknown')}` | {t.get('expectancy_R', 0):.2f}R | -{p.get('max_drawdown', 0):.2%} | {t.get('win_rate', 0):.2%} | {p.get('total_return', 0):.2%} | {p.get('trades_count', 0)} |\n"
        
    md += "\n## Summary & Deltas\n"
    # Provide a simple deterministic statement explaining why Rank 1 beat Rank 2
    if len(ranked_reports) > 1:
        top = ranked_reports[0]
        runner_up = ranked_reports[1]
        
        r1 = top.get("trades", {}).get("expectancy_R", 0)
        r2 = runner_up.get("trades", {}).get("expectancy_R", 0)
        
        d1 = top.get("portfolio", {}).get("max_drawdown", 0)
        d2 = runner_up.get("portfolio", {}).get("max_drawdown", 0)
        
        md += f"**{top['config']['run_id']}** beat **{runner_up['config']['run_id']}** "
        
        if r1 > r2:
            md += f"primarily due to higher Expectancy R ({r1:.2f}R vs {r2:.2f}R).\n"
        elif d1 < d2:
            md += f"with tied expectancy but significantly lower Peak Drawdown ({d1:.2%} vs {d2:.2%}).\n"
        else:
            md += "due to lower capital exposure and time-in-market efficiency.\n"
            
    return md


def main(*run_dirs: str):
    """Orchestrate the parsing, generating, and ranking of multiple run directories."""
    reports = []
    
    for d_str in run_dirs:
        d = Path(d_str)
        # Always force an evaluation refresh of individual reports 
        # to ensure no stale artifacts are used.
        try:
            report_run_main(str(d))
            with open(d / "report.json", "r") as f:
                reports.append(json.load(f))
        except Exception as e:
            logger.error(f"Cannot include run {d} in comparison: {e}")
            continue
            
    if not reports:
        logger.error("No valid runs could be processed. Exiting.")
        sys.exit(1)
        
    # Standard Financer Ranking Logic
    # Primary: Expectancy (R) higher is better
    # Secondary: Max Drawdown lower is better
    # Tertiary: Exposure Pct lower is better (fallback to trade counts for mock)
    def rank_sort_key(report_dict):
        exp = report_dict.get("trades", {}).get("expectancy_R", 0.0)
        dd = report_dict.get("portfolio", {}).get("max_drawdown", 0.0)
        exposure = report_dict.get("portfolio", {}).get("trades_count", 0)  # mock equivalent
        return (exp, -dd, -exposure)
        
    ranked = sorted(reports, key=rank_sort_key, reverse=True)
    
    # Dump locally to the execution cwd (not a specific run dir)
    out_dir = Path.cwd() / "artifacts" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    json_path = out_dir / "comparison.json"
    md_path = out_dir / "comparison.md"
    
    with open(json_path, "w") as f:
        json.dump(ranked, f, indent=2)
        
    with open(md_path, "w") as f:
        f.write(generate_comparison_markdown(ranked))
        
    logger.info(f"Comparison complete. Output written to: {md_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare multiple Financer run reports and generate a scientific ranking.")
    parser.add_argument("--runs", nargs="+", required=True, help="Paths to the artifact run directories to compare.")
    
    args = parser.parse_args()
    main(*args.runs)
