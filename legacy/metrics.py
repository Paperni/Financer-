import pandas as pd
import numpy as np

class QuantitativeCore:
    def __init__(self, financials):
        self.financials = financials
        self.info = financials.get("info", {})
        self.bs = financials.get("balance_sheet")
        self.is_ = financials.get("income_stmt")
        self.cf = financials.get("cash_flow")

    def get_latest_value(self, df, key):
        """Helper to get the most recent value from a dataframe row."""
        try:
            if key in df.index:
                return df.loc[key].iloc[0]
        except Exception:
            pass
        return 0.0

    def calculate_roic(self):
        """
        ROIC = NOPAT / Invested Capital
        NOPAT = EBIT * (1 - Tax Rate)
        Invested Capital = Total Equity + Total Debt - Cash & Equivalents
        """
        try:
            ebit = self.get_latest_value(self.is_, "EBIT")
            tax_provision = self.get_latest_value(self.is_, "Tax Provision")
            pretax_income = self.get_latest_value(self.is_, "Pretax Income")
            
            tax_rate = tax_provision / pretax_income if pretax_income else 0.21
            nopat = ebit * (1 - tax_rate)
            
            total_equity = self.get_latest_value(self.bs, "Stockholders Equity")
            total_debt = self.get_latest_value(self.bs, "Total Debt")
            cash = self.get_latest_value(self.bs, "Cash And Cash Equivalents")
            
            invested_capital = total_equity + total_debt - cash
            
            if invested_capital == 0:
                return 0.0
                
            return (nopat / invested_capital) * 100
        except Exception as e:
            print(f"Error calculating ROIC: {e}")
            return 0.0

    def calculate_fcf_yield(self):
        """
        FCF Yield = Free Cash Flow / Market Cap
        """
        try:
            fcf = self.get_latest_value(self.cf, "Free Cash Flow")
            market_cap = self.info.get("marketCap", 1)
            
            if not fcf or not market_cap:
                return 0.0
                
            return (fcf / market_cap) * 100
        except Exception:
            return 0.0

    def analyze_margin_trends(self):
        """
        Returns 'Expanding', 'Contracting', or 'Stable' based on 3-year trend of Operating Margins.
        """
        try:
            # Get last 3 years of Operating Income and Total Revenue
            # df columns are dates, typically descending. Take first 3.
            years = self.is_.columns[:3]
            margins = []
            
            for date in years:
                op_income = self.is_.loc["Operating Income", date]
                revenue = self.is_.loc["Total Revenue", date]
                if revenue:
                    margins.append(op_income / revenue)
            
            # Margins are [Recent, Year-1, Year-2]
            # We want to see if Recent > Year-1 > Year-2
            if len(margins) < 2:
                return "Insufficient Data"
                
            # Simple slope check
            # Reverse to chronological order for trend: [Year-2, Year-1, Recent]
            margins_chrono = margins[::-1]
            slope = np.polyfit(range(len(margins_chrono)), margins_chrono, 1)[0]
            
            if slope > 0.005: # > 0.5% growth per year
                return "Expanding"
            elif slope < -0.005:
                return "Contracting"
            else:
                return "Stable"
        except Exception:
            return "Unknown"

    def run_dcf_analysis(self):
        """
        Perform a 10-year DCF analysis.
        Start with last known FCF.
        Output: Intrinsic Value per Share, Underlying Assumptions.
        """
        try:
            fcf_start = self.get_latest_value(self.cf, "Free Cash Flow")
            if fcf_start <= 0:
                return None, "Negative FCF - DCF N/A"

            # Assumptions
            # 1. Growth Rate: Conservative 5% or historical average (capped at 10%)
            growth_rate = 0.05 
            
            # WACC Estimation (Simplified)
            # Cost of Equity = Risk Free + Beta * Risk Premium
            rf_rate = 0.04 # 4% treasury
            beta = self.info.get("beta", 1.0)
            market_premium = 0.05 # 5%
            cost_of_equity = rf_rate + beta * market_premium
            
            # Cost of Debt (Interest Expense / Total Debt)
            interest_expense = self.get_latest_value(self.is_, "Interest Expense")
            total_debt = self.get_latest_value(self.bs, "Total Debt")
            cost_of_debt = (interest_expense / total_debt) if total_debt else 0.04
            
            # Capital Structure
            market_cap = self.info.get("marketCap", 1)
            total_value = market_cap + total_debt
            we = market_cap / total_value
            wd = total_debt / total_value
            tax_rate = 0.21
            
            wacc = (we * cost_of_equity) + (wd * cost_of_debt * (1 - tax_rate))
            if wacc < 0.05: wacc = 0.05 # Floor WACC
            
            # Projection
            future_fcf = []
            for i in range(1, 11):
                fcf = fcf_start * ((1 + growth_rate) ** i)
                future_fcf.append(fcf)
                
            # Terminal Value (Perpetuity Growth Method)
            terminal_growth = 0.025 # 2.5% long term inflation
            terminal_value = (future_fcf[-1] * (1 + terminal_growth)) / (wacc - terminal_growth)
            
            # Discounting
            dcf_value = 0
            for i, fcf in enumerate(future_fcf):
                dcf_value += fcf / ((1 + wacc) ** (i + 1))
                
            dcf_value += terminal_value / ((1 + wacc) ** 10)
            
            shares_outstanding = self.info.get("sharesOutstanding", 1)
            intrinsic_value = dcf_value / shares_outstanding
            
            return intrinsic_value, f"WACC: {wacc:.1%}, Growth: {growth_rate:.1%}"
            
        except Exception as e:
            print(f"DCF Error: {e}")
            return None, str(e)

if __name__ == "__main__":
    from data_engine import DataEngine
    de = DataEngine("Apple")
    fin = de.get_financials()
    qc = QuantitativeCore(fin)
    print(f"ROIC: {qc.calculate_roic():.2f}%")
    print(f"FCF Yield: {qc.calculate_fcf_yield():.2f}%")
    print(f"Margin Trend: {qc.analyze_margin_trends()}")
    value, assumptions = qc.run_dcf_analysis()
    print(f"Intrinsic Value: ${value:.2f} ({assumptions})")
