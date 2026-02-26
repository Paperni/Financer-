"""
Performance Metrics Collector

Collects comprehensive performance metrics during historical simulation.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime


class MetricsCollector:
    """Collects and calculates performance metrics from wallet and trade history."""
    
    def __init__(self, initial_capital: float):
        """Initialize metrics collector."""
        self.initial_capital = initial_capital
        self.equity_curve = []  # List of (timestamp, equity) tuples
        self.trades = []  # List of completed trades
        self.regime_performance = {}  # regime -> {trades, wins, pnl}
        self.sector_performance = {}  # sector -> {trades, wins, pnl}
        self.score_performance = {}  # score -> {trades, wins, pnl}
    
    def record_equity(self, timestamp: str, equity: float):
        """Record equity at a point in time."""
        self.equity_curve.append((timestamp, equity))
    
    def record_trade(self, trade: dict):
        """Record a completed trade."""
        # Only record SELL trades (completed positions)
        if trade.get("Action") == "SELL":
            # Ensure PnL is set (calculate if missing)
            if trade.get("PnL") is None:
                price = trade.get("Price", 0)
                qty = trade.get("Qty", 0)
                # Try to get entry price from trade data
                entry_price = trade.get("Entry_Price", 0)
                if entry_price == 0:
                    # Estimate from PnL_Pct if available
                    pnl_pct = trade.get("PnL_Pct", 0)
                    if pnl_pct != 0 and price > 0:
                        entry_price = price / (1 + pnl_pct)
                trade["PnL"] = (price - entry_price) * qty if entry_price > 0 else 0
            
            self.trades.append(trade.copy())
    
    def calculate_metrics(self, wallet: dict) -> dict:
        """
        Calculate comprehensive performance metrics.
        
        Returns:
            Dictionary with all calculated metrics
        """
        final_equity = wallet.get("cash", 0)
        for pos in wallet.get("holdings", {}).values():
            if not pos.get("is_baseline"):
                final_equity += pos.get("qty", 0) * pos.get("last_price", pos.get("entry_price", 0))
        
        # Basic metrics
        total_return = (final_equity - self.initial_capital) / self.initial_capital
        total_fees = wallet.get("total_fees", 0)
        net_return = (final_equity - self.initial_capital - total_fees) / self.initial_capital
        
        # Trade metrics
        trades_df = pd.DataFrame(self.trades) if self.trades else pd.DataFrame()
        total_trades = len(trades_df)
        
        win_rate = 0.0
        avg_win = 0.0
        avg_loss = 0.0
        best_trade = None
        worst_trade = None
        avg_hold_time = None
        
        if total_trades > 0:
            wins = trades_df[trades_df["PnL"] > 0]
            losses = trades_df[trades_df["PnL"] <= 0]
            
            win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
            avg_win = wins["PnL"].mean() if len(wins) > 0 else 0.0
            avg_loss = losses["PnL"].mean() if len(losses) > 0 else 0.0
            
            if len(trades_df) > 0:
                best_trade = trades_df.loc[trades_df["PnL"].idxmax()].to_dict()
                worst_trade = trades_df.loc[trades_df["PnL"].idxmin()].to_dict()
            
            # Calculate average hold time
            if "Entry_Time" in trades_df.columns and "Time" in trades_df.columns:
                hold_times = []
                for _, trade in trades_df.iterrows():
                    try:
                        entry = pd.Timestamp(trade["Entry_Time"])
                        exit_time = pd.Timestamp(trade["Time"])
                        hold_times.append((exit_time - entry).total_seconds() / 3600)  # hours
                    except:
                        pass
                avg_hold_time = np.mean(hold_times) if hold_times else None
        
        # Drawdown metrics
        equity_df = pd.DataFrame(self.equity_curve, columns=["timestamp", "equity"])
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        
        if len(equity_df) > 0:
            equity_df["cummax"] = equity_df["equity"].cummax()
            equity_df["drawdown"] = equity_df["equity"] - equity_df["cummax"]
            equity_df["drawdown_pct"] = (equity_df["drawdown"] / equity_df["cummax"]) * 100
            
            max_drawdown = equity_df["drawdown"].min()
            max_drawdown_pct = equity_df["drawdown_pct"].min()
        
        # Sharpe-like ratio
        sharpe_ratio = None
        if len(equity_df) > 1:
            equity_df["returns"] = equity_df["equity"].pct_change()
            daily_returns = equity_df["returns"].dropna()
            if len(daily_returns) > 0 and daily_returns.std() > 0:
                # Annualized Sharpe (assuming hourly data, ~252*6.5 trading hours per year)
                trading_hours_per_year = 252 * 6.5
                avg_return = daily_returns.mean() * trading_hours_per_year
                std_return = daily_returns.std() * np.sqrt(trading_hours_per_year)
                sharpe_ratio = avg_return / std_return if std_return > 0 else 0.0
        
        # Fee drag
        fee_drag_pct = (total_fees / self.initial_capital) * 100 if self.initial_capital > 0 else 0.0
        
        # Regime performance
        regime_metrics = self._calculate_regime_metrics(trades_df)
        
        # Sector performance
        sector_metrics = self._calculate_sector_metrics(trades_df)
        
        # Score performance
        score_metrics = self._calculate_score_metrics(trades_df)
        
        # Trade distribution
        trade_distribution = self._calculate_trade_distribution(trades_df)
        
        return {
            # Basic metrics
            "initial_capital": self.initial_capital,
            "final_equity": final_equity,
            "total_return_pct": total_return * 100,
            "net_return_pct": net_return * 100,
            "total_fees": total_fees,
            "fee_drag_pct": fee_drag_pct,
            
            # Trade metrics
            "total_trades": total_trades,
            "win_rate_pct": win_rate * 100,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "avg_hold_time_hours": avg_hold_time,
            
            # Risk metrics
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "sharpe_ratio": sharpe_ratio,
            
            # Detailed breakdowns
            "regime_performance": regime_metrics,
            "sector_performance": sector_metrics,
            "score_performance": score_metrics,
            "trade_distribution": trade_distribution,
            
            # Raw data
            "equity_curve": self.equity_curve,
            "trades": [t for t in self.trades],
        }
    
    def _calculate_regime_metrics(self, trades_df: pd.DataFrame) -> dict:
        """Calculate performance by market regime."""
        if trades_df.empty or "Regime" not in trades_df.columns:
            return {}
        
        regimes = {}
        for regime in trades_df["Regime"].unique():
            regime_trades = trades_df[trades_df["Regime"] == regime]
            wins = regime_trades[regime_trades["PnL"] > 0]
            
            regimes[regime] = {
                "trades": len(regime_trades),
                "wins": len(wins),
                "win_rate_pct": (len(wins) / len(regime_trades) * 100) if len(regime_trades) > 0 else 0.0,
                "total_pnl": regime_trades["PnL"].sum(),
                "avg_pnl": regime_trades["PnL"].mean(),
            }
        
        return regimes
    
    def _calculate_sector_metrics(self, trades_df: pd.DataFrame) -> dict:
        """Calculate performance by sector."""
        if trades_df.empty or "Sector" not in trades_df.columns:
            return {}
        
        sectors = {}
        for sector in trades_df["Sector"].dropna().unique():
            sector_trades = trades_df[trades_df["Sector"] == sector]
            wins = sector_trades[sector_trades["PnL"] > 0]
            
            sectors[sector] = {
                "trades": len(sector_trades),
                "wins": len(wins),
                "win_rate_pct": (len(wins) / len(sector_trades) * 100) if len(sector_trades) > 0 else 0.0,
                "total_pnl": sector_trades["PnL"].sum(),
                "avg_pnl": sector_trades["PnL"].mean(),
            }
        
        return sectors
    
    def _calculate_score_metrics(self, trades_df: pd.DataFrame) -> dict:
        """Calculate performance by entry score."""
        if trades_df.empty:
            return {}
        
        # Try to extract score from signals or reasoning
        scores = {}
        for _, trade in trades_df.iterrows():
            score = None
            signals = trade.get("Signals", {})
            if isinstance(signals, dict):
                score = signals.get("score")
            if score is None:
                # Try to parse from reasoning
                reasoning = trade.get("Reasoning", "")
                if reasoning and "/8" in reasoning:
                    try:
                        score = int(reasoning.split("/8")[0].split()[-1])
                    except:
                        pass
            
            if score is None:
                score = "Unknown"
            else:
                score = str(int(score))
            
            if score not in scores:
                scores[score] = {"trades": 0, "wins": 0, "total_pnl": 0.0, "pnls": []}
            
            scores[score]["trades"] += 1
            pnl = trade.get("PnL", 0)
            scores[score]["total_pnl"] += pnl
            scores[score]["pnls"].append(pnl)
            if pnl > 0:
                scores[score]["wins"] += 1
        
        # Calculate averages
        for score in scores:
            if scores[score]["trades"] > 0:
                scores[score]["win_rate_pct"] = (scores[score]["wins"] / scores[score]["trades"]) * 100
                scores[score]["avg_pnl"] = scores[score]["total_pnl"] / scores[score]["trades"]
        
        return scores
    
    def _calculate_trade_distribution(self, trades_df: pd.DataFrame) -> dict:
        """Calculate trade distribution statistics."""
        if trades_df.empty:
            return {}
        
        pnl_values = trades_df["PnL"].values
        
        return {
            "pnl_mean": float(np.mean(pnl_values)),
            "pnl_std": float(np.std(pnl_values)),
            "pnl_median": float(np.median(pnl_values)),
            "pnl_min": float(np.min(pnl_values)),
            "pnl_max": float(np.max(pnl_values)),
            "positive_trades": int(np.sum(pnl_values > 0)),
            "negative_trades": int(np.sum(pnl_values <= 0)),
        }
