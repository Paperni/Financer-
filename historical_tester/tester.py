"""
Historical Trading Tester

Main tester class that orchestrates historical simulation using live trading logic.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import zoneinfo
from tqdm import tqdm

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import portfolio as pf
from data_static import BROAD_STOCKS, BROAD_ETFS
from indicators import check_buy_signal_detailed, check_volume_contraction
from core.strategy.config_loader import load_runtime_config
from core.execution.execution_engine import ExecutionEngine

# Handle both module and script execution
try:
    from .time_simulator import TimeSimulator
    from .historical_cache import HistoricalDataCache
    from .metrics import MetricsCollector
    from .report_generator import ReportGenerator
    from .run_registry import RunRegistry
except ImportError:
    # Running as script
    from time_simulator import TimeSimulator
    from historical_cache import HistoricalDataCache
    from metrics import MetricsCollector
    from report_generator import ReportGenerator
    from run_registry import RunRegistry


class HistoricalTester:
    """Historical trading tester that replays live trading logic on historical data."""
    
    def __init__(self, start_date: datetime, end_date: datetime,
                 initial_capital: float | None = None,
                 wallet_path: str = "test_wallet.json",
                 speed_multiplier: float | None = None,
                 enable_news: bool | None = None,
                 enable_earnings: bool | None = None,
                 engine: str = "native",
                 config_path: str | None = None,
                 profile: str | None = None,
                 overrides: list[str] | None = None):
        """
        Initialize historical tester.
        
        Args:
            start_date: Start date for historical simulation
            end_date: End date for historical simulation
            initial_capital: Initial capital for testing
            wallet_path: Path to test wallet file
            speed_multiplier: Speed multiplier for simulation
            enable_news: Enable news sentiment (None = use config)
            enable_earnings: Enable earnings calendar (None = use config)
        """
        self.runtime_cfg = load_runtime_config(
            config_path=config_path,
            profile=profile,
            overrides=overrides or [],
        )
        self.config_path = config_path
        self.profile = profile
        self.engine = engine

        self.start_date = start_date
        self.end_date = end_date
        cfg_capital = float(self.runtime_cfg.get("capital", {}).get("initial_capital", 100000.0))
        self.initial_capital = initial_capital if initial_capital is not None else cfg_capital
        self.wallet_path = wallet_path
        self.speed_multiplier = speed_multiplier if speed_multiplier is not None else 10.0
        cfg_features = self.runtime_cfg.get("features", {})
        self.enable_news = enable_news if enable_news is not None else bool(cfg_features.get("news_enabled", False))
        self.enable_earnings = (
            enable_earnings if enable_earnings is not None else bool(cfg_features.get("earnings_enabled", False))
        )
        
        # Initialize components
        self.time_sim = TimeSimulator(start_date, speed_multiplier)
        self.data_cache = HistoricalDataCache(
            start_date,
            enable_news=self.enable_news,
            enable_earnings=self.enable_earnings
        )
        self.metrics = MetricsCollector(self.initial_capital)
        self.report_gen = ReportGenerator()
        self.run_registry = RunRegistry()
        self.execution_engine = ExecutionEngine(self.runtime_cfg.get("execution", {}))
        
        # Override wallet file path
        pf.WALLET_FILE = wallet_path
        pf.EQUITY_FILE = wallet_path.replace(".json", "_equity.json")
        
        # All tickers
        self.all_tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
    
    def run(self):
        """Run the historical simulation."""
        print(f"\n{'='*60}")
        print(f"  HISTORICAL TRADING TEST")
        print(f"{'='*60}")
        print(f"  Period: {self.start_date.date()} to {self.end_date.date()}")
        print(f"  Initial Capital: ${self.initial_capital:,.0f}")
        print(f"  Speed: {self.speed_multiplier}x")
        print(f"  News: {'Enabled' if self.enable_news else 'Disabled'}")
        print(f"  Earnings: {'Enabled' if self.enable_earnings else 'Disabled'}")
        print(f"{'='*60}\n")
        
        run_meta = {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "profile": self.profile,
            "engine": self.engine,
            "config_path": self.config_path,
            "runtime_cfg": self.runtime_cfg,
        }
        run_id, run_dir = self.run_registry.create_run(run_meta)

        # Step 1: Download historical data
        print("  [1/4] Downloading historical data...")
        self.data_cache.download_historical_data(
            self.all_tickers,
            self.start_date,
            self.end_date,
            progress=True
        )
        
        # Step 2: Initialize wallet
        print(f"\n  [2/4] Initializing wallet...")
        wallet = pf.reset_wallet(self.initial_capital)
        pf.save_wallet(wallet)
        
        # Step 3: Run simulation
        print(f"\n  [3/4] Running simulation...")
        self._run_simulation(wallet)
        
        # Step 4: Generate reports
        print(f"\n  [4/4] Generating reports...")
        test_config = {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "initial_capital": self.initial_capital,
            "speed_multiplier": self.speed_multiplier,
            "enable_news": self.enable_news,
            "enable_earnings": self.enable_earnings,
            "profile": self.profile,
        }
        
        final_metrics = self.metrics.calculate_metrics(wallet)
        final_metrics["run_id"] = run_id
        report_paths = self.report_gen.generate_all_reports(final_metrics, test_config)
        self.run_registry.save_summary(run_dir, final_metrics)
        self.run_registry.append_leaderboard(
            {
                "run_id": run_id,
                "start_date": test_config["start_date"],
                "end_date": test_config["end_date"],
                "profile": test_config["profile"],
                "engine": self.engine,
                "total_return_pct": final_metrics.get("total_return_pct", 0),
                "win_rate_pct": final_metrics.get("win_rate_pct", 0),
                "max_drawdown_pct": final_metrics.get("max_drawdown_pct", 0),
                "total_trades": final_metrics.get("total_trades", 0),
            }
        )
        
        print(f"\n{'='*60}")
        print(f"  SIMULATION COMPLETE")
        print(f"{'='*60}")
        print(f"  Final Equity: ${final_metrics.get('final_equity', 0):,.2f}")
        print(f"  Total Return: {final_metrics.get('total_return_pct', 0):+.2f}%")
        print(f"  Total Trades: {final_metrics.get('total_trades', 0)}")
        print(f"  Win Rate: {final_metrics.get('win_rate_pct', 0):.1f}%")
        print(f"\n  Reports:")
        print(f"    HTML: {report_paths['html']}")
        print(f"    JSON: {report_paths['json']}")
        print(f"    CSV:  {report_paths['csv_dir']}")
        print(f"{'='*60}\n")
        return final_metrics
    
    def _run_simulation(self, wallet: dict):
        """Run the main simulation loop."""
        # Generate list of market hours to simulate
        market_hours = self._generate_market_hours()
        
        total_hours = len(market_hours)
        progress_bar = tqdm(total=total_hours, desc="Simulating", unit="hour")
        
        cycle_count = 0
        last_cycle_time = None
        
        for hour_time in market_hours:
            # Update simulation time
            self.time_sim.current_time = hour_time
            self.data_cache.update_time(hour_time)
            
            # Run trading cycle (similar to live_trader.run_live_cycle)
            with self.time_sim.mock_time_functions():
                # Only run cycle at market open hours (9:30 AM, 10:30 AM, etc.)
                if hour_time.hour >= 9 and hour_time.hour < 16:
                    if hour_time.minute == 30 or (hour_time.hour > 9 and hour_time.minute == 0):
                        # Run cycle
                        self._run_trading_cycle(wallet)
                        cycle_count += 1
                        last_cycle_time = hour_time
            
            progress_bar.update(1)
            progress_bar.set_postfix({
                'cycles': cycle_count,
                'equity': f"${pf.calc_equity(wallet):,.0f}",
                'positions': len([p for p in wallet['holdings'].values() if not p.get('is_baseline')])
            })
        
        progress_bar.close()
        
        # Close all positions at end
        print(f"\n  Closing all positions at end of simulation...")
        self._close_all_positions(wallet)
    
    def _generate_market_hours(self) -> list:
        """Generate list of market hours to simulate."""
        hours = []
        current = self.start_date
        
        # Round to next market hour
        if current.hour < 9 or (current.hour == 9 and current.minute < 30):
            current = current.replace(hour=9, minute=30, second=0, microsecond=0)
        elif current.hour >= 16:
            current = (current + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
            while current.weekday() >= 5:
                current += timedelta(days=1)
        
        while current <= self.end_date:
            # Skip weekends
            if current.weekday() < 5:
                # Market hours: 9:30 AM to 4:00 PM
                if current.hour >= 9 and current.hour < 16:
                    if current.hour == 9 and current.minute >= 30:
                        hours.append(current)
                    elif current.hour > 9:
                        hours.append(current)
            
            # Advance by 1 hour
            current += timedelta(hours=1)
            
            # If past market close, advance to next day
            if current.hour >= 16:
                current = (current + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
                while current.weekday() >= 5:
                    current += timedelta(days=1)
        
        return hours
    
    def _run_trading_cycle(self, wallet: dict):
        """Run a single trading cycle (similar to live_trader.run_live_cycle)."""
        # Check if market is open
        market_open, status = self.time_sim.is_market_open()
        if not market_open:
            return
        
        # Get market regime
        regime = self.data_cache.get_market_regime()
        
        # Update existing positions
        self._update_holdings(wallet)
        
        # Check pyramids
        self._check_pyramids(wallet)
        
        # Record equity
        equity = pf.calc_equity(wallet)
        self.metrics.record_equity(self.time_sim.now_str(), equity)
        pf.append_equity(equity)
        pf.save_wallet(wallet)
        
        # Deploy baseline if needed
        if wallet["cash"] > pf.BASELINE_CASH_RESERVE + 500:
            qqq_price = self.data_cache.get_latest_price(pf.BASELINE_TICKER)
            if qqq_price:
                pf.deploy_baseline(wallet, qqq_price)
        
        # Scan & Buy
        swing_count = pf.count_swing_positions(wallet)
        if swing_count < pf.MAX_POSITIONS and wallet["cash"] > 1000:
            # Free baseline cash if needed
            if wallet["cash"] < 5000 and pf.BASELINE_TICKER in wallet["holdings"]:
                qqq_price = self.data_cache.get_latest_price(pf.BASELINE_TICKER)
                if qqq_price:
                    pf.free_baseline(wallet, 15000, qqq_price)
            
            self._scan_and_buy(wallet, regime)
        
        pf.save_wallet(wallet)
    
    def _update_holdings(self, wallet: dict):
        """Update existing positions (similar to live_trader.update_holdings)."""
        holdings = wallet["holdings"]
        if not holdings:
            return
        
        swing_tickers = [t for t in holdings.keys() if not holdings[t].get("is_baseline")]
        all_tickers_to_price = list(holdings.keys())
        
        # Update prices from cache
        for ticker in all_tickers_to_price:
            price = self.data_cache.get_latest_price(ticker)
            if price and ticker in wallet["holdings"]:
                wallet["holdings"][ticker]["last_price"] = price
        
        # Check exits for swing positions
        for ticker in list(swing_tickers):
            try:
                pos = wallet["holdings"].get(ticker)
                if not pos:
                    continue
                
                price = pos.get("last_price", pos["entry_price"])
                
                # Pre-earnings safety
                if self.enable_earnings:
                    days_to_earn = self.data_cache.days_until_earnings(ticker)
                    if days_to_earn is not None and days_to_earn <= 2 and not pos.get("earnings_reduced"):
                        half_qty = pos["qty"] // 2
                        if half_qty > 0:
                            pnl = pf.execute_sell(wallet, ticker, price, half_qty,
                                                  f"Pre-earnings reduce ({days_to_earn}d)")
                            if ticker in wallet["holdings"]:
                                wallet["holdings"][ticker]["earnings_reduced"] = True
                            continue
                
                # Check exits
                result = pf.check_exits(wallet, ticker, price)
                if result:
                    reason, pnl = result
                    # Record trade in metrics
                    trade_record = {
                        "Ticker": ticker,
                        "Time": self.time_sim.now_str(),
                        "Action": "SELL",
                        "Price": price,
                        "Qty": pos.get("qty", 0),
                        "PnL": pnl,
                        "PnL_Pct": (price - pos["entry_price"]) / pos["entry_price"] if pos["entry_price"] > 0 else 0,
                        "Reason": reason,
                        "Regime": pos.get("regime", "UNKNOWN"),
                        "Entry_Time": pos.get("entry_time", ""),
                        "Entry_Price": pos.get("entry_price", 0),
                    }
                    # Try to extract sector and signals
                    signals = pos.get("signals", {})
                    if isinstance(signals, dict):
                        trade_record["Sector"] = signals.get("sector", "Unknown")
                        trade_record["Signals"] = signals
                        trade_record["Score"] = signals.get("score", "Unknown")
                    trade_record["Reasoning"] = pos.get("reasoning", "")
                    
                    self.metrics.record_trade(trade_record)
            except Exception as e:
                pass  # Continue on errors
    
    def _check_pyramids(self, wallet: dict):
        """Check for pyramid opportunities (similar to live_trader.check_pyramids)."""
        for ticker, pos in list(wallet["holdings"].items()):
            if not pos.get("pyramid_eligible") or pos.get("pyramided"):
                continue
            if pos.get("is_baseline"):
                continue
            
            # Re-score with fresh data
            row = self.data_cache.get_latest_row(ticker)
            if row is None:
                continue
            
            rs = self.data_cache.get_relative_strength(ticker)
            df = self.data_cache.get(ticker)
            vol_c = check_volume_contraction(df) if df is not None else False
            fundies = self.data_cache.get_fundamentals(ticker)
            dsma50 = self.data_cache.get_daily_sma50(ticker)
            _, score, reasons = check_buy_signal_detailed(row, rs, vol_c, fundies, daily_sma50=dsma50)
            
            if score >= 5:
                price = pos.get("last_price", pos["entry_price"])
                atr = self.data_cache.get_atr(ticker)
                pyramid_cost = pos["initial_qty"] * pos["entry_price"] * 0.5
                pyramid_qty = int(pyramid_cost / (price * (1 + pf.SLIPPAGE_PCT)))
                
                if pyramid_qty > 0 and wallet["cash"] > pyramid_qty * price * (1 + pf.SLIPPAGE_PCT):
                    fee = pyramid_qty * price * pf.SLIPPAGE_PCT
                    cost = pyramid_qty * price * (1 + pf.SLIPPAGE_PCT)
                    wallet["cash"] -= cost
                    wallet["total_fees"] = wallet.get("total_fees", 0) + fee
                    
                    old_cost = pos["qty"] * pos["entry_price"]
                    new_cost = pyramid_qty * price
                    total_qty = pos["qty"] + pyramid_qty
                    pos["entry_price"] = round((old_cost + new_cost) / total_qty, 4)
                    pos["qty"] = total_qty
                    pos["pyramided"] = True
                    
                    if atr:
                        pos["sl"] = round(price - pf.ATR_STOP_MULTIPLIER * atr, 2)
                        pos["tp2"] = round(price + pf.ATR_TP2_MULTIPLIER * atr, 2)
                        pos["tp3"] = round(price + pf.ATR_TP3_MULTIPLIER * atr, 2)
                    
                    wallet["history"].append({
                        "Ticker": ticker,
                        "Time": self.time_sim.now_str(),
                        "Action": "BUY",
                        "Price": price,
                        "Qty": pyramid_qty,
                        "PnL": 0,
                        "PnL_Pct": 0,
                        "Fee": round(fee, 2),
                        "Reason": f"Pyramid add (score {score}/8)",
                    })
    
    def _scan_and_buy(self, wallet: dict, regime: str):
        """Scan and buy (similar to live_trader.scan_and_buy)."""
        swing_count = pf.count_swing_positions(wallet)
        if swing_count >= pf.MAX_POSITIONS:
            return
        
        # Drawdown circuit breaker
        halted, dd_pct = pf.check_drawdown_halt(wallet)
        if halted:
            return
        
        # RISK_OFF gate
        if regime == "RISK_OFF":
            return
        
        # Phase 1: Technical screen
        pre_candidates = []
        for ticker in self.all_tickers:
            if ticker in wallet["holdings"]:
                continue
            
            row = self.data_cache.get_latest_row(ticker)
            if row is None:
                continue
            
            rs = self.data_cache.get_relative_strength(ticker)
            df = self.data_cache.get(ticker)
            vol_contracting = check_volume_contraction(df) if df is not None else False
            dsma50 = self.data_cache.get_daily_sma50(ticker)
            
            passed, score, reasons = check_buy_signal_detailed(row, rs, vol_contracting, daily_sma50=dsma50)
            if passed or score >= 4:
                atr = self.data_cache.get_atr(ticker)
                pre_candidates.append((ticker, score, reasons, row, atr, rs, vol_contracting, dsma50))
        
        # Phase 2: PEG enrichment
        candidates = []
        for ticker, score, reasons, row, atr, rs, vol_c, dsma50 in pre_candidates:
            fundies = self.data_cache.get_fundamentals(ticker)
            _, full_score, full_reasons = check_buy_signal_detailed(row, rs, vol_c, fundies, daily_sma50=dsma50)
            
            if full_score >= 5:
                candidates.append((ticker, full_score, full_reasons, row, atr, rs, fundies))
        
        # Sort by score
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        slots = pf.MAX_POSITIONS - pf.count_swing_positions(wallet)
        found = 0
        
        # Build sector count
        sector_count = {}
        for held_ticker, held_pos in wallet["holdings"].items():
            if held_pos.get("is_baseline"):
                continue
            held_fundies = self.data_cache.get_fundamentals(held_ticker)
            sec = held_fundies.get("sector", "Unknown") if held_fundies else "Unknown"
            sector_count[sec] = sector_count.get(sec, 0) + 1
        
        MAX_PER_SECTOR = 3
        
        for ticker, score, reasons, row, atr, rs, fundies in candidates:
            if found >= slots:
                break
            
            # Sector concentration check
            candidate_sector = fundies.get("sector", "Unknown") if fundies else "Unknown"
            if candidate_sector != "Unknown" and sector_count.get(candidate_sector, 0) >= MAX_PER_SECTOR:
                continue
            
            # Earnings calendar gate
            if self.enable_earnings:
                days_to_earn = self.data_cache.days_until_earnings(ticker)
                if days_to_earn is not None and days_to_earn <= 3:
                    continue
            
            # News sentiment gate
            news = self.data_cache.get_news_sentiment(ticker)
            if news["sentiment"] == "DANGER":
                continue
            score += news["adjustment"]
            if news["adjustment"] != 0:
                reasons["news"] = f"News: {news['sentiment']} ({news['adjustment']:+.1f})"
            if score < 5:
                continue
            
            close = float(row["Close"])
            can_open, open_reason = self.execution_engine.can_open_position(self.time_sim.current_time)
            if not can_open:
                continue
            fill = self.execution_engine.resolve_entry(row, close)
            if not fill.get("filled"):
                continue
            close = float(fill["price"])
            reason_str = " | ".join(reasons.values())
            
            signals = {
                "score": score,
                "rsi": round(float(row["RSI"]), 1),
                "sma50": round(float(row["SMA_50"]), 2),
                "close": round(close, 2),
                "atr": round(atr, 2) if atr else None,
                "relative_strength": round(rs, 2) if rs else None,
                "sector": candidate_sector,
                "news_sentiment": news["sentiment"],
                "news_adjustment": news["adjustment"],
                "days_to_earnings": days_to_earn if self.enable_earnings else None,
                "reasoning": f"[{score}/8 | {regime}] {reason_str}",
                "execution_mode": self.execution_engine.cfg.order_mode,
            }
            
            if pf.execute_buy(wallet, ticker, close, atr=atr, regime=regime, signals=signals):
                sector_count[candidate_sector] = sector_count.get(candidate_sector, 0) + 1
                found += 1
    
    def _close_all_positions(self, wallet: dict):
        """Close all positions at end of simulation."""
        for ticker in list(wallet["holdings"].keys()):
            pos = wallet["holdings"][ticker]
            if pos.get("is_baseline"):
                continue  # Don't close baseline
            
            price = pos.get("last_price", pos["entry_price"])
            qty = pos.get("qty", 0)
            
            if qty > 0:
                pnl = pf.execute_sell(wallet, ticker, price, qty, "End of simulation")
                
                # Record trade
                trade_record = {
                    "Ticker": ticker,
                    "Time": self.time_sim.now_str(),
                    "Action": "SELL",
                    "Price": price,
                    "Qty": qty,
                    "PnL": pnl,
                    "PnL_Pct": (price - pos["entry_price"]) / pos["entry_price"] if pos["entry_price"] > 0 else 0,
                    "Reason": "End of simulation",
                    "Regime": pos.get("regime", "UNKNOWN"),
                    "Entry_Time": pos.get("entry_time", ""),
                    "Entry_Price": pos.get("entry_price", 0),
                }
                signals = pos.get("signals", {})
                if isinstance(signals, dict):
                    trade_record["Sector"] = signals.get("sector", "Unknown")
                    trade_record["Signals"] = signals
                trade_record["Reasoning"] = pos.get("reasoning", "")
                
                self.metrics.record_trade(trade_record)


def interactive_cli():
    config_path = input("Config path [default: configs/strategy/default.yaml]: ").strip()
    if not config_path:
        config_path = "configs/strategy/default.yaml"

    profile = input("Profile (conservative|balanced|aggressive) [default: balanced]: ").strip()
    if not profile:
        profile = "balanced"

    """Interactive CLI for configuring and running historical test."""
    print("\n" + "="*60)
    print("  HISTORICAL TRADING TESTER")
    print("="*60 + "\n")

    mode = input("Mode (single/sweep/walk/compare/benchmark) [default: single]: ").strip().lower() or "single"
    engine = input("Engine (native/backtrader) [default: native]: ").strip().lower() or "native"
    
    # Get start date
    while True:
        start_str = input("Start date (YYYY-MM-DD) [default: 2024-01-01]: ").strip()
        if not start_str:
            start_str = "2024-01-01"
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d")
            start_date = start_date.replace(tzinfo=zoneinfo.ZoneInfo("America/New_York"))
            break
        except ValueError:
            print("  Invalid date format. Please use YYYY-MM-DD.")
    
    # Get end date
    while True:
        end_str = input("End date (YYYY-MM-DD) [default: 2024-03-01]: ").strip()
        if not end_str:
            end_str = "2024-03-01"
        try:
            end_date = datetime.strptime(end_str, "%Y-%m-%d")
            end_date = end_date.replace(tzinfo=zoneinfo.ZoneInfo("America/New_York"))
            if end_date <= start_date:
                print("  End date must be after start date.")
                continue
            break
        except ValueError:
            print("  Invalid date format. Please use YYYY-MM-DD.")
    
    # Get speed multiplier
    while True:
        speed_str = input("Speed multiplier (1x, 10x, 100x, etc.) [default: 10x]: ").strip().lower()
        if not speed_str:
            speed_str = "10x"
        try:
            if speed_str.endswith("x"):
                speed_multiplier = float(speed_str[:-1])
            else:
                speed_multiplier = float(speed_str)
            break
        except ValueError:
            print("  Invalid speed. Please enter a number (e.g., 10 or 10x).")
    
    # Get wallet path
    wallet_path = input("Wallet path [default: test_wallet.json]: ").strip()
    if not wallet_path:
        wallet_path = "test_wallet.json"
    
    # Get initial capital
    while True:
        capital_str = input("Initial capital [default: 100000]: ").strip()
        if not capital_str:
            initial_capital = None
            break
        try:
            initial_capital = float(capital_str)
            break
        except ValueError:
            print("  Invalid amount. Please enter a number.")
    
    # Get news sentiment (blank = config default)
    news_str = input("Enable news sentiment? (y/n, blank=profile default): ").strip().lower()
    enable_news = None if not news_str else (news_str == "y")

    # Get earnings calendar (blank = config default)
    earnings_str = input("Enable earnings calendar? (y/n, blank=profile default): ").strip().lower()
    enable_earnings = None if not earnings_str else (earnings_str == "y")
    
    print("\n" + "="*60)
    print("  Starting simulation...")
    print("="*60 + "\n")
    
    # Create and run tester
    tester = HistoricalTester(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        wallet_path=wallet_path,
        speed_multiplier=speed_multiplier,
        enable_news=enable_news,
        enable_earnings=enable_earnings,
        config_path=config_path,
        profile=profile,
        engine=engine,
    )
    if mode == "single":
        tester.run()
    elif mode == "sweep":
        try:
            from .optimizer import run_parameter_sweep
        except ImportError:
            from optimizer import run_parameter_sweep
        sweep_sets = [
            ["risk.max_positions_per_sector=2"],
            ["risk.max_positions_per_sector=3"],
            ["risk.max_positions_per_sector=4"],
        ]
        base_kwargs = {
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "wallet_path": wallet_path,
            "speed_multiplier": speed_multiplier,
            "enable_news": enable_news,
            "enable_earnings": enable_earnings,
            "config_path": config_path,
            "profile": profile,
        }
        results = run_parameter_sweep(base_kwargs, sweep_sets, engine=engine)
        print(f"Sweep completed: {len(results)} runs")
    elif mode == "walk":
        try:
            from .optimizer import run_walk_forward
        except ImportError:
            from optimizer import run_walk_forward
        base_kwargs = {
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "wallet_path": wallet_path,
            "speed_multiplier": speed_multiplier,
            "enable_news": enable_news,
            "enable_earnings": enable_earnings,
            "config_path": config_path,
            "profile": profile,
        }
        results = run_walk_forward(base_kwargs, window_days=30, step_days=15, engine=engine)
        print(f"Walk-forward completed: {len(results)} windows")
    elif mode == "compare":
        try:
            from .optimizer import run_ab_compare
        except ImportError:
            from optimizer import run_ab_compare
        prof_b = input("Compare against profile [default: aggressive]: ").strip() or "aggressive"
        base_kwargs = {
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "wallet_path": wallet_path,
            "speed_multiplier": speed_multiplier,
            "enable_news": enable_news,
            "enable_earnings": enable_earnings,
            "config_path": config_path,
        }
        res = run_ab_compare(base_kwargs, profile, prof_b, engine=engine)
        print(f"Compare complete. Delta return: {res['delta_return_pct']:+.2f}%")
    elif mode == "benchmark":
        try:
            from .orchestrator import run_benchmark_suite
        except ImportError:
            from orchestrator import run_benchmark_suite
        engine_list = input("Engines csv [default: native,backtrader]: ").strip() or "native,backtrader"
        validate_with = input("Validate with lean? (y/n) [default: n]: ").strip().lower()
        engine_names = [name.strip() for name in engine_list.split(",") if name.strip()]
        base_kwargs = {
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "wallet_path": wallet_path,
            "speed_multiplier": speed_multiplier,
            "enable_news": enable_news,
            "enable_earnings": enable_earnings,
            "config_path": config_path,
            "profile": profile,
        }
        suite = run_benchmark_suite(
            engine_names=engine_names,
            tester_kwargs=base_kwargs,
            validate_with="lean" if validate_with == "y" else None,
        )
        print(f"Benchmark complete. Artifacts: {suite['report_paths']}")
    else:
        print("Unknown mode; running single.")
        tester.run()


if __name__ == "__main__":
    interactive_cli()
