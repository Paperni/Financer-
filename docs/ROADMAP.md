# Financer Roadmap

This roadmap tracks the rebuilding of the Financer algorithmic trading brain into a robust, decoupled, domain-driven system.

### ✅ Completed Slices
- **Slice 1: Scaffolding & CI Pipeline**
  - Pytest setup, strictly enforced import boundaries, pre-commit scripts, and validation shells.
- **Slice 2: Domain Models & Global Primitives**
  - Pydantic schemas for `Order`, `ActionPlan`, `TradeIntent`, `PortfolioSnapshot`, `RiskState`.
- **Slice 3: Modular Edge (SwingEngine)**
  - Decoupled `SwingEngine` creating `TradeIntents` purely based on technical features (TA-Lib).
- **Slice 4: Orchestrator & Execution Pipeline**
  - Implemented `CIOOrchestrator`, `RiskGovernor` (sizing logic), and the `Broker` interface stub.
- **Slice 5: Replay Parity & Hardening**
  - Built `PositionManager` to isolate exit tracking (Stop Loss, TP, Trailing). Migrated anti-pyramiding veto to the `RiskGovernor` intent level for clean determinism.
- **Slice 6: Live Loop Skeleton**
  - Base `run_live.py` daemon evaluating heartbeats, enforcing operational safety (`KILL_SWITCH`, Max DD constraints, Manual run modes), and snapshotting artifacts to JSON cleanly.

### 🚧 Current Post-Slice-6 Goal
- Status Review, Technical Debt documentation, and bounding box tests on AST dependencies to ensure the architectural purity of Slices 1-6 remains pristine before introducing network side-effects.

### 🔮 Future Slices
- **Slice 7: Network Integration & Cloud Broker Adapters**
- **Slice 8: Machine Learning Engine Ports (FinBERT / Regimes)**
- **Slice 9: Reporting & Live Dashboard Generation**
