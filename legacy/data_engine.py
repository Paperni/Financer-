import yfinance as yf
import pandas as pd
import os
from bs4 import BeautifulSoup
from downloader import get_ticker, download_reports

class DataEngine:
    def __init__(self, company_name, email="your.email@example.com"):
        self.company_name = company_name
        self.ticker = get_ticker(company_name)
        self.email = email
        if not self.ticker:
            raise ValueError(f"Could not resolve ticker for {company_name}")
            
    def get_financials(self):
        """
        Fetches structured financial data from yfinance.
        Returns a dictionary containing balance sheet, income statement, and cash flow.
        """
        print(f"Fetching financial data for {self.ticker}...")
        stock = yf.Ticker(self.ticker)
        
        # Helper to safely get data
        try:
            info = stock.info
            balance_sheet = stock.balance_sheet
            income_stmt = stock.income_stmt
            cash_flow = stock.cashflow
            
            return {
                "info": info,
                "balance_sheet": balance_sheet,
                "income_stmt": income_stmt,
                "cash_flow": cash_flow,
                "history": stock.history(period="10y") # Needed for DCF beta/volatility potentially
            }
        except Exception as e:
            print(f"Error fetching financials: {e}")
            return None

    def get_latest_10k_text(self):
        """
        Downloads (if not present) and parses the latest 10-K filing.
        Returns the text content of the 10-K.
        """
        # Ensure reports exist
        download_reports(self.company_name, self.email)
        
        base_dir = os.path.join("reports", "sec-edgar-filings", self.ticker, "10-K")
        if not os.path.exists(base_dir):
            print("No 10-K directory found.")
            return ""

        # Find the most recent filing directory
        subdirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
        if not subdirs:
            print("No 10-K filings found.")
            return ""
            
        # Sort by creation time (approximation of recency if not using accession number logic)
        # Better: lexicographical sort of accession numbers usually works for recency if format implies date
        # But standard os.listdir order isn't guaranteed. 
        # Let's just pick the first one for now as downloader fetched "limit=1" latest.
        latest_filing_dir = subdirs[0] 
        
        # Find the HTML file (usually 'primary-document.html' or similar)
        # sec-edgar-downloader saves it as 'filing-details.html' or similar full text
        # Let's look for *.html or *.txt
        for file in os.listdir(latest_filing_dir):
            if file.endswith(".html") or file.endswith(".txt"):
                file_path = os.path.join(latest_filing_dir, file)
                print(f"Parsing 10-K from: {file_path}")
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    soup = BeautifulSoup(content, 'html.parser')
                    text = soup.get_text(separator="\n")
                    return text
                except Exception as e:
                    print(f"Error parsing 10-K: {e}")
                    return ""
        
        return ""

if __name__ == "__main__":
    # Test
    de = DataEngine("Apple")
    fin = de.get_financials()
    print("Market Cap:", fin['info'].get('marketCap'))
    text = de.get_latest_10k_text()
    print("10-K Text Length:", len(text))
