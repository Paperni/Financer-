import pandas as pd
from pathlib import Path
from financer.engines.swing.engine import SwingEngine
from datetime import datetime

features_dir = Path("data/cache/features")

print("Loading cached features for engine testing...")
files = list(features_dir.glob("*.parquet"))

# Load all data into a daily structure
daily_features = {}
for f in files[:200]: # load a bunch
    ticker = f.name.split("_")[0]
    df = pd.read_parquet(f)
    if "above_50" not in df.columns: continue
    
    ticker_dict = df.to_dict('index')
    for d, row_dict in ticker_dict.items():
        if pd.isna(d): continue
        ts = pd.to_datetime(d).normalize()
        if ts not in daily_features:
            daily_features[ts] = {}
        daily_features[ts][ticker] = row_dict

print(f"Loaded {len(daily_features)} days of features.")

engine = SwingEngine(
    min_entry_score=5.0,
    max_draft=10,
    stop_loss_atr_mult=1.5,
    tp_atr_mult=4.0
)

total_intents = 0
for day in sorted(daily_features.keys()):
    intents = engine.evaluate(daily_features[day])
    total_intents += len(intents)
    if intents:
        print(f"{day.date()}: Found {len(intents)} intents.")

print(f"Total Intents emitted over 5 years: {total_intents}")
from financer.core.orchestrator import CIOOrchestrator
from financer.execution.broker_sim import SimBroker
from financer.models.portfolio import PortfolioSnapshot
from financer.models.risk import RiskState
from financer.models.enums import Regime

orchestrator = CIOOrchestrator()
broker = SimBroker()
portfolio = PortfolioSnapshot(cash=100000.0, positions=[])
risk_state = RiskState(regime=Regime.RISK_ON, open_risk_pct=0.0)

trades = 0
vetos = 0
for day in sorted(daily_features.keys()):
    intents = engine.evaluate(daily_features[day])
    if intents:
        # Need to patch meta for price like run_replay does
        for intent in intents:
            if "latest_price" not in intent.meta:
                try:
                    p = float(daily_features[day][intent.ticker].get("Close", 100))
                    a = float(daily_features[day][intent.ticker].get("atr_14", 1.0))
                    intent.meta["latest_price"] = p
                    intent.meta["atr_14"] = a
                except Exception:
                    pass
        plan = orchestrator.formulate_plan(intents, [], portfolio, risk_state)
        vetos += len(plan.vetoed_intents)
        for order in plan.orders:
            if order.status.value == "VETOED":
                vetos += 1
                
        portfolio = broker.execute_plan(plan, portfolio)
        
print(f"Final Pos: {len(portfolio.positions)}")
print(f"Total Vetos: {vetos}")
