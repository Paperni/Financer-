# Financer Architecture

This document gives a visual overview of system components and execution paths.

## Financer Brain — Target Architecture

The platform is being refactored into a layered "Brain" with two engines,
a CIO Orchestrator, and a Risk Governor. Engines emit intents, not orders.

```mermaid
flowchart TD
    subgraph data [Data Layer]
        yfinance[yfinance / SEC EDGAR]
        cache[DataCache]
        news[News Engine]
    end

    subgraph features [Feature Store]
        technical_f[Technical Indicators]
        fundamental_f[Fundamental Scores]
        sentiment_f[Sentiment Signals]
    end

    subgraph engines [Engines — emit intents only]
        lt[Long-Term Investor Engine]
        sw[Swing Trader Engine]
    end

    subgraph cio [CIO Orchestrator — creates orders]
        merge[Intent Merger]
        sizing[Position Sizing]
        plan[ActionPlan]
    end

    subgraph risk [Risk Governor — can veto]
        checks[Risk Checks]
        veto[Approve / Veto]
    end

    subgraph exec [Execution]
        paper[Paper Trading]
        live[Live Execution]
    end

    subgraph logs [Replay and Logs]
        replay[Historical Replay]
        decisions[Decision Logger]
    end

    data --> features
    features --> engines
    engines -->|TradeIntent / AllocationIntent| cio
    cio -->|Order / ActionPlan| risk
    risk -->|Approved Orders| exec
    exec --> logs
    cio --> logs
```

### Core schemas (`financer/models/`)

| Model | Module | Purpose |
|-------|--------|---------|
| `TradeIntent` | `intents.py` | Engine recommendation (ticker, direction, conviction, reasons) |

### Intelligence schemas (`financer/intelligence/`)

| Model | Module | Purpose |
|-------|--------|---------|
| `ControlPlan` | `models.py` | Top-level object containing environmental state and resulting policy constraints. |
| `MarketState` | `models.py` | Nested sub-model tracking Regime and NLP scores. |
| `PolicyOverrides` | `models.py` | Nested sub-model dictating Execution boundaries (e.g. `max_positions`). |

**Intelligence Rules (Non-negotiable)**
- **Controls Risk, Not Alpha:** The intelligence layer may throttle capital deployed (via scaling or lowering positions to 0), but does not execute new isolated positions.
- **Data Only:** `ControlPlan` is read-only. It mutates absolutely nothing.
- **Placeholder Nullification:** Future intelligence variables (e.g., NLP Event Risk, Sentiment Scoring) must remain strictly `Optional[None]` typed until actively wired into the orchestrator. Downstream interfaces must safely parse empty values.
| `AllocationIntent` | `intents.py` | Engine desired portfolio split |
| `ReasonCode` | `intents.py` | Explainable reason attached to any intent |
| `Order` | `actions.py` | Concrete sized order (CIO output) |
| `ActionPlan` | `actions.py` | Batch of orders + allocation shifts |
| `PositionState` | `portfolio.py` | Single position with P&L properties |
| `PortfolioSnapshot` | `portfolio.py` | Full portfolio view (cash + positions) |
| `RiskState` | `risk.py` | Current risk metrics (regime, drawdown, sector counts) |
| `RiskVeto` | `risk.py` | Risk Governor decision on an order |
| `EventFlags` | `events.py` | Cross-engine coordination flags |
| `position_size()` | `sizing.py` | Pure function: ATR-based qty/stop/TP calculation |

### Import boundaries (non-negotiable)

- **`financer/` never imports root-level scripts. Enforced by `tests/test_import_boundary.py`.**
- `financer/models/` imports nothing outside itself
- `financer/data/` will not import `financer/engines/`
- `financer/engines/` will not import `financer/execution/`
- Only `financer/orchestrator/` creates `Order` and `ActionPlan` objects

## High-Level Components

```mermaid
flowchart LR
    subgraph analysis [Fundamental Analysis]
        downloader[downloader.py]
        analyzer[analyzer.py]
        technical[technical.py]
        filings[reports/sec-edgar-filings]
        htmlReports[reports/*_analysis.html]
        downloader --> filings
        analyzer --> filings
        analyzer --> technical
        analyzer --> htmlReports
    end

    subgraph trading [Live Trading]
        liveTrader[live_trader.py]
        indicators[indicators.py]
        portfolio[portfolio.py]
        runtimeFiles[wallet.json and equity_curve.json]
        dashboard[docs/dashboards/dashboard.html]
        liveTrader --> indicators
        liveTrader --> portfolio
        liveTrader --> runtimeFiles
        liveTrader --> dashboard
    end

    subgraph replay [Historical Replay]
        tester[historical_tester/tester.py]
        timeSimulator[historical_tester/time_simulator.py]
        historicalCache[historical_tester/historical_cache.py]
        metricsCollector[historical_tester/metrics.py]
        reportGenerator[historical_tester/report_generator.py]
        testResults[test_results/*]
        tester --> timeSimulator
        tester --> historicalCache
        tester --> metricsCollector
        tester --> reportGenerator
        reportGenerator --> testResults
    end
```

## Live Trading Cycle

```mermaid
flowchart TD
    startCycle[run_live_cycle] --> refreshCache[Refresh DataCache]
    refreshCache --> regimeCheck[Get Market Regime]
    regimeCheck --> updateHoldings[Update Holdings and Exits]
    updateHoldings --> checkPyramids[Check Pyramid Adds]
    checkPyramids --> recordEquity[Append Equity and Save Wallet]
    recordEquity --> scanBuy[Scan and Buy Candidates]
    scanBuy --> baselineOps[Free or Deploy Baseline QQQ]
    baselineOps --> dashboardUpdate[Update Dashboard]
```

## Historical Replay Cycle

```mermaid
flowchart TD
    initReplay[HistoricalTester Init] --> loadHistoricalData[Download Rolling Historical Windows]
    loadHistoricalData --> setSimTime[Set Simulated Time]
    setSimTime --> sliceCache[Slice Data to Current Sim Time]
    sliceCache --> runCycle[Run Trading Cycle Replica]
    runCycle --> collectMetrics[Collect Trades and Equity Metrics]
    collectMetrics --> advanceTime[Advance to Next Market Hour]
    advanceTime --> doneCheck{Reached End Date}
    doneCheck -->|No| setSimTime
    doneCheck -->|Yes| exportReports[Export HTML JSON CSV Reports]
```
