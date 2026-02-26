# Slice 4 Validation: CIO Orchestrator & ActionPlan Loop

## 1. Orchestrator Monopoly on Orders
**✅ Confirm only orchestrator creates Order/ActionPlan**  
The `SwingEngine` strictly yields `TradeIntent` objects. The `CIOOrchestrator` is the sole component responsible for converting these intents into concrete `ActionPlan` and `Order` objects by applying `position_size()` rules over the portfolio equity.
*ActionPlan formulation:* `financer/core/orchestrator.py:28`
*Order instantiation:* `financer/core/orchestrator.py:61`

## 2. Risk Governor Veto Rules
The `RiskGovernor` evaluates incoming orders against the portfolio `RiskState` and applies the following implemented rules:
1. **Guaranteed Exits:** Any order with `Direction.SELL` bypasses risk limits and is automatically `APPROVED`. (`financer/core/governor.py:23`)
2. **Global Halts:** If `RiskState.halt_active` is true, *all new entries* receive a `VETOED` status. (`financer/core/governor.py:31`)
3. **Open Risk Limit:** The governor enforces a `max_open_risk_pct` (default 20%). If `state.open_risk_pct` meets or exceeds this limit, the order is `VETOED` with the exact math attached to the failure reason. (`financer/core/governor.py:42`)

## 3. SimBroker Execution Logic
**Fill Logic:** The `SimBroker` accepts an `ActionPlan` and loops through its `orders`. It only attempts execution if `order.status == OrderStatus.APPROVED`. 
* **Buy:** Verifies sufficient `portfolio.cash >= (qty * price)`. If true, mutates the cash balance, appends the new `PositionState` to the portfolio, and marks the order `FILLED`. If false, retroactively flips the order to `VETOED` via "Insufficient cash". (`financer/execution/broker_sim.py:28`)
* **Sell:** Looks for a matching position ticker. If found, liquidates it fully at the order limit price, credits cash, removes the position, and marks order `FILLED`. (`financer/execution/broker_sim.py:48`)

**Slippage & Fees Handling:** Currently, execution is a purely stubbed, zero-friction fill. Orders are filled exactly at `order.price` without volume delays, slippage models, or broker commissions. *(Note: While `sizing.py` knows about `SLIPPAGE_PCT=0.0005`, the `SimBroker` does not enforce it yet).*

## 4. Approval & Veto Tracking
Vetoes and approvals are currently tracked deterministically in two ways rather than streaming to disk logs:
1. **The `RiskVeto` struct:** Returned alongside the mutated order by the Governor, containing explicit lists of `checks_passed` and `checks_failed`. (`financer/core/governor.py:49`)
2. **Order Object Mutation:** The `Order.status` state changes sequentially: `PROPOSED` -> `APPROVED/VETOED` (in Governor) -> `FILLED` (in Broker). The Broker relies on this state tracking.
3. Post-execution, the `ActionPlan.orders` list effectively serves as the persistent audit log of exactly what was passed, blocked, or filled for a given timestep.
