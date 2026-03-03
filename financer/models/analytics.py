"""Mathematical utilities for risk management and performance attribution."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_annualized_volatility(returns: pd.Series, periods: int = 252) -> float:
    """Calculate annualized standard deviation of returns."""
    if returns.empty or len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(periods))


class CVaRCalculator:
    """Evaluates the 99% Conditional Value-at-Risk (Expected Shortfall) of a portfolio."""

    @staticmethod
    def calculate_es_99(portfolio_returns: pd.Series) -> float:
        """
        Calculates the expected shortfall at the 99% confidence interval.
        Returns the expected loss as a positive float (e.g., 0.049 for 4.9%).
        """
        if portfolio_returns.empty or len(portfolio_returns) < 100:
            return 0.0
            
        # Sort returns worst to best
        sorted_returns = portfolio_returns.sort_values(ascending=True)
        
        # Find the 1% tail (99% confidence)
        tail_cutoff_idx = max(1, int(len(sorted_returns) * 0.01))
        tail_losses = sorted_returns.iloc[:tail_cutoff_idx]
        
        # Expected Shortfall is the mean of the losses in the tail
        expected_shortfall = tail_losses.mean()
        
        return abs(float(expected_shortfall))

    @classmethod
    def evaluate_proposed_portfolio(
        cls, 
        current_positions: list[tuple[str, float]], 
        proposed_intents: list[tuple[str, float]], 
        historical_returns_map: dict[str, pd.Series]
    ) -> float:
        """
        Simulates the portfolio return series including proposed intents 
        and calculates the resulting ES_0.99.
        """
        combined_allocations: dict[str, float] = {}
        for ticker, weight in current_positions + proposed_intents:
            combined_allocations[ticker] = combined_allocations.get(ticker, 0.0) + weight

        # Build synthetic portfolio returns stream
        portfolio_series = None
        
        for ticker, weight in combined_allocations.items():
            if ticker in historical_returns_map:
                asset_returns = historical_returns_map[ticker] * weight
                if portfolio_series is None:
                    portfolio_series = asset_returns.copy()
                else:
                    # Align and add
                    portfolio_series = portfolio_series.add(asset_returns, fill_value=0.0)

        if portfolio_series is None:
            return 0.0
            
        return cls.calculate_es_99(portfolio_series)
