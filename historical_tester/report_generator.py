"""
Report Generator for Historical Testing

Generates comprehensive reports in HTML, JSON, and CSV formats.
"""

import json
import csv
import pandas as pd
from pathlib import Path
from typing import Dict, List
from datetime import datetime

try:
    import plotly.graph_objects as go
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


class ReportGenerator:
    """Generates performance reports in multiple formats."""
    
    def __init__(self, output_dir: str = "test_results"):
        """Initialize report generator."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def generate_all_reports(self, metrics: dict, test_config: dict):
        """Generate all report formats."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # HTML report
        html_path = self.output_dir / f"historical_test_{timestamp}.html"
        self.generate_html_report(metrics, test_config, html_path)
        
        # JSON report
        json_path = self.output_dir / f"historical_test_{timestamp}.json"
        self.generate_json_report(metrics, test_config, json_path)
        
        # CSV reports
        csv_dir = self.output_dir / f"historical_test_{timestamp}_csv"
        csv_dir.mkdir(exist_ok=True)
        self.generate_csv_reports(metrics, csv_dir)
        
        return {
            "html": str(html_path),
            "json": str(json_path),
            "csv_dir": str(csv_dir),
        }
    
    def generate_html_report(self, metrics: dict, test_config: dict, output_path: Path):
        """Generate interactive HTML report with charts."""
        html_parts = []
        
        # Header
        html_parts.append("""
<!DOCTYPE html>
<html>
<head>
    <title>Historical Trading Test Report</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0f0f13; color: #e0e0e0; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        .card { background: #1e1e24; padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h1 { color: #4CAF50; border-bottom: 2px solid #333; padding-bottom: 10px; }
        h2 { color: #66BB6A; margin-top: 30px; }
        .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
        .metric { background: #2a2a35; padding: 15px; border-radius: 8px; }
        .metric-label { font-size: 0.9em; color: #aaa; margin-bottom: 5px; }
        .metric-value { font-size: 1.8em; font-weight: bold; }
        .positive { color: #4CAF50; }
        .negative { color: #f44336; }
        .neutral { color: #FF9800; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #333; }
        th { background: #2a2a35; color: #66BB6A; }
        tr:hover { background: #2a2a35; }
    </style>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
</head>
<body>
    <div class="container">
        <h1>Historical Trading Test Report</h1>
""")
        
        # Test configuration
        html_parts.append(f"""
        <div class="card">
            <h2>Test Configuration</h2>
            <div class="metric-grid">
                <div class="metric">
                    <div class="metric-label">Start Date</div>
                    <div class="metric-value">{test_config.get('start_date', 'N/A')}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">End Date</div>
                    <div class="metric-value">{test_config.get('end_date', 'N/A')}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Initial Capital</div>
                    <div class="metric-value">${test_config.get('initial_capital', 0):,.0f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Speed Multiplier</div>
                    <div class="metric-value">{test_config.get('speed_multiplier', 1)}x</div>
                </div>
            </div>
        </div>
""")
        
        # Key metrics
        html_parts.append(f"""
        <div class="card">
            <h2>Performance Summary</h2>
            <div class="metric-grid">
                <div class="metric">
                    <div class="metric-label">Final Equity</div>
                    <div class="metric-value">${metrics.get('final_equity', 0):,.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Total Return</div>
                    <div class="metric-value {'positive' if metrics.get('total_return_pct', 0) >= 0 else 'negative'}">
                        {metrics.get('total_return_pct', 0):+.2f}%
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Net Return</div>
                    <div class="metric-value {'positive' if metrics.get('net_return_pct', 0) >= 0 else 'negative'}">
                        {metrics.get('net_return_pct', 0):+.2f}%
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Total Trades</div>
                    <div class="metric-value">{metrics.get('total_trades', 0)}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Win Rate</div>
                    <div class="metric-value {'positive' if metrics.get('win_rate_pct', 0) >= 50 else 'negative'}">
                        {metrics.get('win_rate_pct', 0):.1f}%
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Max Drawdown</div>
                    <div class="metric-value negative">
                        {metrics.get('max_drawdown_pct', 0):.2f}%
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Sharpe Ratio</div>
                    <div class="metric-value {'positive' if metrics.get('sharpe_ratio', 0) and metrics.get('sharpe_ratio', 0) > 1 else 'neutral'}">
                        {metrics.get('sharpe_ratio', 'N/A') if metrics.get('sharpe_ratio') is not None else 'N/A'}
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Total Fees</div>
                    <div class="metric-value">${metrics.get('total_fees', 0):,.2f}</div>
                </div>
            </div>
        </div>
""")
        
        # Equity curve chart
        if metrics.get("equity_curve") and HAS_PLOTLY:
            equity_df = pd.DataFrame(metrics["equity_curve"], columns=["timestamp", "equity"])
            equity_df["timestamp"] = pd.to_datetime(equity_df["timestamp"])
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=equity_df["timestamp"],
                y=equity_df["equity"],
                mode='lines',
                name='Equity',
                line=dict(color='#4CAF50', width=2)
            ))
            fig.add_hline(y=metrics.get('initial_capital', 0), line_dash="dash", 
                         line_color="gray", annotation_text="Initial Capital")
            
            fig.update_layout(
                title="Equity Curve",
                xaxis_title="Time",
                yaxis_title="Equity ($)",
                template="plotly_dark",
                height=400,
            )
            
            html_parts.append(f"""
        <div class="card">
            <h2>Equity Curve</h2>
            <div id="equity-chart"></div>
            <script>
                var equityData = {fig.to_json()};
                Plotly.newPlot('equity-chart', equityData.data, equityData.layout);
            </script>
        </div>
""")
        
        # Trade distribution
        if metrics.get("trade_distribution"):
            dist = metrics["trade_distribution"]
            html_parts.append(f"""
        <div class="card">
            <h2>Trade Distribution</h2>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Average PnL</td><td>${dist.get('pnl_mean', 0):,.2f}</td></tr>
                <tr><td>Median PnL</td><td>${dist.get('pnl_median', 0):,.2f}</td></tr>
                <tr><td>Std Dev</td><td>${dist.get('pnl_std', 0):,.2f}</td></tr>
                <tr><td>Best Trade</td><td>${dist.get('pnl_max', 0):,.2f}</td></tr>
                <tr><td>Worst Trade</td><td>${dist.get('pnl_min', 0):,.2f}</td></tr>
                <tr><td>Winning Trades</td><td>{dist.get('positive_trades', 0)}</td></tr>
                <tr><td>Losing Trades</td><td>{dist.get('negative_trades', 0)}</td></tr>
            </table>
        </div>
""")
        
        # Regime performance
        if metrics.get("regime_performance"):
            html_parts.append("""
        <div class="card">
            <h2>Performance by Market Regime</h2>
            <table>
                <tr><th>Regime</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>Total PnL</th><th>Avg PnL</th></tr>
""")
            for regime, perf in metrics["regime_performance"].items():
                html_parts.append(f"""
                <tr>
                    <td>{regime}</td>
                    <td>{perf.get('trades', 0)}</td>
                    <td>{perf.get('wins', 0)}</td>
                    <td>{perf.get('win_rate_pct', 0):.1f}%</td>
                    <td class="{'positive' if perf.get('total_pnl', 0) >= 0 else 'negative'}">
                        ${perf.get('total_pnl', 0):,.2f}
                    </td>
                    <td class="{'positive' if perf.get('avg_pnl', 0) >= 0 else 'negative'}">
                        ${perf.get('avg_pnl', 0):,.2f}
                    </td>
                </tr>
""")
            html_parts.append("</table></div>")
        
        # Best/Worst trades
        if metrics.get("best_trade") or metrics.get("worst_trade"):
            html_parts.append("""
        <div class="card">
            <h2>Best & Worst Trades</h2>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
""")
            if metrics.get("best_trade"):
                bt = metrics["best_trade"]
                html_parts.append(f"""
                <div>
                    <h3>Best Trade</h3>
                    <table>
                        <tr><td>Ticker</td><td>{bt.get('Ticker', 'N/A')}</td></tr>
                        <tr><td>PnL</td><td class="positive">${bt.get('PnL', 0):,.2f}</td></tr>
                        <tr><td>Return</td><td class="positive">{bt.get('PnL_Pct', 0)*100:.2f}%</td></tr>
                        <tr><td>Reason</td><td>{bt.get('Reason', 'N/A')}</td></tr>
                    </table>
                </div>
""")
            if metrics.get("worst_trade"):
                wt = metrics["worst_trade"]
                html_parts.append(f"""
                <div>
                    <h3>Worst Trade</h3>
                    <table>
                        <tr><td>Ticker</td><td>{wt.get('Ticker', 'N/A')}</td></tr>
                        <tr><td>PnL</td><td class="negative">${wt.get('PnL', 0):,.2f}</td></tr>
                        <tr><td>Return</td><td class="negative">{wt.get('PnL_Pct', 0)*100:.2f}%</td></tr>
                        <tr><td>Reason</td><td>{wt.get('Reason', 'N/A')}</td></tr>
                    </table>
                </div>
""")
            html_parts.append("</div></div>")
        
        # Footer
        html_parts.append(f"""
        <div class="card">
            <p style="color: #aaa; text-align: center;">
                Report generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </p>
        </div>
    </div>
</body>
</html>
""")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(''.join(html_parts))
        
        print(f"  HTML report saved: {output_path}")
    
    def generate_json_report(self, metrics: dict, test_config: dict, output_path: Path):
        """Generate JSON report with all metrics."""
        report = {
            "test_config": test_config,
            "metrics": metrics,
            "generated_at": datetime.now().isoformat(),
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"  JSON report saved: {output_path}")
    
    def generate_csv_reports(self, metrics: dict, output_dir: Path):
        """Generate CSV reports for trades and equity curve."""
        # Trades CSV
        if metrics.get("trades"):
            trades_path = output_dir / "trades.csv"
            trades_df = pd.DataFrame(metrics["trades"])
            trades_df.to_csv(trades_path, index=False)
            print(f"  Trades CSV saved: {trades_path}")
        
        # Equity curve CSV
        if metrics.get("equity_curve"):
            equity_path = output_dir / "equity_curve.csv"
            equity_df = pd.DataFrame(metrics["equity_curve"], columns=["timestamp", "equity"])
            equity_df.to_csv(equity_path, index=False)
            print(f"  Equity curve CSV saved: {equity_path}")
        
        # Summary CSV
        summary_path = output_dir / "summary.csv"
        summary_data = {
            "Metric": [
                "Initial Capital", "Final Equity", "Total Return %", "Net Return %",
                "Total Trades", "Win Rate %", "Max Drawdown %", "Sharpe Ratio",
                "Total Fees", "Fee Drag %", "Avg Hold Time (hours)"
            ],
            "Value": [
                metrics.get("initial_capital", 0),
                metrics.get("final_equity", 0),
                metrics.get("total_return_pct", 0),
                metrics.get("net_return_pct", 0),
                metrics.get("total_trades", 0),
                metrics.get("win_rate_pct", 0),
                metrics.get("max_drawdown_pct", 0),
                metrics.get("sharpe_ratio", "N/A"),
                metrics.get("total_fees", 0),
                metrics.get("fee_drag_pct", 0),
                metrics.get("avg_hold_time_hours", "N/A"),
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_csv(summary_path, index=False)
        print(f"  Summary CSV saved: {summary_path}")
