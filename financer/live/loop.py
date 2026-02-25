import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from financer.core.governor import RiskGovernor
from financer.core.orchestrator import CIOOrchestrator
from financer.engines.swing.engine import SwingEngine
from financer.execution.broker_sim import SimBroker
from financer.execution.position_manager import PositionManager
from financer.features.build import build_features
from financer.live.config import ExecutionMode, LiveConfig
from financer.models.actions import ActionPlan, Order
from financer.models.enums import Direction, OrderStatus
from financer.models.portfolio import PortfolioSnapshot
from financer.models.risk import RiskState

logger = logging.getLogger(__name__)


def setup_artifact_dirs(config: LiveConfig) -> Path:
    """Ensure artifact directories exist for this run."""
    run_dir = Path(config.artifact_root) / config.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "approvals").mkdir(exist_ok=True)
    
    # Save active config
    with open(run_dir / "config.json", "w") as f:
        f.write(config.model_dump_json(indent=2))
        
    return run_dir


def check_manual_approval(plan: ActionPlan, approvals_dir: Path, run_id: str) -> ActionPlan:
    """In MANUAL mode, filter orders based on an approval JSON file."""
    approval_file = approvals_dir / f"APPROVE_{run_id}.json"
    
    if not approval_file.exists():
        for order in plan.orders:
            order.status = OrderStatus.VETOED
            order.meta["veto_reason"] = "manual_approval_missing"
        return plan

    try:
        with open(approval_file, "r") as f:
            data = json.load(f)
            approved_ids = set(data.get("approved_order_ids", []))
            
        for order in plan.orders:
            if order.order_id not in approved_ids:
                order.status = OrderStatus.VETOED
                order.meta["veto_reason"] = "manual_approval_denied"
    except Exception as e:
        logger.error(f"Error reading approval file: {e}")
        for order in plan.orders:
            order.status = OrderStatus.VETOED
            order.meta["veto_reason"] = f"manual_approval_error: {e}"

    return plan


def run_live_once(
    config: LiveConfig,
    portfolio: PortfolioSnapshot,
    risk_state: RiskState,
    engine: SwingEngine,
    orchestrator: CIOOrchestrator,
    pos_manager: PositionManager,
    broker: SimBroker,
    run_dir: Path
) -> PortfolioSnapshot:
    """Executes a single fully-integrated cycle of the algorithmic brain."""
    now = datetime.now(timezone.utc)
    cwd = Path.cwd()
    
    # 1. Fetch Latest State
    try:
        latest_features = {}
        for ticker in config.universe:
            # Note: A real live implementation fetch 1 day/bar backwards from today
            # We mock this tightly to the end of the history
            df = build_features(ticker, "2000-01-01", now.strftime("%Y-%m-%d"))
            if not df.empty:
                latest_features[ticker] = df.iloc[-1]
    except Exception as e:
        logger.error(f"Failed to build features: {e}")
        return portfolio

    # Mark to Market
    for pos in portfolio.positions:
        if pos.ticker in latest_features:
            pos.current_price = float(latest_features[pos.ticker].get("Close", pos.current_price))

    # Calculate Current Daily Drawdown
    current_equity = portfolio.equity
    # Assuming initial_capital acts as High Water Mark for daily DD
    dd_today_pct = 0.0
    if portfolio.initial_capital > 0:
        dd_today_pct = (current_equity - portfolio.initial_capital) / portfolio.initial_capital

    # 2. Evaluate Intents
    trade_intents = engine.evaluate(latest_features)
    exit_intents, trail_updates = pos_manager.evaluate_exits(portfolio, latest_features, now)
    
    for pos in portfolio.positions:
        if pos.ticker in trail_updates:
            pos.stop_loss = trail_updates[pos.ticker]

    # 3. Apply Safety Vetoes & Constraints
    kill_switch_active = (cwd / "KILL_SWITCH").exists()
    flatten_active = (cwd / "FLATTEN_NOW").exists()
    max_dd_hit = dd_today_pct <= -config.max_daily_dd_pct

    filtered_trade_intents = []
    
    if flatten_active:
        # Generate raw sells for everything, ignore entries completely
        logger.warning("FLATTEN_NOW detected. Liquidating portfolio.")
        flatten_intents = [
            pos_manager._create_exit_intent(p, p.current_price, "FLATTEN_NOW")
            for p in portfolio.positions
        ]
        all_intents = flatten_intents
    elif kill_switch_active or max_dd_hit:
        # Only allow exits
        if kill_switch_active: logger.warning("KILL_SWITCH active. Vetoing new entries.")
        if max_dd_hit: logger.warning(f"MAX DD HIT ({dd_today_pct:.2%}). Vetoing new entries.")
        all_intents = exit_intents
    else:
        # Normal operation
        all_intents = trade_intents + exit_intents

    # 4. Formulate Action Plan
    if all_intents:
        plan = orchestrator.formulate_plan(all_intents, [], portfolio, risk_state)
    else:
        plan = ActionPlan()

    # 5. Apply Execution Mode Filters
    if config.mode == ExecutionMode.DRY_RUN:
        for order in plan.orders:
            order.status = OrderStatus.VETOED
            order.meta["veto_reason"] = "dry_run"
    elif config.mode == ExecutionMode.MANUAL:
        plan = check_manual_approval(plan, run_dir / "approvals", config.run_id)

    # 6. Execute Validated Plan
    if plan.orders:
        portfolio = broker.execute_plan(plan, portfolio)
        
    # Set high water mark roughly per cycle if equity grew
    portfolio.initial_capital = max(portfolio.initial_capital, portfolio.equity)

    # 7. Write Cycle Artifacts
    _write_artifacts(config, run_dir, now, plan, portfolio, latest_features)
    
    return portfolio


