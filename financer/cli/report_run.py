"""CLI tool to generate metrics and a canonical report for a single Financer execution run."""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from financer.analytics.core import ARTIFACT_SCHEMA_VERSION
from financer.analytics.ledger import parse_run
from financer.analytics.metrics import (
    compute_attribution,
    compute_portfolio_metrics,
    compute_trade_metrics,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def generate_markdown_report(config: dict[str, Any], port: dict, trade: dict, attr: dict) -> str:
    """Format the report components into a clean Markdown document."""
    md = f"# Financer Run Report: `{config.get('run_id', 'unknown')}`\n\n"
    md += f"**Artifact Schema Version**: `{ARTIFACT_SCHEMA_VERSION}`\n"
    md += f"**Timeframe**: `{config.get('timeframe', 'UNKNOWN')}` | **Mode**: `{config.get('mode', 'UNKNOWN')}`\n\n"
    
    md += "## Portfolio Metrics\n"
    md += f"- **Total Return (Est)**: {port['total_return']:.2%}\n"
    md += f"- **Max Drawdown**: -{port['max_drawdown']:.2%}\n"
    md += f"- **Trades Count**: {port['trades_count']}\n\n"
    
    md += "## Trade Metrics\n"
    if port['trades_count'] > 0:
        md += f"- **Win Rate**: {trade['win_rate']:.2%}\n"
        md += f"- **Expectancy (R)**: {trade['expectancy_R']:.2f}R\n"
        md += f"- **Profit Factor**: {trade['profit_factor']:.2f}\n"
        md += f"- **Avg Win/Loss (R)**: {trade['avg_win_R']:.2f}R / {trade['avg_loss_R']:.2f}R\n"
        md += f"- **Median Hold Bars**: {trade['median_hold_bars']:.1f}\n\n"
    else:
        md += "_No closed trades evaluating R criteria._\n\n"
        
    md += "## Attribution\n"
    
    if attr.get("top_veto_reasons"):
        md += "### Top Engine Veto Reasons\n"
        for reason, count in attr["top_veto_reasons"].items():
            md += f"- {reason}: {count}\n"
        md += "\n"
        
    if attr.get("by_exit_reason"):
        md += "### Edge by Exit Reason (Avg R)\n"
        for reason, avg_r in attr["by_exit_reason"].items():
            md += f"- {reason}: {avg_r:.2f}R\n"

    return md


def main(run_dir_str: str):
    """Generate the ledger and reports for the given execution directory."""
    run_dir = Path(run_dir_str)
    
    logger.info(f"Parsing Financer run artifacts in: {run_dir}")
    try:
        df = parse_run(run_dir)
        
        # We explicitly serialize a CSV of the Canonical Ledger
        ledger_path = run_dir / "ledger.csv"
        df.to_csv(ledger_path, index=False)
        logger.info(f"Canonical Ledger serialized to: {ledger_path.name}")
        
    except FileNotFoundError as e:
        logger.error(f"Cannot parse run: {e}")
        return
    except Exception as e:
        logger.error(f"Fatal error generating ledger: {e}")
        return
        
    # Read core config parameters
    config_path = run_dir / "config.json"
    with open(config_path, "r") as f:
        config = json.load(f)
        
    lifecycle_path = str(run_dir / "lifecycle.jsonl")

    # Generate Numerical Metrics
    port_metrics = compute_portfolio_metrics(None, df)
    trade_metrics = compute_trade_metrics(df)
    attribution = compute_attribution(df, lifecycle_path=lifecycle_path)
    
    # Bundle Report
    report_dict = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "config": config,
        "portfolio": port_metrics,
        "trades": trade_metrics,
        "attribution": attribution
    }
    
    # Target files
    out_json = run_dir / "report.json"
    out_md = run_dir / "report.md"
    
    with open(out_json, "w") as f:
        json.dump(report_dict, f, indent=2)
        
    with open(out_md, "w") as f:
        f.write(generate_markdown_report(config, port_metrics, trade_metrics, attribution))
        
    logger.info(f"Saved metric artifacts: {out_json.name}, {out_md.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a canonical ledger and analytical report for a single Financer run.")
    parser.add_argument("--run", type=str, required=True, help="Path to the artifact run directory.")
    
    args = parser.parse_args()
    main(args.run)
