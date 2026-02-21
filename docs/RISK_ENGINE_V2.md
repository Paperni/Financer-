# Risk Engine v2

Risk Engine v2 adds portfolio-level controls before opening new positions.

## Current Gates

- Daily realized-loss halt
- Open-risk budget cap (sum of entry-to-stop risk across open positions)
- Sector concentration cap
- Estimated new-position risk cap

## Integration Points

- `live_trader.py`
  - `scan_and_buy()` checks portfolio gate before scanning entries
  - per-candidate entry gate checked before earnings/news/final buy call
- Config-driven values from `configs/*`

## Decision Flow

```mermaid
flowchart TD
    start[New cycle] --> portfolioGate[can_open_new_positions]
    portfolioGate -->|blocked| stopNoBuy[No new buys]
    portfolioGate -->|ok| candidateLoop[For each candidate]
    candidateLoop --> entryGate[can_take_entry]
    entryGate -->|blocked| nextCandidate[Skip candidate]
    entryGate -->|ok| strategyChecks[Score + earnings + news]
    strategyChecks --> executeBuy[execute_buy]
```
