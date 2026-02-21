# Operations Runbook

## Start Trading Loop

```bash
python live_trader.py --profile balanced --loop
```

## Start Control API

```bash
python live_trader.py --control-api
```

## Pause New Entries

```http
POST /controls
{
  "pause_buys": true,
  "notes": "Pause for event risk"
}
```

## Emergency Flatten

```http
POST /controls
{
  "emergency_flatten": true
}
```

## Enable Manual Approval Mode

```http
POST /controls
{
  "approval_mode": "manual"
}
```

Then inspect approvals:

```http
GET /approvals
```

Approve one:

```http
POST /approvals/decision
{
  "id": "APPROVAL_ID",
  "decision": "approve",
  "note": "approved by operator"
}
```

## Logs

- decision logs: `logs/decisions/*.jsonl`
- alert logs: `logs/alerts/alerts.jsonl`
