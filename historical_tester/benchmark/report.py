from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .compare import build_benchmark_payload


def write_benchmark_report(
    engine_results: list[dict[str, Any]],
    output_dir: str = "test_results/benchmarks",
    validate_result: dict[str, Any] | None = None,
) -> dict[str, str]:
    payload = build_benchmark_payload(engine_results)
    if validate_result is not None:
        payload["validation"] = validate_result

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"benchmark_{stamp}.json"
    csv_path = out_dir / f"benchmark_{stamp}.csv"
    html_path = out_dir / f"benchmark_{stamp}.html"

    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    rows = payload.get("records", [])
    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    html_lines = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>Benchmark Report</title>",
        "<style>body{font-family:Segoe UI,sans-serif;padding:20px;background:#111;color:#eee}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #333;padding:8px}"
        "th{background:#1d1d1d}</style></head><body>",
        "<h1>Standardized Benchmark Report</h1>",
        f"<p>Generated: {datetime.now().isoformat()}</p>",
        "<table><tr><th>Engine</th><th>Return %</th><th>Win Rate %</th><th>Max DD %</th>"
        "<th>Sharpe</th><th>Trades</th><th>Fee Drag %</th><th>Avg Hold (h)</th></tr>",
    ]
    for row in rows:
        sharpe = "N/A" if row["sharpe_ratio"] is None else f"{row['sharpe_ratio']:.3f}"
        avg_hold = "N/A" if row["avg_hold_time_hours"] is None else f"{row['avg_hold_time_hours']:.2f}"
        html_lines.append(
            "<tr>"
            f"<td>{row['engine']}</td>"
            f"<td>{row['total_return_pct']:.2f}</td>"
            f"<td>{row['win_rate_pct']:.2f}</td>"
            f"<td>{row['max_drawdown_pct']:.2f}</td>"
            f"<td>{sharpe}</td>"
            f"<td>{row['total_trades']}</td>"
            f"<td>{row['fee_drag_pct']:.2f}</td>"
            f"<td>{avg_hold}</td>"
            "</tr>"
        )
    html_lines.append("</table>")
    if validate_result is not None:
        html_lines.append("<h2>Validation</h2>")
        html_lines.append(f"<pre>{json.dumps(validate_result, indent=2, default=str)}</pre>")
    html_lines.append("</body></html>")
    html_path.write_text("\n".join(html_lines), encoding="utf-8")

    return {"json": str(json_path), "csv": str(csv_path), "html": str(html_path)}

