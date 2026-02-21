# Explainability and Decision Audit (Sprint 3)

Decision events are now logged in structured form for audit and debugging.

Log path:

- `logs/decisions/<YYYY-MM-DD>.jsonl`

## Event Types

- `scan_skipped`
- `candidate_skipped`
- `candidate_blocked`
- `buy_executed`
- `entries_skipped`
- `exits_skipped`
- `cycle_skipped`
- `emergency_flatten_triggered`
- `emergency_flatten_sell`

## Record Shape

```json
{
  "ts": "2026-02-21T14:32:10.123456",
  "event": "candidate_skipped",
  "ticker": "AAPL",
  "reason": "earnings_gate",
  "context": {"days_to_earnings": 2}
}
```

## Why This Matters

- Trace exactly why trades were taken or skipped
- Debug strategy drift after config changes
- Build "why-not" reports from raw logs