def _write_artifacts(
    config: LiveConfig, run_dir: Path, now: datetime, 
    plan: ActionPlan, portfolio: PortfolioSnapshot, features: dict
):
    """Serialize the exact state of the loop to disk cleanly."""
    cycle_id = now.isoformat()
    
    # Write Lifecycle (trade log equivalent)
    lifecycle_entry = {
        "timestamp": cycle_id,
        "candidate_intents": [
            {
                "ticker": intent.ticker, 
                "direction": intent.direction.value, 
                "conviction": intent.conviction.value
            }
            for intent in plan.vetoed_intents  # For now just use vetoed + orders
            # A real db should pass all_intents down, but orchestrator currently consumes them
        ],
        "vetoed_intents": [
            {"ticker": v.ticker, "direction": v.direction.value, "reason": v.meta.get("veto_reason", "")}
            for v in plan.vetoed_intents
        ],
        "created_orders": [
            {
                "id": o.order_id, "ticker": o.ticker, "direction": o.direction.value, 
                "qty": o.qty, "price": o.price, "status": o.status.value,
                "veto_reason": o.meta.get("veto_reason", "")
            }
            for o in plan.orders
        ],
        "filled_orders": [
            {"id": o.order_id, "ticker": o.ticker, "direction": o.direction.value, "qty": o.qty, "price": o.price}
            for o in plan.orders if o.status == OrderStatus.FILLED
        ]
    }
    
    with open(run_dir / "lifecycle.jsonl", "a") as f:
        f.write(json.dumps(lifecycle_entry) + "\n")

    # Write heartbeat
    heartbeat = {
        "timestamp": cycle_id,
        "equity": portfolio.equity,
        "positions": len(portfolio.positions),
        "status": "OK"
    }
    with open(run_dir / "cycle_logs.jsonl", "a") as f:
        f.write(json.dumps(heartbeat) + "\n")
        
    # Write snapshot state (Overwrite)
    with open(run_dir / "positions.json", "w") as f:
        pos_list = [p.model_dump(mode="json") for p in portfolio.positions]
        f.write(json.dumps(pos_list, indent=2))
        
    with open(run_dir / "equity_curve.json", "w") as f:
        # In a real app we'd append or load->append->write
        pass


def run_live_loop(config: LiveConfig):
    """Indefinitely runs the live evaluation loop."""
    logger.info(f"Starting Financer Live Loop: {config.run_id} ({config.mode.value})")
    
    run_dir = setup_artifact_dirs(config)
    
    portfolio = PortfolioSnapshot(cash=100000.0, positions=[])
    risk_state = RiskState()
    
    engine = SwingEngine()
    orchestrator = CIOOrchestrator()
    pos_manager = PositionManager()
    broker = SimBroker()
    
    while True:
        try:
            portfolio = run_live_once(
                config, portfolio, risk_state, engine, orchestrator, pos_manager, broker, run_dir
            )
            
            if (Path.cwd() / "FLATTEN_NOW").exists():
                logger.info("FLATTEN_NOW generated. Exiting loop.")
                break
                
        except Exception as e:
            logger.error(f"Critical error in execution loop: {e}", exc_info=True)
            
        time.sleep(config.loop_interval_seconds)
