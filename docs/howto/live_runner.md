# How to Run the Financer Live Loop

The Live Loop skeleton executes iteratively at a configured interval to synthesize the current portfolio, features, and Mark-to-Market equity against your execution modes and intents limit requirements.

## Loop Architecture
1. **State Synthesis**: Determines the current portfolio, features, and Mark-to-Market equity.
2. **Intent Evaluation**: Evaluates all models and execution constraints natively.
3. **Safety Vetoes**: Checks file-based kill-switches and memory-based drawdown limits.
4. **Orchestrator Translation**: Generates ActionPlans of Orders.
5. **Mode Filter**: Vetoes execution depending on whether it is `dry_run`, `manual`, or `auto`.
6. **Execution**: Pushes valid orders to the Broker interface.
7. **Artifact Heartbeat**: Streams logs, JSONs, and lifecycle states to disk safely.

## Safety Controls
| Control | Trigger | Behavior |
| :--- | :--- | :--- |
| **Kill Switch** | `touch KILL_SWITCH` | Instantly blocks all entry intents from forming orders. Exits still run. |
| **Flatten Now** | `touch FLATTEN_NOW` | SELL logic overrides everything, flattens 100% of positions, script exits. |
| **Max Drawdown** | Equity vs high-water | Vetoes entries if DD limit breached. |
| **Manual Approval** | `mode="manual"` | Requires `APPROVE_<run_id>.json` containing `approved_order_ids` list matching the orchestrator intent IDs precisely. |

## Artifact Output Structure
Artifacts land in `/artifacts/live/<RUN_ID>/`:
- `config.json`
- `cycle_logs.jsonl`
- `lifecycle.jsonl`
- `positions.json`
- `equity_curve.json`

## CLI Usage
Run the default dry-run mode matching the conservative risk profile configuration:
```bash
python -m financer.cli.run_live --profile conservative --mode dry_run
```
For manual deployment validation over your simulated live stream, use:
```bash
python -m financer.cli.run_live --profile balanced --mode manual
```
