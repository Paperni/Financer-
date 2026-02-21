import os
import sys
import yfinance as yf
from sec_edgar_downloader import Downloader

def get_ticker(company_name):
    """
    Attempts to find a stock ticker for a given company name using yfinance.
    """
    print(f"Searching for ticker for: {company_name}...")
    try:
        # yfinance doesn't have a direct "search by name" that returns a single string,
        # but we can try to use the Ticker object or search suggestions.
        # A common trick is to use the search functionality if available or just try the name.
        # For simplicity in this 'small' start, we'll try to find it via yf.utils
        # or just inform the user we're using a heuristic.
        
        # Searching via yfinance Ticker might not work for name.
        # Let's use a more robust way: yf.Search (if version supports it) or a simple mapping.
        search = yf.Search(company_name, max_results=1)
        if search.quotes:
            ticker = search.quotes[0]['symbol']
            print(f"Found ticker: {ticker}")
            return ticker
        else:
            print(f"Could not find a ticker for '{company_name}'.")
            return None
    except Exception as e:
        print(f"Error searching for ticker: {e}")
        return None

def download_reports(company_name, email):
    """
    Downloads the most recent 10-K and 10-Q reports for a company.
    """
    ticker = get_ticker(company_name)
    if not ticker:
        return

    # SEC EDGAR requires a User-Agent string with email for identification
    dl = Downloader("FinancerApp", email, "reports")

    print(f"Downloading recent filings for {ticker}...")
    
    # Download 10-K (Annual reports) - get the most recent one
    print("- Fetching latest 10-K...")
    dl.get("10-K", ticker, limit=1, download_details=True)
    
    # Download 10-Q (Quarterly reports) - get the 2 most recent ones
    print("- Fetching latest 10-Qs...")
    dl.get("10-Q", ticker, limit=2, download_details=True)

    print(f"\nDone! Reports for {ticker} are saved in the 'reports' folder.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        name = input("Enter company name (e.g., Apple, Tesla): ")
    else:
        name = sys.argv[1]
    
    # Using a placeholder email as required by SEC EDGAR downloader.
    # In a real app, this should be the developer's or user's email.
    placeholder_email = "your.email@example.com"
    
    download_reports(name, placeholder_email)
