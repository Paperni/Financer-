import re
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from textblob import TextBlob
from pathlib import Path
from datetime import datetime
import time
import technical
import news_engine

try:
    from finvizfinance.quote import finvizfinance as Finviz
    from finvizfinance.screener.overview import Overview as FinvizScreener
    HAS_FINVIZ = True
except ImportError:
    HAS_FINVIZ = False

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ── Constants ──────────────────────────────────────────────────────────────────
TERMINAL_GROWTH = 0.025
MARGIN_OF_SAFETY_TARGET = 0.30
RISK_FREE_RATE = 0.043  # 10-year Treasury yield (~4.3% as of early 2026)

# Sector-specific equity risk premiums (base ERP + sector adjustment)
# Reflects different risk profiles: stable sectors get lower discount rates
SECTOR_DISCOUNT_RATES = {
    "Technology":              0.095,  # High growth, moderate risk
    "Healthcare":              0.090,  # Defensive + innovation mix
    "Financial Services":      0.100,  # Regulatory & cycle risk
    "Consumer Cyclical":       0.095,  # Economic sensitivity
    "Consumer Defensive":      0.080,  # Stable cash flows, low risk
    "Industrials":             0.090,  # Moderate cyclicality
    "Energy":                  0.105,  # Commodity & geopolitical risk
    "Communication Services":  0.090,  # Mixed stability
    "Real Estate":             0.085,  # Stable income streams
    "Utilities":               0.075,  # Regulated, very stable
    "Basic Materials":         0.100,  # Commodity exposure
}
DEFAULT_DISCOUNT_RATE = 0.095

COMPLEX_INDUSTRIES = [
    "biotechnology", "crypto", "cannabis", "spac", "blank check",
    "shell companies", "special purpose acquisition",
]
COMPLEX_SECTORS = ["financial services"]

# yfinance → FINVIZ sector name mapping (where they differ)
YFINANCE_TO_FINVIZ_SECTOR = {
    "Financial Services": "Financial",
}

# Fallback peer lists when FINVIZ screener is unavailable
SECTOR_PEER_CANDIDATES = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "CSCO", "ACN", "IBM", "INTC", "AMD", "TXN", "QCOM"],
    "Healthcare": ["JNJ", "UNH", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY", "AMGN", "MDT", "ISRG", "GILD", "CVS"],
    "Financial Services": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "C", "USB", "PNC", "TFC", "COF", "MMC"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "BKNG", "CMG", "ABNB", "MAR"],
    "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "MDLZ", "GIS", "KHC", "STZ"],
    "Industrials": ["HON", "UNP", "UPS", "RTX", "CAT", "DE", "BA", "GE", "LMT", "MMM", "ITW", "EMR"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HES", "DVN"],
    "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA", "T", "VZ", "TMUS", "CHTR", "EA", "TTWO"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "WELL", "DLR", "AVB"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "WEC", "ES"],
    "Basic Materials": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DD", "DOW", "VMC"],
}


# ── Utility ────────────────────────────────────────────────────────────────────
def _safe(func, default=None):
    try:
        r = func()
        return r if r is not None else default
    except Exception:
        return default


def _pct(v):
    if v is None or v == "N/A":
        return "N/A"
    return f"{v * 100:.1f}%"


def _fmt_money(v, billions=False):
    if v is None or v == "N/A":
        return "N/A"
    if billions:
        return f"${v / 1e9:,.1f}B"
    return f"${v:,.0f}"


def _cv(series):
    s = series.dropna()
    if len(s) < 2 or s.mean() == 0:
        return None
    return float(s.std() / abs(s.mean()))


def _cagr(first, last, years):
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _trend(series):
    s = series.dropna()
    if len(s) < 2:
        return "Insufficient Data"
    first_half = s.iloc[len(s)//2:].mean()
    second_half = s.iloc[:len(s)//2].mean()
    if first_half == 0:
        return "Stable"
    change = (second_half - first_half) / abs(first_half)
    if change > 0.03:
        return "Expanding"
    elif change < -0.03:
        return "Contracting"
    return "Stable"



def get_10k_text(ticker, base_path="reports"):
    """
    Reads the latest 10-K HTML file and returns plain text usage for NLP.
    """
    path = find_latest_filing(base_path, ticker, "10-K")
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "lxml")
        return soup.get_text(separator=" ")
    except Exception:
        return ""

def analyze_sentiment(text):
    """
    Returns polarity (-1 to 1) and subjectivity (0 to 1).
    """
    if not text:
        return 0, 0
    blob = TextBlob(text[:100000]) # Truncate to avoids memory issues
    return blob.sentiment.polarity, blob.sentiment.subjectivity

# ── Data Fetching ──────────────────────────────────────────────────────────────
def fetch_yfinance_data(ticker):
    t = yf.Ticker(ticker)
    data = {"ticker": ticker, "error": None}

    data["info"] = _safe(lambda: t.info, {})
    data["financials"] = _safe(lambda: t.financials, pd.DataFrame())
    data["balance_sheet"] = _safe(lambda: t.balance_sheet, pd.DataFrame())
    data["cashflow"] = _safe(lambda: t.cashflow, pd.DataFrame())
    data["quarterly_financials"] = _safe(lambda: t.quarterly_financials, pd.DataFrame())

    data["insider_purchases"] = _safe(lambda: t.insider_purchases, pd.DataFrame())
    data["growth_estimates"] = _safe(lambda: t.growth_estimates, pd.DataFrame())
    data["analyst_price_targets"] = _safe(lambda: t.analyst_price_targets, {})
    data["history"] = _safe(lambda: t.history(period="2y"), pd.DataFrame())

    return data


# ── FINVIZ Data Fetching ──────────────────────────────────────────────────────
def fetch_finviz_data(ticker):
    """Fetch supplemental data from FINVIZ. Returns dict with fundament, ratings, news, insiders."""
    result = {
        "fundament": {},
        "ratings": pd.DataFrame(),
        "news": pd.DataFrame(),
        "insiders": pd.DataFrame(),
    }
    if not HAS_FINVIZ:
        return result

    try:
        stock = Finviz(ticker)
    except Exception:
        print(f"  [FINVIZ] Could not initialize for {ticker}")
        return result

    print("  Fetching FINVIZ fundamentals...")
    result["fundament"] = _safe(lambda: stock.ticker_fundament(), {})
    time.sleep(0.5)

    print("  Fetching FINVIZ analyst ratings...")
    result["ratings"] = _safe(lambda: stock.ticker_outer_ratings(), pd.DataFrame())
    time.sleep(0.5)

    print("  Fetching FINVIZ news headlines...")
    result["news"] = _safe(lambda: stock.ticker_news(), pd.DataFrame())
    time.sleep(0.5)

    print("  Fetching FINVIZ insider trades...")
    result["insiders"] = _safe(lambda: stock.ticker_inside_trader(), pd.DataFrame())

    return result


# ── Sector Peer Selection & Fetching ──────────────────────────────────────────
def _score_and_select_peers(candidates, ticker, industry, market_cap, n=5):
    """Score peer candidates by industry match and market cap proximity, return top n with info cache."""
    scored = []
    info_cache = {}
    checked = 0
    for c in candidates:
        if c == ticker:
            continue
        if checked >= 10:
            break
        checked += 1
        c_info = _safe(lambda c=c: yf.Ticker(c).info, {})
        if not c_info or not c_info.get("marketCap"):
            continue
        info_cache[c] = c_info
        c_mcap = c_info.get("marketCap", 0)
        c_industry = c_info.get("industry", "")

        score = 0
        if c_industry == industry:
            score += 2
        if market_cap > 0 and c_mcap > 0:
            ratio = c_mcap / market_cap
            if 0.25 <= ratio <= 4.0:
                score += 1
        scored.append((c, score, c_mcap))

    scored.sort(key=lambda x: (-x[1], -x[2]))
    selected = [s[0] for s in scored[:n]]
    return selected, {t: info_cache[t] for t in selected if t in info_cache}


def select_sector_peers(ticker, info, n=5):
    sector = info.get("sector", "")
    market_cap = info.get("marketCap", 0) or 0
    industry = info.get("industry", "")

    # Try FINVIZ screener first
    if HAS_FINVIZ and sector:
        try:
            fv_sector = YFINANCE_TO_FINVIZ_SECTOR.get(sector, sector)
            print(f"  [FINVIZ] Screening {fv_sector} sector peers...")
            foverview = FinvizScreener()
            foverview.set_filter(filters_dict={"Sector": fv_sector})
            # Suppress finvizfinance progress bar output
            import io, sys
            _old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                screener_df = foverview.screener_view()
            finally:
                sys.stdout = _old_stdout
            time.sleep(0.5)

            if screener_df is not None and not screener_df.empty:
                # Remove target ticker
                ticker_col = "Ticker" if "Ticker" in screener_df.columns else screener_df.columns[1]
                screener_df = screener_df[screener_df[ticker_col] != ticker]

                # Parse market cap for proximity sorting
                def _parse_mcap(val):
                    try:
                        s = str(val).upper().strip()
                        if s.endswith("B"):
                            return float(s[:-1]) * 1e9
                        elif s.endswith("M"):
                            return float(s[:-1]) * 1e6
                        return float(s)
                    except Exception:
                        return 0

                if "Market Cap" in screener_df.columns and market_cap > 0:
                    screener_df = screener_df.copy()
                    screener_df["_mcap"] = screener_df["Market Cap"].apply(_parse_mcap)
                    screener_df["_ratio"] = screener_df["_mcap"].apply(
                        lambda x: abs(x / market_cap - 1) if x > 0 else 999
                    )
                    screener_df = screener_df.sort_values("_ratio")

                candidates = screener_df[ticker_col].head(n * 2).tolist()
                if candidates:
                    selected, cache = _score_and_select_peers(candidates, ticker, industry, market_cap, n)
                    if selected:
                        return selected, cache
        except Exception as e:
            print(f"  [FINVIZ] Screener failed ({e}), falling back to hardcoded peers...")

    # Fallback: hardcoded sector peer candidates
    candidates = SECTOR_PEER_CANDIDATES.get(sector, [])
    if not candidates:
        return [], {}

    return _score_and_select_peers(candidates, ticker, industry, market_cap, n)


def fetch_peer_metrics(peer_tickers, info_cache=None):
    if info_cache is None:
        info_cache = {}
    peers = []
    for ticker in peer_tickers:
        info = info_cache.get(ticker)
        if not info:
            info = _safe(lambda t=ticker: yf.Ticker(t).info, {})
        if not info:
            continue
        peers.append({
            "ticker": ticker,
            "company_name": info.get("shortName", ticker),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "roe": info.get("returnOnEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "peg": info.get("pegRatio"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
        })
    return peers


# ── SEC Filing Parsing (kept from original) ────────────────────────────────────
def find_latest_filing(base_path, ticker, filing_type):
    filing_dir = Path(base_path) / "sec-edgar-filings" / ticker / filing_type
    if not filing_dir.exists():
        return None
    accessions = sorted([d for d in filing_dir.iterdir() if d.is_dir()], reverse=True)
    if not accessions:
        return None
    latest_path = accessions[0] / "primary-document.html"
    return latest_path if latest_path.exists() else None


def extract_metrics(html_path):
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'lxml')
    metrics = {
        "Revenue": [r"Total [Nn]et [Ss]ales", r"Total [Rr]evenue", r"Net [Ss]ales"],
        "Net Income": [r"Net [Ii]ncome", r"Net [Ee]arnings"],
        "Total Assets": [r"Total [Aa]ssets"],
        "Total Liabilities": [r"Total [Ll]iabilities"],
    }
    results = {}
    tables = soup.find_all('table')
    for metric_name, patterns in metrics.items():
        found = False
        for table in tables:
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue
                first_cell_text = cells[0].get_text(strip=True)
                for pattern in patterns:
                    if re.search(pattern, first_cell_text):
                        for cell in cells[1:]:
                            text = cell.get_text(strip=True).replace('$', '').replace(',', '').replace('(', '-').replace(')', '')
                            try:
                                clean_val = re.sub(r'[^0-9.\\-]', '', text)
                                if clean_val:
                                    results[metric_name] = float(clean_val)
                                    found = True
                                    break
                            except ValueError:
                                continue
                        if found: break
                if found: break
            if found: break
        if not found:
            results[metric_name] = "Not Found"
    return results


# ── Helper to safely pull a row from yfinance DataFrames ───────────────────────
def _row(df, *labels):
    if df is None or df.empty:
        return pd.Series(dtype=float)
    for label in labels:
        if label in df.index:
            return df.loc[label].dropna()
    return pd.Series(dtype=float)


# ── Phase 1: Circle of Competence ──────────────────────────────────────────────
def phase1_competence_filter(data, text_10k=""):
    info = data.get("info", {})
    fin = data.get("financials", pd.DataFrame())

    sector = info.get("sector", "Unknown")
    industry = info.get("industry", "Unknown")
    summary = info.get("longBusinessSummary", "")

    industry_lower = industry.lower()
    is_complex = any(k in industry_lower for k in COMPLEX_INDUSTRIES)
    is_complex = is_complex or sector.lower() in COMPLEX_SECTORS
    
    # NLP Simplicity Check
    simplicity = "Moderate" # Default
    if text_10k and len(text_10k) > 5000:
        try:
            sentences = TextBlob(text_10k[:50000]).sentences
            avg_len = sum(len(s.words) for s in sentences) / max(1, len(sentences))
            if avg_len < 15:
                simplicity = "Simple"
            elif avg_len < 25:
                simplicity = "Moderate"
            else:
                simplicity = "Complex"
        except Exception:
            pass
    elif len(summary) < 600 and not is_complex:
         simplicity = "Simple"
    
    if is_complex:
        simplicity = "Complex"

    revenue = _row(fin, "Total Revenue", "Net Sales")
    cv_rev = _cv(revenue)
    earnings = _row(fin, "Net Income", "Net Income Common Stockholders")
    cv_earn = _cv(earnings)

    years = max(len(revenue), len(earnings))

    if cv_rev is not None and cv_rev < 0.10:
        predict = "High"
    elif cv_rev is not None and cv_rev < 0.20:
        predict = "Medium"
    elif cv_rev is not None:
        predict = "Low"
    else:
        predict = "N/A"

    neg_years = 0
    if not earnings.empty:
        neg_years = int((earnings < 0).sum())
    speculative = neg_years >= 2 or is_complex

    score = 0
    max_score = 10
    score += {"Simple": 3, "Moderate": 2, "Complex": 0}.get(simplicity, 1)
    score += {"High": 4, "Medium": 2, "Low": 0, "N/A": 0}.get(predict, 0)
    if not speculative:
        score += 3

    commentary = f"{sector} / {industry}. "
    commentary += f"Predictability: {predict}. "
    if speculative:
        commentary += "Flagged as potentially speculative."
    else:
        commentary += "Passes competence filter."

    return {
        "name": "Circle of Competence",
        "score": score, "max_score": max_score,
        "metrics": {
            "Business": summary[:200] + ("..." if len(summary) > 200 else ""),
            "Sector": sector,
            "Industry": industry,
            "Simplicity": simplicity,
            "Revenue Consistency (CV)": f"{cv_rev:.3f}" if cv_rev else "N/A",
            "Earnings Consistency (CV)": f"{cv_earn:.3f}" if cv_earn else "N/A",
            "Predictability": predict,
            "Speculative Flag": "Yes" if speculative else "No",
            "Years of Data": str(years),
        },
        "commentary": commentary,
    }


# ── Phase 2: Moat Analysis ────────────────────────────────────────────────────
def phase2_moat_analysis(data, text_10k="", finviz_data=None, enriched_news=None):
    info = data.get("info", {})
    fin = data.get("financials", pd.DataFrame())

    gross_margin = info.get("grossMargins")
    op_margin = info.get("operatingMargins")
    roe = info.get("returnOnEquity")
    market_cap = info.get("marketCap")

    gp = _row(fin, "Gross Profit")
    rev = _row(fin, "Total Revenue", "Net Sales")
    gm_series = (gp / rev).dropna() if not gp.empty and not rev.empty else pd.Series(dtype=float)
    gm_trend = _trend(gm_series)

    op_inc = _row(fin, "Operating Income")
    om_series = (op_inc / rev).dropna() if not op_inc.empty and not rev.empty else pd.Series(dtype=float)
    om_trend = _trend(om_series)

    rev_cagr = None
    if len(rev) >= 2:
        rev_cagr = _cagr(rev.iloc[-1], rev.iloc[0], len(rev) - 1)

    score = 0
    max_score = 10
    signals = []
    concerns = []

    # NLP Moat Scan (enhanced with count-based strength from qualitative.py)
    if text_10k:
        moat_kw = {
            "Network Effect": ["network effect", "ecosystem", "viral", "platform", "user base"],
            "Switching Costs": ["switching cost", "high retention", "locked in", "embedded", "integration", "high cost to change"],
            "Intangible": ["brand power", "patent", "trademark", "loyalty", "customer loyalty", "reputation"],
            "Cost Advantage": ["economies of scale", "low cost producer", "proprietary tech", "vertical integration"]
        }
        text_lower = text_10k.lower()
        for cat, kws in moat_kw.items():
            count = sum(text_lower.count(w) for w in kws)
            if count > 0:
                strength = "Strong" if count > 10 else "Potential"
                signals.append(f"{strength} {cat} ({count} mentions)")
                score += 2 if count > 10 else 1

    # News sentiment analysis (VADER via news_engine, TextBlob fallback)
    news_headlines = []
    if enriched_news:
        sentiments = [a["sentiment_compound"] for a in enriched_news if a.get("sentiment_compound") is not None]
        for a in enriched_news[:5]:
            news_headlines.append({
                "title": a.get("title", "")[:100],
                "date": str(a.get("date", ""))[:10],
                "sentiment": f"{a.get('sentiment_compound', 0):+.2f}",
            })
        if sentiments:
            avg_sentiment = sum(sentiments) / len(sentiments)
            if avg_sentiment > 0.05:
                signals.append(f"Positive news sentiment ({avg_sentiment:+.2f} avg VADER, {len(sentiments)} headlines)")
                score += 1
            elif avg_sentiment < -0.05:
                concerns.append(f"Negative news sentiment ({avg_sentiment:+.2f} avg VADER, {len(sentiments)} headlines)")
    else:
        # Fallback: FINVIZ data with TextBlob (original behavior)
        fv = finviz_data or {}
        fv_news = fv.get("news", pd.DataFrame())
        if fv_news is not None and not fv_news.empty:
            sentiments = []
            for _, row in fv_news.head(20).iterrows():
                title = str(row.get("Title", row.get("title", "")))
                if title and title != "nan":
                    blob = TextBlob(title)
                    sentiments.append(blob.sentiment.polarity)
                    if len(news_headlines) < 5:
                        news_headlines.append({
                            "title": title[:100],
                            "date": str(row.get("Date", row.get("date", "")))[:10],
                            "sentiment": f"{blob.sentiment.polarity:+.2f}",
                        })
            if sentiments:
                avg_sentiment = sum(sentiments) / len(sentiments)
                if avg_sentiment > 0.1:
                    signals.append(f"Positive news sentiment ({avg_sentiment:+.2f} avg, {len(sentiments)} headlines)")
                    score += 1
                elif avg_sentiment < -0.1:
                    concerns.append(f"Negative news sentiment ({avg_sentiment:+.2f} avg, {len(sentiments)} headlines)")

    if gross_margin and gross_margin > 0.40:
        score += 2
        signals.append(f"High gross margin ({_pct(gross_margin)}) suggests pricing power")
    elif gross_margin and gross_margin > 0.25:
        score += 1
        signals.append(f"Moderate gross margin ({_pct(gross_margin)})")
    else:
        concerns.append("Low gross margins may indicate weak pricing power")

    if gm_trend == "Expanding":
        score += 2
        signals.append("Gross margins expanding over time")
    elif gm_trend == "Stable":
        score += 1
    elif gm_trend == "Contracting":
        concerns.append("Gross margins contracting -- possible moat erosion")

    if op_margin and op_margin > 0.25:
        score += 2
        signals.append(f"Strong operating margin ({_pct(op_margin)})")
    elif op_margin and op_margin > 0.15:
        score += 1

    if rev_cagr and rev_cagr > 0.05:
        score += 2
        signals.append(f"Revenue CAGR {_pct(rev_cagr)} suggests durable demand")
    elif rev_cagr and rev_cagr > 0.0:
        score += 1

    if market_cap and market_cap > 500e9:
        score += 1
        signals.append("Dominant market position (mega-cap)")

    if roe and roe > 0.25:
        score += 1
        signals.append(f"High ROE ({_pct(roe)}) indicates efficient capital use")

    score = min(score, max_score)

    return {
        "name": "Moat Analysis",
        "score": score, "max_score": max_score,
        "metrics": {
            "Gross Margin": _pct(gross_margin),
            "Gross Margin Trend": gm_trend,
            "Operating Margin": _pct(op_margin),
            "Operating Margin Trend": om_trend,
            "Revenue CAGR": _pct(rev_cagr),
            "Return on Equity": _pct(roe),
            "Market Cap": _fmt_money(market_cap, billions=True),
        },
        "moat_signals": signals,
        "moat_concerns": concerns,
        "news_headlines": news_headlines,
        "gm_history": {str(k.year) if hasattr(k, 'year') else str(k): round(float(v) * 100, 1) for k, v in gm_series.items()} if not gm_series.empty else {},
        "om_history": {str(k.year) if hasattr(k, 'year') else str(k): round(float(v) * 100, 1) for k, v in om_series.items()} if not om_series.empty else {},
        "commentary": "Moat analysis requires qualitative judgment. The above are quantitative indicators only.",
    }


# ── Phase 3: Quantitative Vitals ──────────────────────────────────────────────
def phase3_quantitative_vitals(data, finviz_data=None):
    info = data.get("info", {})
    fin = data.get("financials", pd.DataFrame())
    bs = data.get("balance_sheet", pd.DataFrame())
    cf = data.get("cashflow", pd.DataFrame())

    op_income = _row(fin, "Operating Income")
    tax_prov = _row(fin, "Tax Provision")
    pretax = _row(fin, "Pretax Income")
    invested_cap = _row(bs, "Invested Capital")

    roic_history = {}
    roic_current = None
    if not op_income.empty and not tax_prov.empty and not pretax.empty and not invested_cap.empty:
        for col in op_income.index:
            if col in tax_prov.index and col in pretax.index and col in invested_cap.index:
                pt = pretax[col]
                if pt != 0:
                    tax_rate = tax_prov[col] / pt
                    nopat = op_income[col] * (1 - tax_rate)
                    ic = invested_cap[col]
                    if ic != 0:
                        r = nopat / ic
                        yr = str(col.year) if hasattr(col, 'year') else str(col)
                        roic_history[yr] = round(float(r) * 100, 1)
                        if roic_current is None:
                            roic_current = float(r)

    fcf_series = _row(cf, "Free Cash Flow")
    fcf_current = float(fcf_series.iloc[0]) if not fcf_series.empty else None
    market_cap = info.get("marketCap")
    fcf_yield = (fcf_current / market_cap) if fcf_current and market_cap else None

    fcf_history = {}
    for k, v in fcf_series.items():
        yr = str(k.year) if hasattr(k, 'year') else str(k)
        fcf_history[yr] = round(float(v) / 1e9, 2)

    total_debt = info.get("totalDebt")
    ebitda = info.get("ebitda")
    debt_ebitda = (total_debt / ebitda) if total_debt and ebitda and ebitda != 0 else None

    gp = _row(fin, "Gross Profit")
    rev = _row(fin, "Total Revenue", "Net Sales")
    gm_series = (gp / rev).dropna() if not gp.empty and not rev.empty else pd.Series(dtype=float)
    op_inc = _row(fin, "Operating Income")
    om_series = (op_inc / rev).dropna() if not op_inc.empty and not rev.empty else pd.Series(dtype=float)
    margin_trend = _trend(om_series)

    gm_current = float(gm_series.iloc[0]) if not gm_series.empty else None
    om_current = float(om_series.iloc[0]) if not om_series.empty else None

    # FINVIZ fundamental cross-check / gap filling
    data_source_notes = []
    fv = finviz_data or {}
    fundament = fv.get("fundament", {})

    if not info.get("trailingPE") and fundament.get("P/E"):
        try:
            pe_val = str(fundament["P/E"]).replace(",", "")
            if pe_val != "-":
                info["trailingPE"] = float(pe_val)
                data_source_notes.append("P/E from FINVIZ")
        except (ValueError, TypeError):
            pass

    if not info.get("returnOnEquity") and fundament.get("ROE"):
        try:
            roe_str = str(fundament["ROE"]).replace("%", "")
            if roe_str != "-":
                info["returnOnEquity"] = float(roe_str) / 100
                data_source_notes.append("ROE from FINVIZ")
        except (ValueError, TypeError):
            pass

    if fundament.get("Debt/Eq"):
        try:
            de_val = str(fundament["Debt/Eq"])
            if de_val != "-":
                data_source_notes.append(f"FINVIZ Debt/Eq: {de_val}")
        except Exception:
            pass

    score = 0
    max_score = 20

    if roic_current:
        if roic_current > 0.20:
            score += 7
        elif roic_current > 0.15:
            score += 5
        elif roic_current > 0.10:
            score += 3

    if fcf_yield:
        if fcf_yield > 0.05:
            score += 5
        elif fcf_yield > 0.03:
            score += 3
        elif fcf_yield > 0.01:
            score += 1

    if debt_ebitda is not None:
        if debt_ebitda < 1.0:
            score += 5
        elif debt_ebitda < 3.0:
            score += 4
        elif debt_ebitda < 5.0:
            score += 2

    if margin_trend == "Expanding":
        score += 3
    elif margin_trend == "Stable":
        score += 1

    score = min(score, max_score)

    return {
        "name": "Quantitative Vitals",
        "score": score, "max_score": max_score,
        "metrics": {
            "ROIC (Current)": _pct(roic_current),
            "ROIC Target (>15%)": "Met" if roic_current and roic_current > 0.15 else "Not Met",
            "FCF Yield": _pct(fcf_yield),
            "Free Cash Flow": _fmt_money(fcf_current, billions=True),
            "Debt/EBITDA": f"{debt_ebitda:.2f}" if debt_ebitda is not None else "N/A",
            "Debt/EBITDA Safe (<3.0)": "Yes" if debt_ebitda is not None and debt_ebitda < 3.0 else ("No" if debt_ebitda else "N/A"),
            "Gross Margin": _pct(gm_current),
            "Operating Margin": _pct(om_current),
            "Margin Trend": margin_trend,
            "Data Sources": "; ".join(data_source_notes) if data_source_notes else "All from Yahoo Finance",
        },
        "roic_history": roic_history,
        "fcf_history": fcf_history,
        "commentary": f"ROIC {'exceeds' if roic_current and roic_current > 0.15 else 'below'} 15% target. Debt/EBITDA {'healthy' if debt_ebitda and debt_ebitda < 3.0 else 'elevated or unavailable'}.",
    }


# ── Phase 4: Management & Capital Allocation ──────────────────────────────────
def phase4_management(data, text_10k="", finviz_data=None):
    info = data.get("info", {})
    bs = data.get("balance_sheet", pd.DataFrame())
    cf = data.get("cashflow", pd.DataFrame())

    # Sentiment Analysis
    sentiment_label = "Neutral/No Text"
    if text_10k:
        pol, subj = analyze_sentiment(text_10k[:50000])
        if pol > 0.12:
            score_boost = 1
            sentiment_label = f"Optimistic (Polarity: {pol:.2f})"
        elif pol < 0.02:
             score_boost = 0
             sentiment_label = f"Cautious (Polarity: {pol:.2f})"
        else:
             score_boost = 0
             sentiment_label = f"Neutral (Polarity: {pol:.2f})"
    else:
        score_boost = 0

    insider_pct = info.get("heldPercentInsiders")
    inst_pct = info.get("heldPercentInstitutions")

    shares = _row(bs, "Ordinary Shares Number", "Share Issued")
    share_history = {}
    for k, v in shares.items():
        yr = str(k.year) if hasattr(k, 'year') else str(k)
        share_history[yr] = round(float(v) / 1e9, 2)

    if len(shares) >= 2:
        change = (shares.iloc[0] - shares.iloc[-1]) / shares.iloc[-1]
        if change < -0.02:
            share_trend = "Declining (Buybacks)"
        elif change > 0.02:
            share_trend = "Increasing (Dilution)"
        else:
            share_trend = "Stable"
    else:
        share_trend = "Insufficient Data"

    buybacks = _row(cf, "Repurchase Of Capital Stock")
    buyback_total = abs(float(buybacks.sum())) if not buybacks.empty else None

    # Insider activity — FINVIZ enhanced
    insider_activity = "No recent data"
    insider_buys = 0
    insider_sells = 0
    insider_trades_display = []
    fv = finviz_data or {}
    fv_insiders = fv.get("insiders", pd.DataFrame())

    if fv_insiders is not None and not fv_insiders.empty:
        for _, row in fv_insiders.iterrows():
            txn = str(row.get("Transaction", "")).lower()
            if "buy" in txn or "purchase" in txn:
                insider_buys += 1
            elif "sale" in txn or "sell" in txn:
                insider_sells += 1
        total_txn = insider_buys + insider_sells
        if total_txn > 0:
            buy_ratio = insider_buys / total_txn
            if buy_ratio > 0.60:
                insider_activity = f"Net Buying (bullish) — {insider_buys} buys vs {insider_sells} sells"
            elif buy_ratio < 0.40:
                insider_activity = f"Net Selling (cautious) — {insider_buys} buys vs {insider_sells} sells"
            else:
                insider_activity = f"Mixed — {insider_buys} buys, {insider_sells} sells"
        else:
            insider_activity = f"{len(fv_insiders)} trades (no buy/sell classification)"
        # Collect last 5 trades for display
        for _, row in fv_insiders.head(5).iterrows():
            insider_trades_display.append({
                "name": str(row.get("Insider Trading", ""))[:25],
                "date": str(row.get("Date", "")),
                "type": str(row.get("Transaction", "")),
                "value": str(row.get("Value ($)", "")),
            })
    else:
        # Fallback to yfinance
        ip = data.get("insider_purchases", pd.DataFrame())
        if ip is not None and not ip.empty and "Shares" in ip.columns:
            insider_activity = "See report for details (yfinance)"

    divs = _row(cf, "Common Stock Dividend Paid", "Cash Dividends Paid")
    div_total = abs(float(divs.sum())) if not divs.empty else 0

    fcf_series = _row(cf, "Free Cash Flow")
    fcf_total = float(fcf_series.sum()) if not fcf_series.empty else None
    capital_return = ((buyback_total or 0) + div_total) / fcf_total if fcf_total and fcf_total > 0 else None

    score = 0
    max_score = 10

    if insider_pct:
        if insider_pct > 0.05:
            score += 3
        elif insider_pct > 0.01:
            score += 2
        else:
            score += 1

    if share_trend == "Declining (Buybacks)":
        score += 3
    elif share_trend == "Stable":
        score += 1
    elif share_trend == "Increasing (Dilution)":
        score -= 1

    if capital_return and capital_return > 0.5:
        score += 2
    elif capital_return and capital_return > 0.2:
        score += 1

    score += 1  # baseline for having data
    score += score_boost

    # FINVIZ insider trade scoring
    if insider_buys + insider_sells > 0:
        buy_ratio = insider_buys / (insider_buys + insider_sells)
        if buy_ratio > 0.60:
            score += 2
        elif buy_ratio < 0.40:
            score -= 1

    score = max(0, min(score, max_score))

    return {
        "name": "Management & Capital Allocation",
        "score": score, "max_score": max_score,
        "metrics": {
            "Insider Ownership": _pct(insider_pct),
            "Institutional Ownership": _pct(inst_pct),
            "Share Count Trend": share_trend,
            "Buybacks (Total)": _fmt_money(buyback_total, billions=True),
            "Dividends (Total)": _fmt_money(div_total, billions=True),
            "Capital Return / FCF": f"{capital_return:.1%}" if capital_return else "N/A",
            "Net Insider Activity": insider_activity,
            "Management Sentiment": sentiment_label,
        },
        "share_history": share_history,
        "insider_trades": insider_trades_display,
        "commentary": f"Share trend: {share_trend}. {'Strong' if capital_return and capital_return > 0.5 else 'Moderate'} capital return to shareholders.",
    }


# ── Phase 5: Valuation & Margin of Safety ─────────────────────────────────────

def _get_analyst_growth(data):
    """Extract analyst consensus growth rate from yfinance growth_estimates."""
    ge = data.get("growth_estimates", pd.DataFrame())
    if ge is None or ge.empty:
        return None

    # yfinance returns "stockTrend" column (not "Stock")
    for col_name in ["stockTrend", "Stock", "stock"]:
        if col_name in ge.columns:
            val = ge[col_name].dropna()
            for v in val:
                if isinstance(v, (int, float)) and not np.isnan(v):
                    return float(v)

    # Fallback: try first column
    if len(ge.columns) > 0:
        col = ge.columns[0]
        val = ge[col].dropna()
        for v in val:
            if isinstance(v, (int, float)) and not np.isnan(v):
                return float(v)

    return None


def _get_discount_rate(sector, beta=None):
    """Get discount rate using CAPM with beta when available, sector fallback otherwise.
    CAPM: Cost of Equity = Risk-Free Rate + Beta * Equity Risk Premium
    Inspired by metrics.py WACC calculation."""
    if beta is not None and isinstance(beta, (int, float)) and beta > 0:
        equity_risk_premium = 0.055  # long-term average ERP
        capm_rate = RISK_FREE_RATE + beta * equity_risk_premium
        # Clamp to reasonable range (6%-14%)
        return max(0.06, min(capm_rate, 0.14))
    return SECTOR_DISCOUNT_RATES.get(sector, DEFAULT_DISCOUNT_RATE)


def _calculate_dcf(data):
    """Two-stage DCF using normalized FCF, analyst growth, and sector discount rate."""
    info = data.get("info", {})
    cf = data.get("cashflow", pd.DataFrame())

    fcf_series = _row(cf, "Free Cash Flow")
    if fcf_series.empty:
        return None, {}

    shares = info.get("sharesOutstanding")
    total_debt = info.get("totalDebt", 0) or 0
    cash = info.get("totalCash", 0) or 0

    if not shares or shares == 0:
        return None, {}

    # Normalized FCF: use weighted average (recent years weighted more)
    fcf_vals = [float(v) for v in fcf_series.values if not np.isnan(v)]
    if len(fcf_vals) >= 3:
        # Weight: most recent 50%, second 30%, rest 20%
        weights = [0.50, 0.30] + [0.20 / max(len(fcf_vals) - 2, 1)] * (len(fcf_vals) - 2)
        weights = weights[:len(fcf_vals)]
        w_sum = sum(weights)
        base_fcf = sum(f * w for f, w in zip(fcf_vals, weights)) / w_sum
    elif len(fcf_vals) == 2:
        base_fcf = fcf_vals[0] * 0.6 + fcf_vals[1] * 0.4
    else:
        base_fcf = fcf_vals[0]

    # Get analyst growth rate
    analyst_growth = _get_analyst_growth(data)
    growth_source = "Analyst Consensus"

    if analyst_growth is not None:
        growth_rate = analyst_growth
    else:
        # Fallback: compute from historical revenue CAGR
        fin = data.get("financials", pd.DataFrame())
        rev = _row(fin, "Total Revenue", "Net Sales")
        if len(rev) >= 2:
            growth_rate = _cagr(rev.iloc[-1], rev.iloc[0], len(rev) - 1)
            if growth_rate is None:
                growth_rate = 0.06
            growth_source = "Historical Revenue CAGR"
        else:
            growth_rate = 0.06
            growth_source = "Default (no data)"

    # Clamp growth to reasonable bounds
    growth_rate = max(0.02, min(growth_rate, 0.25))
    # Stage 2: growth decelerates toward GDP-like rate
    stage2_growth = max(TERMINAL_GROWTH + 0.01, min(growth_rate * 0.5, 0.08))

    # CAPM/beta discount rate with sector fallback
    sector = info.get("sector", "")
    beta = info.get("beta")
    discount_rate = _get_discount_rate(sector, beta)

    assumptions = {
        "Base FCF (Normalized)": _fmt_money(base_fcf, billions=True),
        "FCF Years Averaged": str(len(fcf_vals)),
        "Growth Source": growth_source,
        "Stage 1 Growth (yr 1-5)": _pct(growth_rate),
        "Stage 2 Growth (yr 6-10)": _pct(stage2_growth),
        "Terminal Growth": _pct(TERMINAL_GROWTH),
        "Discount Rate": f"{discount_rate*100:.1f}% (CAPM, beta={beta:.2f})" if isinstance(beta, (int, float)) and beta > 0 else f"{discount_rate*100:.1f}% ({sector} sector)",
        "Net Debt": _fmt_money(total_debt - cash, billions=True),
        "Shares Outstanding": f"{shares / 1e9:.2f}B",
    }

    dcf_total = 0
    fcf = base_fcf
    for yr in range(1, 11):
        g = growth_rate if yr <= 5 else stage2_growth
        fcf *= (1 + g)
        dcf_total += fcf / (1 + discount_rate) ** yr

    if discount_rate <= TERMINAL_GROWTH:
        return None, {}
    terminal_val = fcf * (1 + TERMINAL_GROWTH) / (discount_rate - TERMINAL_GROWTH)
    dcf_total += terminal_val / (1 + discount_rate) ** 10

    equity_value = dcf_total - (total_debt - cash)
    intrinsic = equity_value / shares

    return max(0, intrinsic), assumptions


def _calculate_relative_valuation(data, peer_data):
    """Relative valuation using peer median P/E and forward P/E applied to target's earnings."""
    info = data.get("info", {})
    eps_trailing = info.get("trailingEps")
    eps_forward = _safe(lambda: info.get("forwardEps"))

    if not peer_data:
        return None, {}

    # Get peer P/E medians
    peer_trailing_pes = [p.get("trailing_pe") for p in peer_data if p.get("trailing_pe") and p["trailing_pe"] > 0]
    peer_forward_pes = [p.get("forward_pe") for p in peer_data if p.get("forward_pe") and p["forward_pe"] > 0]

    results = {}
    values = []

    if peer_trailing_pes and eps_trailing and eps_trailing > 0:
        median_pe = float(np.median(peer_trailing_pes))
        rel_val_trailing = eps_trailing * median_pe
        results["Peer Median P/E"] = f"{median_pe:.1f}"
        results["EPS (Trailing)"] = f"${eps_trailing:.2f}"
        results["Relative Value (Trailing)"] = f"${rel_val_trailing:,.0f}"
        values.append(rel_val_trailing)

    if peer_forward_pes and eps_forward and eps_forward > 0:
        median_fpe = float(np.median(peer_forward_pes))
        rel_val_forward = eps_forward * median_fpe
        results["Peer Median Fwd P/E"] = f"{median_fpe:.1f}"
        results["EPS (Forward)"] = f"${eps_forward:.2f}"
        results["Relative Value (Forward)"] = f"${rel_val_forward:,.0f}"
        values.append(rel_val_forward)

    if not values:
        return None, results

    # Average of trailing and forward relative valuations
    rel_fair_value = sum(values) / len(values)
    results["Relative Fair Value"] = f"${rel_fair_value:,.0f}"
    return rel_fair_value, results


def _calculate_earnings_power_value(data):
    """Earnings Power Value: normalized earnings / cost of equity. No-growth valuation floor."""
    info = data.get("info", {})
    fin = data.get("financials", pd.DataFrame())

    # Use average operating income over available years, after tax
    op_income = _row(fin, "Operating Income")
    tax_prov = _row(fin, "Tax Provision")
    pretax = _row(fin, "Pretax Income")

    if op_income.empty:
        return None, {}

    # Calculate effective tax rate
    tax_rate = 0.21  # default corporate rate
    if not tax_prov.empty and not pretax.empty:
        valid_taxes = []
        for col in tax_prov.index:
            if col in pretax.index and pretax[col] != 0:
                rate = tax_prov[col] / pretax[col]
                if 0.05 < rate < 0.50:
                    valid_taxes.append(rate)
        if valid_taxes:
            tax_rate = sum(valid_taxes) / len(valid_taxes)

    # Normalized after-tax operating income
    op_vals = [float(v) for v in op_income.values if not np.isnan(v)]
    if not op_vals:
        return None, {}

    # Weighted average (recent years weighted more)
    if len(op_vals) >= 3:
        weights = [0.50, 0.30] + [0.20 / max(len(op_vals) - 2, 1)] * (len(op_vals) - 2)
        weights = weights[:len(op_vals)]
        w_sum = sum(weights)
        normalized_op = sum(f * w for f, w in zip(op_vals, weights)) / w_sum
    else:
        normalized_op = sum(op_vals) / len(op_vals)

    nopat = normalized_op * (1 - tax_rate)

    # Maintenance capex (use depreciation as proxy)
    dep = _row(fin, "Depreciation And Amortization In Income Statement",
               "Depreciation And Amortization", "Depreciation Amortization Depletion")
    maint_capex = abs(float(dep.iloc[0])) if not dep.empty else 0

    earnings_power = nopat - maint_capex

    sector = info.get("sector", "")
    beta = info.get("beta")
    discount_rate = _get_discount_rate(sector, beta)

    shares = info.get("sharesOutstanding")
    total_debt = info.get("totalDebt", 0) or 0
    cash = info.get("totalCash", 0) or 0

    if not shares or shares == 0 or discount_rate == 0:
        return None, {}

    enterprise_epv = earnings_power / discount_rate
    equity_epv = enterprise_epv - (total_debt - cash)
    epv_per_share = equity_epv / shares

    results = {
        "Normalized NOPAT": _fmt_money(nopat, billions=True),
        "Maintenance CapEx": _fmt_money(maint_capex, billions=True),
        "Earnings Power": _fmt_money(earnings_power, billions=True),
        "Effective Tax Rate": _pct(tax_rate),
        "EPV / Share": f"${max(0, epv_per_share):,.0f}",
    }

    return max(0, epv_per_share), results


def _get_analyst_target(data, finviz_data=None):
    """Extract analyst consensus price target. FINVIZ as fallback."""
    apt = data.get("analyst_price_targets")
    if apt and isinstance(apt, dict):
        target = apt.get("mean") or apt.get("current")
        if target:
            return target
    elif apt is not None and hasattr(apt, 'get'):
        target = _safe(lambda: apt.get("mean"))
        if target:
            return target

    # FINVIZ fallback
    fv = finviz_data or {}
    fundament = fv.get("fundament", {})
    fv_target = fundament.get("Target Price")
    if fv_target:
        try:
            return float(fv_target)
        except (ValueError, TypeError):
            pass
    return None


def _blend_valuations(dcf_value, relative_value, epv_value, analyst_target):
    """
    Blend multiple valuation methods into a composite fair value.
    Weights: DCF 40%, Relative 25%, EPV 15%, Analyst 20%.
    Only uses methods that produced a value.
    """
    methods = []

    if dcf_value and dcf_value > 0:
        methods.append(("DCF", dcf_value, 0.40))
    if relative_value and relative_value > 0:
        methods.append(("Relative", relative_value, 0.25))
    if epv_value and epv_value > 0:
        methods.append(("EPV", epv_value, 0.15))
    if analyst_target and analyst_target > 0:
        methods.append(("Analyst", analyst_target, 0.20))

    if not methods:
        return None, {}

    # Normalize weights to sum to 1.0
    total_weight = sum(w for _, _, w in methods)
    composite = sum(v * w / total_weight for _, v, w in methods)

    breakdown = {}
    for name, val, w in methods:
        adj_w = w / total_weight
        breakdown[name] = {"value": val, "weight": adj_w}

    return composite, breakdown


def phase5_valuation(data, peer_data=None, finviz_data=None):
    info = data.get("info", {})
    price = info.get("currentPrice") or info.get("regularMarketPrice")

    # Method 1: DCF
    dcf_value, dcf_assumptions = _calculate_dcf(data)

    # Method 2: Relative valuation (needs peer data)
    relative_value, relative_details = _calculate_relative_valuation(data, peer_data or [])

    # Method 3: Earnings Power Value
    epv_value, epv_details = _calculate_earnings_power_value(data)

    # Method 4: Analyst consensus target
    analyst_target = _get_analyst_target(data, finviz_data)

    # FINVIZ analyst consensus distribution
    analyst_consensus = {}
    fv = finviz_data or {}
    fv_ratings = fv.get("ratings", pd.DataFrame())
    if fv_ratings is not None and not fv_ratings.empty:
        rating_counts = {}
        # Columns: Date, Status, Outer, Rating, Price
        rating_col = "Rating" if "Rating" in fv_ratings.columns else fv_ratings.columns[3] if len(fv_ratings.columns) > 3 else None
        if rating_col:
            for _, row in fv_ratings.iterrows():
                rating_str = str(row.get(rating_col, "")).lower()
                # Handle "Hold → Buy" format: take the target rating (after →)
                if "→" in rating_str or "->" in rating_str:
                    rating_str = rating_str.split("→")[-1].split("->")[-1].strip()
                if "buy" in rating_str or "outperform" in rating_str or "overweight" in rating_str:
                    rating_counts["Buy"] = rating_counts.get("Buy", 0) + 1
                elif "sell" in rating_str or "underperform" in rating_str or "underweight" in rating_str:
                    rating_counts["Sell"] = rating_counts.get("Sell", 0) + 1
                elif "hold" in rating_str or "neutral" in rating_str or "perform" in rating_str:
                    rating_counts["Hold"] = rating_counts.get("Hold", 0) + 1
        analyst_consensus = {k: v for k, v in rating_counts.items() if v > 0}

    # Blend all methods
    composite_value, blend_breakdown = _blend_valuations(dcf_value, relative_value, epv_value, analyst_target)

    # Use composite as the intrinsic value
    intrinsic = composite_value

    margin_of_safety = None
    if intrinsic and price:
        margin_of_safety = (intrinsic - price) / intrinsic

    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    peg = info.get("pegRatio")

    analyst_upside = None
    if analyst_target and price:
        analyst_upside = (analyst_target - price) / price

    score = 0
    max_score = 10

    if margin_of_safety is not None:
        if margin_of_safety > 0.30:
            score += 5
        elif margin_of_safety > 0.15:
            score += 3
        elif margin_of_safety > 0:
            score += 1

    if peg is not None:
        if peg < 1.0:
            score += 3
        elif peg < 1.5:
            score += 2
        elif peg < 2.0:
            score += 1

    if analyst_upside and analyst_upside > 0.20:
        score += 2
    elif analyst_upside and analyst_upside > 0.10:
        score += 1

    score = min(score, max_score)

    mos_met = margin_of_safety is not None and margin_of_safety >= MARGIN_OF_SAFETY_TARGET

    # Build valuation method summary for display
    method_summary = {}
    if dcf_value:
        method_summary["DCF Fair Value"] = f"${dcf_value:,.0f}"
    if relative_value:
        method_summary["Relative Fair Value"] = f"${relative_value:,.0f}"
    if epv_value:
        method_summary["Earnings Power Value"] = f"${epv_value:,.0f}"
    if analyst_target:
        method_summary["Analyst Target (Mean)"] = f"${analyst_target:,.0f}"

    metrics = {}
    metrics["Composite Fair Value"] = f"${intrinsic:,.0f}" if intrinsic else "N/A"
    metrics.update(method_summary)
    metrics["Current Price"] = f"${price:,.2f}" if price else "N/A"
    metrics["Margin of Safety"] = _pct(margin_of_safety)
    metrics["30% Margin Met"] = "Yes" if mos_met else "No"
    metrics["Trailing P/E"] = f"{trailing_pe:.1f}" if trailing_pe else "N/A"
    metrics["Forward P/E"] = f"{forward_pe:.1f}" if forward_pe else "N/A"
    metrics["PEG Ratio"] = f"{peg:.2f}" if peg else "N/A"
    metrics["Analyst Upside"] = _pct(analyst_upside)
    if analyst_consensus:
        consensus_str = ", ".join(f"{k}: {v}" for k, v in analyst_consensus.items())
        metrics["Analyst Consensus (FINVIZ)"] = consensus_str

    # Build blend weights display
    blend_display = {}
    for method_name, bd in blend_breakdown.items():
        blend_display[f"{method_name} (weight {bd['weight']:.0%})"] = f"${bd['value']:,.0f}"

    commentary = f"{'Adequate' if mos_met else 'Insufficient'} margin of safety. "
    commentary += f"Composite blends {len(blend_breakdown)} valuation methods. "
    commentary += f"PEG {'attractive' if peg and peg < 1.5 else 'elevated or unavailable'}."

    return {
        "name": "Valuation & Margin of Safety",
        "score": score, "max_score": max_score,
        "metrics": metrics,
        "dcf_assumptions": dcf_assumptions,
        "relative_details": relative_details,
        "epv_details": epv_details,
        "blend_breakdown": blend_display,
        "margin_of_safety_met": mos_met,
        "raw_intrinsic": intrinsic,
        "raw_price": price,
        "raw_dcf": dcf_value,
        "raw_relative": relative_value,
        "raw_epv": epv_value,
        "raw_analyst": analyst_target,
        "analyst_consensus": analyst_consensus,
        "commentary": commentary,
    }


# ── Phase 6: Sector Comparison ────────────────────────────────────────────────
def phase6_sector_comparison(data, peer_data):
    info = data.get("info", {})
    if not peer_data or len(peer_data) < 2:
        return None

    target = {
        "ticker": data.get("ticker", ""),
        "company_name": info.get("shortName", data.get("ticker", "")),
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "gross_margin": info.get("grossMargins"),
        "operating_margin": info.get("operatingMargins"),
        "roe": info.get("returnOnEquity"),
        "revenue_growth": info.get("revenueGrowth"),
        "peg": info.get("pegRatio"),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "is_target": True,
    }

    all_companies = [target] + [{**p, "is_target": False} for p in peer_data]

    # Compute rankings and medians
    # For each metric: define whether higher or lower is better
    metric_config = {
        "trailing_pe": {"label": "P/E Ratio", "lower_better": True, "fmt": ".1f"},
        "forward_pe": {"label": "Forward P/E", "lower_better": True, "fmt": ".1f"},
        "gross_margin": {"label": "Gross Margin", "lower_better": False, "fmt": ".1%"},
        "operating_margin": {"label": "Op. Margin", "lower_better": False, "fmt": ".1%"},
        "roe": {"label": "ROE", "lower_better": False, "fmt": ".1%"},
        "revenue_growth": {"label": "Rev. Growth", "lower_better": False, "fmt": ".1%"},
        "peg": {"label": "PEG", "lower_better": True, "fmt": ".2f"},
    }

    rankings = {}
    peer_medians = {}
    commentary_parts = []

    for metric_key, config in metric_config.items():
        # Get values for peers only (exclude target) for median
        peer_vals = [p.get(metric_key) for p in peer_data if p.get(metric_key) is not None]
        target_val = target.get(metric_key)

        if not peer_vals or target_val is None:
            continue

        median = float(np.median(peer_vals))
        peer_medians[config["label"]] = median

        # Rank (include target in the ranking)
        all_vals = [(c.get("ticker", "?"), c.get(metric_key)) for c in all_companies if c.get(metric_key) is not None]
        if config["lower_better"]:
            all_vals.sort(key=lambda x: x[1])
        else:
            all_vals.sort(key=lambda x: -x[1])

        rank = next((i + 1 for i, (t, _) in enumerate(all_vals) if t == target["ticker"]), None)
        total = len(all_vals)

        if rank:
            rankings[config["label"]] = {"rank": rank, "of": total, "rank1_is_best": True}

            # Commentary for notable rankings
            if median != 0:
                diff_pct = (target_val - median) / abs(median) * 100
                direction = "above" if diff_pct > 0 else "below"
                if abs(diff_pct) > 10:
                    fmt = config["fmt"]
                    t_formatted = f"{target_val:{fmt}}"
                    m_formatted = f"{median:{fmt}}"
                    commentary_parts.append(
                        f"{config['label']}: {t_formatted} ({abs(diff_pct):.0f}% {direction} sector median {m_formatted}, rank {rank}/{total})"
                    )

    return {
        "name": "Sector Comparison",
        "peer_table": all_companies,
        "rankings": rankings,
        "peer_medians": peer_medians,
        "commentary": commentary_parts,
        "peer_tickers": [p["ticker"] for p in peer_data],
        "sector": info.get("sector", ""),
        "peer_count": len(peer_data),
    }


# ── Strategy Engine ───────────────────────────────────────────────────────────
def compute_strategy(phases, sector_comparison=None):
    total = sum(p["score"] for p in phases)
    max_total = sum(p["max_score"] for p in phases)
    pct = total / max_total if max_total > 0 else 0

    # Separate fundamentals (phases 1-4) from valuation (phase 5)
    fund_score = sum(p["score"] for p in phases[:4])
    fund_max = sum(p["max_score"] for p in phases[:4])
    fund_pct = fund_score / fund_max if fund_max > 0 else 0

    val_score = phases[4]["score"]
    val_max = phases[4]["max_score"]
    val_pct = val_score / val_max if val_max > 0 else 0

    # Extract raw price data from phase 5
    intrinsic = phases[4].get("raw_intrinsic")
    price = phases[4].get("raw_price")
    buy_below = intrinsic * (1 - MARGIN_OF_SAFETY_TARGET) if intrinsic else None

    premium_discount = None
    if intrinsic and price and intrinsic > 0:
        premium_discount = (price - intrinsic) / intrinsic

    target_prices = {
        "fair_value": intrinsic,
        "buy_below": buy_below,
        "current_price": price,
        "premium_discount_pct": premium_discount,
    }

    # Collect bull/bear signals
    bull_points = []
    bear_points = []
    for p in phases:
        if p["score"] >= p["max_score"] * 0.7:
            bull_points.append(f"{p['name']}: {p['commentary']}")
        elif p["score"] < p["max_score"] * 0.4:
            bear_points.append(f"{p['name']}: {p['commentary']}")
        if "moat_signals" in p:
            bull_points.extend(p["moat_signals"][:3])
        if "moat_concerns" in p:
            bear_points.extend(p["moat_concerns"][:3])

    # Strategy matrix: fundamentals_pct vs val_pct
    speculative = any(p.get("metrics", {}).get("Speculative Flag") == "Yes" for p in phases)

    if fund_pct >= 0.70 and val_pct >= 0.60:
        strategy_label = "STRONG BUY"
        verdict = "BUY"
        strategy_detail = "Excellent fundamentals with attractive valuation."
        action_items = ["Consider initiating a position at current price levels."]
    elif fund_pct >= 0.70 and val_pct >= 0.30:
        strategy_label = "QUALITY HOLD"
        verdict = "BUY"
        if buy_below and price:
            discount_needed = ((price - buy_below) / price) * 100
            strategy_detail = f"Excellent company trading above ideal entry. Consider buying on a {discount_needed:.0f}% pullback to ${buy_below:,.0f}."
            action_items = [f"Set price alert at ${buy_below:,.0f}.", "Acceptable to build a small starter position."]
        else:
            strategy_detail = "Excellent company but valuation is moderately stretched."
            action_items = ["Monitor for better entry point."]
    elif fund_pct >= 0.70 and val_pct < 0.30:
        strategy_label = "WATCHLIST - OVERVALUED"
        verdict = "WATCHLIST"
        if premium_discount is not None and buy_below:
            strategy_detail = f"Outstanding business trading at {premium_discount * 100:.0f}% premium to fair value. Wait for entry below ${buy_below:,.0f}."
            action_items = [f"Set price alert at ${buy_below:,.0f}.", "Do not chase -- quality is priced in."]
        else:
            strategy_detail = "Outstanding business but significantly overvalued."
            action_items = ["Monitor valuation for improvement."]
    elif fund_pct >= 0.45 and val_pct >= 0.60:
        strategy_label = "VALUE OPPORTUNITY"
        verdict = "BUY"
        strategy_detail = "Decent fundamentals at attractive price. Verify improving trends before committing."
        action_items = ["Research recent quarterly trends.", "Consider a small position with stop-loss."]
    elif fund_pct >= 0.45 and val_pct >= 0.30:
        strategy_label = "HOLD - MIXED"
        verdict = "WATCHLIST"
        weak = [p["name"] for p in phases[:4] if p["score"] < p["max_score"] * 0.5]
        strategy_detail = f"Moderate business quality with fair valuation. Watch for improvement in: {', '.join(weak) if weak else 'overall fundamentals'}."
        action_items = ["Not compelling enough for new money.", "Hold if already owned; monitor quarterly."]
    elif fund_pct >= 0.45 and val_pct < 0.30:
        strategy_label = "WATCHLIST - WEAK VALUE"
        verdict = "WATCHLIST"
        weak = [p["name"] for p in phases[:4] if p["score"] < p["max_score"] * 0.5]
        if premium_discount is not None:
            strategy_detail = f"Moderate fundamentals and {premium_discount * 100:.0f}% premium to fair value. Needs significant price correction."
        else:
            strategy_detail = "Moderate fundamentals and overvalued. Needs both fundamental and valuation improvement."
        action_items = ["Avoid new positions.", "Revisit if price drops significantly or fundamentals improve."]
    elif fund_pct < 0.45 and val_pct >= 0.60:
        strategy_label = "SPECULATIVE VALUE"
        verdict = "WATCHLIST"
        strategy_detail = "Weak fundamentals but cheap valuation. High risk -- only for contrarian investors."
        action_items = ["Deep dive into turnaround potential.", "Small position only if thesis is strong."]
    elif fund_pct < 0.45 and val_pct >= 0.30:
        strategy_label = "AVOID - WEAK"
        verdict = "AVOID"
        weak = [p["name"] for p in phases[:4] if p["score"] < p["max_score"] * 0.4]
        strategy_detail = f"Fundamental weaknesses in: {', '.join(weak) if weak else 'multiple areas'}. Not compelling at current valuation."
        action_items = ["Look elsewhere in the sector for better quality."]
    else:
        strategy_label = "AVOID"
        verdict = "AVOID"
        weak = [p["name"] for p in phases[:4] if p["score"] < p["max_score"] * 0.4]
        strategy_detail = f"Weak fundamentals and overvalued. Issues: {', '.join(weak) if weak else 'multiple areas'}."
        action_items = ["Do not invest.", "Sector peers likely offer better risk/reward."]

    # Speculative override
    if speculative and verdict == "BUY":
        verdict = "WATCHLIST"
        strategy_label = "WATCHLIST - SPECULATIVE"
        bear_points.append("Downgraded: flagged as speculative")

    # Add sector context to strategy detail
    if sector_comparison and sector_comparison.get("commentary"):
        sector_context = " | ".join(sector_comparison["commentary"][:2])
    else:
        sector_context = None

    if not bull_points:
        bull_points.append("Limited positive signals identified from available data.")
    if not bear_points:
        bear_points.append("No major concerns identified from available data.")

    return {
        "total_score": total,
        "max_score": max_total,
        "percentage": pct,
        "fundamentals_pct": fund_pct,
        "valuation_pct": val_pct,
        "verdict": verdict,
        "strategy_label": strategy_label,
        "strategy_detail": strategy_detail,
        "action_items": action_items,
        "target_prices": target_prices,
        "sector_context": sector_context,
        "bull_case": bull_points,
        "bear_case": bear_points,
    }


# ── HTML Report Generation ────────────────────────────────────────────────────
def _render_score_bar(score, max_score):
    pct = (score / max_score * 100) if max_score > 0 else 0
    if pct >= 70:
        color = "#28a745"
    elif pct >= 45:
        color = "#ffc107"
    else:
        color = "#dc3545"
    return f'''<div class="score-bar-wrap">
        <span class="score-label">{score}/{max_score}</span>
        <div class="score-bar"><div class="score-fill" style="width:{pct:.0f}%;background:{color}"></div></div>
    </div>'''


def _render_svg_chart(data_dict, color="#4a90d9", height=80, width=320, label="", is_pct=False):
    if not data_dict:
        return "<p class='muted'>No trend data available.</p>"
    keys = list(data_dict.keys())
    vals = list(data_dict.values())
    if not vals:
        return ""

    mn, mx = min(vals), max(vals)
    rng = mx - mn if mx != mn else 1
    padding = 30

    points = []
    for i, v in enumerate(vals):
        x = padding + i * ((width - 2 * padding) / max(len(vals) - 1, 1))
        y = height - padding - ((v - mn) / rng) * (height - 2 * padding)
        points.append((x, y))

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = polyline + f" {points[-1][0]:.1f},{height - padding} {points[0][0]:.1f},{height - padding}"

    svg = f'<svg width="{width}" height="{height + 25}" viewBox="0 0 {width} {height + 25}" class="trend-chart">'
    svg += f'<polygon points="{area}" fill="{color}" opacity="0.15"/>'
    svg += f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'

    for i, (x, y) in enumerate(points):
        svg += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>'
        suffix = "%" if is_pct else ""
        svg += f'<text x="{x:.1f}" y="{y - 8:.1f}" class="chart-val">{vals[i]}{suffix}</text>'
        svg += f'<text x="{x:.1f}" y="{height + 18}" class="chart-label">{keys[i]}</text>'

    if label:
        svg += f'<text x="{width / 2}" y="12" class="chart-title">{label}</text>'
    svg += '</svg>'
    return svg


def _render_metric_row(key, value):
    cls = ""
    v_str = str(value)
    if v_str in ("Met", "Yes") or "Expanding" in v_str or "Buybacks" in v_str:
        cls = "metric-good"
    elif v_str in ("Not Met", "No", "N/A") or "Contracting" in v_str or "Dilution" in v_str:
        cls = "metric-bad"
    elif v_str == "Speculative" or "Complex" in v_str:
        cls = "metric-bad"
    return f'<tr><td class="metric-key">{key}</td><td class="metric-val {cls}">{value}</td></tr>'


def _strategy_color(label):
    if "STRONG BUY" in label:
        return "#28a745"
    if "QUALITY HOLD" in label:
        return "#17a2b8"
    if "VALUE OPPORTUNITY" in label:
        return "#20c997"
    if "OVERVALUED" in label:
        return "#ffc107"
    if "WEAK VALUE" in label:
        return "#fd7e14"
    if "MIXED" in label:
        return "#6c757d"
    if "SPECULATIVE" in label:
        return "#e83e8c"
    if "AVOID" in label:
        return "#dc3545"
    if "WATCHLIST" in label:
        return "#ffc107"
    return "#6c757d"


def _render_price_targets(target_prices):
    fv = target_prices.get("fair_value")
    bb = target_prices.get("buy_below")
    cp = target_prices.get("current_price")
    pd_pct = target_prices.get("premium_discount_pct")

    if not fv or not cp:
        return ""

    pd_color = "#dc3545" if pd_pct and pd_pct > 0 else "#28a745"
    pd_label = f"+{pd_pct * 100:.0f}% Premium" if pd_pct and pd_pct > 0 else f"{pd_pct * 100:.0f}% Discount"

    return f'''
    <div class="phase-card price-targets-card">
        <h3>Price Targets & Action Levels</h3>
        <div class="price-targets-grid">
            <div class="price-item">
                <span class="price-label">Fair Value (Composite)</span>
                <span class="price-value">${fv:,.0f}</span>
            </div>
            <div class="price-item">
                <span class="price-label">Buy Below (30% MoS)</span>
                <span class="price-value" style="color:#28a745">${bb:,.0f}</span>
            </div>
            <div class="price-item">
                <span class="price-label">Current Price</span>
                <span class="price-value">${cp:,.2f}</span>
            </div>
            <div class="price-item">
                <span class="price-label">Premium / Discount</span>
                <span class="price-value" style="color:{pd_color}">{pd_label}</span>
            </div>
        </div>
    </div>'''


def _render_sector_comparison(sector_comparison, ticker):
    if not sector_comparison:
        return ""

    peer_table = sector_comparison.get("peer_table", [])
    rankings = sector_comparison.get("rankings", {})
    commentary = sector_comparison.get("commentary", [])

    if not peer_table:
        return ""

    # Build table rows
    rows = ""
    for c in sorted(peer_table, key=lambda x: -(x.get("market_cap") or 0)):
        is_target = c.get("is_target", False)
        row_cls = ' class="target-row"' if is_target else ""
        name = c.get("company_name", c.get("ticker", "?"))
        if len(name) > 20:
            name = name[:18] + ".."

        mc = f"${c['market_cap'] / 1e9:,.0f}B" if c.get("market_cap") else "N/A"
        pe = f"{c['trailing_pe']:.1f}" if c.get("trailing_pe") else "N/A"
        fpe = f"{c['forward_pe']:.1f}" if c.get("forward_pe") else "N/A"
        gm = f"{c['gross_margin'] * 100:.1f}%" if c.get("gross_margin") else "N/A"
        om = f"{c['operating_margin'] * 100:.1f}%" if c.get("operating_margin") else "N/A"
        roe = f"{c['roe'] * 100:.1f}%" if c.get("roe") else "N/A"
        rg = f"{c['revenue_growth'] * 100:.1f}%" if c.get("revenue_growth") else "N/A"

        marker = " *" if is_target else ""
        rows += f'<tr{row_cls}><td>{c.get("ticker", "?")}{marker}</td><td>{name}</td><td>{mc}</td><td>{pe}</td><td>{fpe}</td><td>{gm}</td><td>{om}</td><td>{roe}</td><td>{rg}</td></tr>\n'

    # Rankings badges
    rank_html = ""
    if rankings:
        rank_html = '<div class="signals" style="margin-top:12px">'
        for metric_label, r in rankings.items():
            rank = r["rank"]
            of = r["of"]
            best_is_low = r.get("rank1_is_best", True)
            if best_is_low:
                # Rank 1 = best (pre-sorted by metric direction)
                if rank <= 2:
                    badge_cls = "badge-good"
                elif rank >= of - 1:
                    badge_cls = "badge-bad"
                else:
                    badge_cls = "badge-neutral"
            else:
                # Inverted: high rank = good
                if rank >= of - 1:
                    badge_cls = "badge-good"
                elif rank <= 2:
                    badge_cls = "badge-bad"
                else:
                    badge_cls = "badge-neutral"
            rank_html += f'<span class="badge {badge_cls}">{metric_label}: #{rank} of {of}</span>'
        rank_html += '</div>'

    # Commentary
    comm_html = ""
    if commentary:
        comm_html = '<div style="margin-top:12px">'
        for c in commentary:
            comm_html += f'<p class="muted" style="margin-bottom:4px">{c}</p>'
        comm_html += '</div>'

    return f'''
    <div class="phase-card">
        <div class="phase-header">
            <h3>Sector Peer Comparison</h3>
        </div>
        <p class="commentary">Compared against {sector_comparison.get("peer_count", "?")} {sector_comparison.get("sector", "sector")} peers. Target company ({ticker}) highlighted.</p>
        <div style="overflow-x:auto">
        <table class="sector-table">
            <thead><tr>
                <th>Ticker</th><th>Company</th><th>Mkt Cap</th><th>P/E</th><th>Fwd P/E</th><th>Gross M.</th><th>Op. M.</th><th>ROE</th><th>Rev Gr.</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
        </div>
        {rank_html}
        {comm_html}
    </div>'''


def generate_html_report(ticker, data, phases, verdict, sec_metrics, sector_comparison=None, technical_chart=""):
    info = data.get("info", {})
    company = info.get("shortName", info.get("longName", ticker))
    price = info.get("currentPrice") or info.get("regularMarketPrice", "N/A")
    now = datetime.now().strftime("%B %d, %Y at %H:%M")

    v = verdict
    s_color = _strategy_color(v["strategy_label"])
    s_text_color = "#000" if v["strategy_label"] in ("WATCHLIST - OVERVALUED",) else "#fff"
    pct_display = f'{v["percentage"] * 100:.0f}%'
    fund_display = f'{v["fundamentals_pct"] * 100:.0f}%'
    val_display = f'{v["valuation_pct"] * 100:.0f}%'

    # Build phase sections
    phase_html = ""
    for p in phases:
        metrics_rows = "\n".join(_render_metric_row(k, val) for k, val in p.get("metrics", {}).items())
        charts = ""

        if "gm_history" in p and p["gm_history"]:
            charts += _render_svg_chart(p["gm_history"], "#4a90d9", label="Gross Margin %", is_pct=True)
        if "om_history" in p and p["om_history"]:
            charts += _render_svg_chart(p["om_history"], "#6f42c1", label="Operating Margin %", is_pct=True)
        if "roic_history" in p and p["roic_history"]:
            charts += _render_svg_chart(p["roic_history"], "#28a745", label="ROIC %", is_pct=True)
        if "fcf_history" in p and p["fcf_history"]:
            charts += _render_svg_chart(p["fcf_history"], "#17a2b8", label="Free Cash Flow ($B)")
        if "share_history" in p and p["share_history"]:
            charts += _render_svg_chart(p["share_history"], "#fd7e14", label="Shares Outstanding (B)")

        signals_html = ""
        if "moat_signals" in p and p["moat_signals"]:
            signals_html += '<div class="signals">'
            for s in p["moat_signals"]:
                signals_html += f'<span class="badge badge-good">{s}</span>'
            signals_html += '</div>'
        if "moat_concerns" in p and p["moat_concerns"]:
            signals_html += '<div class="signals">'
            for c in p["moat_concerns"]:
                signals_html += f'<span class="badge badge-bad">{c}</span>'
            signals_html += '</div>'

        dcf_html = ""
        if "dcf_assumptions" in p and p["dcf_assumptions"]:
            dcf_rows = "\n".join(_render_metric_row(k, val) for k, val in p["dcf_assumptions"].items())
            dcf_html = f'<div class="dcf-box"><h4>DCF Model Assumptions</h4><table class="metric-table">{dcf_rows}</table></div>'

        if "blend_breakdown" in p and p["blend_breakdown"]:
            blend_rows = "\n".join(_render_metric_row(k, val) for k, val in p["blend_breakdown"].items())
            dcf_html += f'<div class="dcf-box"><h4>Valuation Blend Weights</h4><table class="metric-table">{blend_rows}</table></div>'

        if "relative_details" in p and p["relative_details"]:
            rel_rows = "\n".join(_render_metric_row(k, val) for k, val in p["relative_details"].items())
            dcf_html += f'<div class="dcf-box"><h4>Relative Valuation (Peer-Based)</h4><table class="metric-table">{rel_rows}</table></div>'

        if "epv_details" in p and p["epv_details"]:
            epv_rows = "\n".join(_render_metric_row(k, val) for k, val in p["epv_details"].items())
            dcf_html += f'<div class="dcf-box"><h4>Earnings Power Value (No-Growth Floor)</h4><table class="metric-table">{epv_rows}</table></div>'

        # FINVIZ: Insider trades mini-table (Phase 4)
        insider_html = ""
        if "insider_trades" in p and p["insider_trades"]:
            irows = ""
            for t in p["insider_trades"]:
                irows += f'<tr><td>{t["name"]}</td><td>{t["date"]}</td><td>{t["type"]}</td><td>{t["value"]}</td></tr>'
            insider_html = f'''<div class="dcf-box"><h4>Recent Insider Trades (FINVIZ)</h4>
                <table class="metric-table"><tr><td class="metric-key"><b>Insider</b></td><td class="metric-key"><b>Date</b></td><td class="metric-key"><b>Type</b></td><td class="metric-key"><b>Value</b></td></tr>{irows}</table></div>'''

        # FINVIZ: News headlines (Phase 2)
        news_html = ""
        if "news_headlines" in p and p["news_headlines"]:
            nrows = ""
            for h in p["news_headlines"]:
                try:
                    sv = float(h["sentiment"])
                    sc = "#28a745" if sv > 0 else "#dc3545" if sv < 0 else "#666"
                except (ValueError, TypeError):
                    sc = "#666"
                nrows += f'<tr><td>{h["date"]}</td><td>{h["title"]}</td><td style="color:{sc};font-weight:600">{h["sentiment"]}</td></tr>'
            news_html = f'''<div class="dcf-box"><h4>Recent News Sentiment (VADER)</h4>
                <table class="metric-table"><tr><td class="metric-key"><b>Date</b></td><td class="metric-key"><b>Headline</b></td><td class="metric-key"><b>Sent.</b></td></tr>{nrows}</table></div>'''

        # FINVIZ: Analyst consensus badges (Phase 5)
        consensus_html = ""
        if "analyst_consensus" in p and p["analyst_consensus"]:
            badges = ""
            for label, count in p["analyst_consensus"].items():
                color = "#28a745" if "Buy" in label else "#dc3545" if "Sell" in label else "#ffc107"
                badges += f'<span class="badge" style="background:{color}20;color:{color};border:1px solid {color}40">{label}: {count}</span>'
            consensus_html = f'<div class="dcf-box"><h4>Analyst Consensus (FINVIZ)</h4><div class="signals">{badges}</div></div>'

        phase_html += f'''
        <div class="phase-card">
            <div class="phase-header">
                <h3>{p["name"]}</h3>
                {_render_score_bar(p["score"], p["max_score"])}
            </div>
            <p class="commentary">{p.get("commentary", "")}</p>
            <table class="metric-table">{metrics_rows}</table>
            {signals_html}
            <div class="charts-row">{charts}</div>
            {dcf_html}
            {insider_html}
            {news_html}
            {consensus_html}
        </div>'''

    # Price targets card
    price_targets_html = _render_price_targets(v.get("target_prices", {}))

    # Sector comparison card
    sector_html = _render_sector_comparison(sector_comparison, ticker)

    # SEC filing appendix
    sec_html = ""
    if sec_metrics:
        sec_rows = "\n".join(_render_metric_row(k, f"${val:,.0f}" if isinstance(val, (int, float)) else val) for k, val in sec_metrics.items())
        sec_html = f'''
        <div class="phase-card appendix">
            <h3>Appendix: SEC Filing Raw Metrics</h3>
            <p class="muted">Extracted directly from the latest 10-K filing HTML. Values may be in millions or thousands -- check filing for units.</p>
            <table class="metric-table">{sec_rows}</table>
        </div>'''

    # Bull/Bear
    bull_items = "\n".join(f"<li>{b}</li>" for b in v["bull_case"])
    bear_items = "\n".join(f"<li>{b}</li>" for b in v["bear_case"])

    # Action items
    action_items_html = "\n".join(f"<li>{a}</li>" for a in v.get("action_items", []))

    # Sector context line
    sector_ctx = ""
    if v.get("sector_context"):
        sector_ctx = f'<p class="muted" style="margin-top:8px">{v["sector_context"]}</p>'

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} Investment Analysis</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #f0f2f5; color: #1a1a2e; line-height: 1.6;
    }}
    .container {{ max-width: 920px; margin: 0 auto; padding: 20px; }}

    .header {{
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        color: #fff; padding: 40px 36px; border-radius: 16px;
        margin-bottom: 24px; position: relative; overflow: hidden;
    }}
    .header::after {{
        content: ''; position: absolute; top: -50%; right: -20%;
        width: 400px; height: 400px; border-radius: 50%;
        background: rgba(255,255,255,0.03);
    }}
    .header h1 {{ font-size: 2rem; font-weight: 700; margin-bottom: 4px; }}
    .header .ticker {{ font-size: 1.1rem; opacity: 0.7; margin-bottom: 16px; }}
    .header .price {{ font-size: 1.3rem; font-weight: 600; }}
    .header .date {{ font-size: 0.85rem; opacity: 0.5; margin-top: 8px; }}

    .strategy-box {{
        padding: 16px 24px; border-radius: 12px; margin-top: 16px;
        position: relative; z-index: 1;
    }}
    .strategy-label {{ font-size: 1.3rem; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; }}
    .strategy-detail {{ font-size: 0.95rem; margin-top: 6px; opacity: 0.9; }}
    .strategy-actions {{ margin-top: 8px; font-size: 0.85rem; opacity: 0.8; }}
    .strategy-actions li {{ margin-left: 16px; margin-bottom: 2px; }}

    .overall-score {{
        font-size: 1rem; margin-top: 12px; opacity: 0.85;
    }}
    .score-breakdown {{
        display: flex; gap: 20px; margin-top: 6px; font-size: 0.9rem; opacity: 0.7;
    }}
    .overall-bar {{
        width: 100%; height: 10px; background: rgba(255,255,255,0.15);
        border-radius: 5px; margin-top: 8px; overflow: hidden;
    }}
    .overall-fill {{
        height: 100%; border-radius: 5px; transition: width 0.5s;
    }}

    .exec-summary {{
        display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px;
    }}
    .bull-box, .bear-box {{
        padding: 20px 24px; border-radius: 12px; border-left: 5px solid;
        background: #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }}
    .bull-box {{ border-color: #28a745; }}
    .bear-box {{ border-color: #dc3545; }}
    .bull-box h3 {{ color: #28a745; margin-bottom: 10px; font-size: 1rem; }}
    .bear-box h3 {{ color: #dc3545; margin-bottom: 10px; font-size: 1rem; }}
    .bull-box li, .bear-box li {{
        font-size: 0.9rem; margin-bottom: 6px; margin-left: 16px;
    }}

    .phase-card {{
        background: #fff; border-radius: 12px; padding: 24px 28px;
        margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }}
    .phase-header {{
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 12px; flex-wrap: wrap; gap: 8px;
    }}
    .phase-header h3 {{ font-size: 1.15rem; color: #1a1a2e; }}
    .commentary {{ font-size: 0.9rem; color: #555; margin-bottom: 14px; font-style: italic; }}

    .score-bar-wrap {{ display: flex; align-items: center; gap: 10px; }}
    .score-label {{ font-weight: 700; font-size: 0.95rem; min-width: 50px; text-align: right; }}
    .score-bar {{
        width: 140px; height: 10px; background: #e9ecef;
        border-radius: 5px; overflow: hidden;
    }}
    .score-fill {{ height: 100%; border-radius: 5px; transition: width 0.4s; }}

    .metric-table {{ width: 100%; border-collapse: collapse; margin-bottom: 12px; }}
    .metric-table td {{ padding: 7px 12px; font-size: 0.9rem; border-bottom: 1px solid #f0f0f0; }}
    .metric-key {{ color: #555; width: 50%; }}
    .metric-val {{ font-weight: 600; }}
    .metric-good {{ color: #28a745; }}
    .metric-bad {{ color: #dc3545; }}

    .signals {{ margin: 10px 0; display: flex; flex-wrap: wrap; gap: 8px; }}
    .badge {{
        display: inline-block; padding: 5px 14px; border-radius: 20px;
        font-size: 0.8rem; font-weight: 500;
    }}
    .badge-good {{ background: #d4edda; color: #155724; }}
    .badge-bad {{ background: #f8d7da; color: #721c24; }}
    .badge-neutral {{ background: #e2e3e5; color: #383d41; }}

    .charts-row {{ display: flex; flex-wrap: wrap; gap: 16px; margin-top: 10px; }}
    .trend-chart {{ background: #fafbfc; border-radius: 8px; }}
    .chart-val {{ font-size: 10px; text-anchor: middle; fill: #333; font-weight: 600; }}
    .chart-label {{ font-size: 9px; text-anchor: middle; fill: #888; }}
    .chart-title {{ font-size: 10px; text-anchor: middle; fill: #555; font-weight: 700; }}

    .dcf-box {{
        background: #f8f9fa; border-radius: 8px; padding: 16px;
        margin-top: 12px; border: 1px solid #e9ecef;
    }}
    .dcf-box h4 {{ font-size: 0.95rem; margin-bottom: 8px; color: #333; }}

    .price-targets-grid {{
        display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 12px;
    }}
    .price-item {{ text-align: center; padding: 12px; background: #f8f9fa; border-radius: 8px; }}
    .price-label {{ display: block; font-size: 0.8rem; color: #666; margin-bottom: 4px; }}
    .price-value {{ display: block; font-size: 1.3rem; font-weight: 700; }}

    .sector-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    .sector-table th {{
        background: #1a1a2e; color: #fff; padding: 8px 10px;
        text-align: left; font-weight: 600; white-space: nowrap;
    }}
    .sector-table td {{ padding: 7px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }}
    .sector-table tr.target-row {{ background: #e8f4fd; font-weight: 600; }}
    .sector-table tr:hover {{ background: #f8f9fa; }}

    .appendix {{ background: #f8f9fa; }}
    .appendix h3 {{ font-size: 1rem; color: #555; margin-bottom: 8px; }}

    .footer {{
        text-align: center; padding: 24px; color: #888; font-size: 0.8rem;
        margin-top: 12px;
    }}
    .muted {{ color: #888; font-size: 0.85rem; }}

    @media (max-width: 640px) {{
        .exec-summary {{ grid-template-columns: 1fr; }}
        .phase-header {{ flex-direction: column; align-items: flex-start; }}
        .charts-row {{ flex-direction: column; }}
        .price-targets-grid {{ grid-template-columns: repeat(2, 1fr); }}
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>{company}</h1>
        <div class="ticker">{ticker} &bull; {info.get("sector", "")} &bull; {info.get("industry", "")}</div>
        <div class="price">Current Price: ${price if isinstance(price, (int, float)) else "N/A"}</div>
        <div class="strategy-box" style="background:{s_color};color:{s_text_color}">
            <div class="strategy-label">{v["strategy_label"]}</div>
            <div class="strategy-detail">{v["strategy_detail"]}</div>
            <ul class="strategy-actions">{action_items_html}</ul>
        </div>
        <div class="overall-score">Overall Score: {v["total_score"]}/{v["max_score"]} ({pct_display})</div>
        <div class="score-breakdown">
            <span>Fundamentals: {fund_display}</span>
            <span>Valuation: {val_display}</span>
        </div>
        <div class="overall-bar"><div class="overall-fill" style="width:{pct_display};background:{s_color}"></div></div>
        {sector_ctx}
        <div class="date">Analysis generated on {now}</div>
    </div>

    <div class="exec-summary">
        <div class="bull-box">
            <h3>Bull Case</h3>
            <ul>{bull_items}</ul>
        </div>
        <div class="bear-box">
            <h3>Bear Case</h3>
            <ul>{bear_items}</ul>
        </div>
    </div>

    <div class="phase-card">
        <div class="phase-header">
            <h3>Technical Analysis</h3>
        </div>
        {technical_chart}
    </div>

    {price_targets_html}
    {phase_html}
    {sector_html}
    {sec_html}

    <div class="footer">
        <p>This analysis is generated automatically using public financial data from Yahoo Finance and SEC EDGAR.</p>
        <p>This is not financial advice. All investment decisions should involve professional consultation and personal due diligence.</p>
        <p>Data sources: Yahoo Finance (yfinance), SEC EDGAR, FINVIZ &bull; Generated by Financer</p>
    </div>
</div>
</body>
</html>'''
    return html


# ── Orchestration ──────────────────────────────────────────────────────────────
def analyze_ticker(ticker, base_path="reports"):
    print(f"\n{'='*50}")
    print(f"  Analyzing {ticker}...")
    print(f"{'='*50}")

    print("  Fetching market data from Yahoo Finance...")
    data = fetch_yfinance_data(ticker)

    # Fetch FINVIZ supplemental data
    if HAS_FINVIZ:
        print("  Fetching supplemental data from FINVIZ...")
        finviz_data = fetch_finviz_data(ticker)
    else:
        finviz_data = {}

    # Fetch & score news headlines (VADER sentiment)
    print("  Fetching news & sentiment...")
    enriched_news = news_engine.fetch_and_score(ticker, max_items=20)

    sec_metrics = {}
    text_10k = ""
    path_10k = find_latest_filing(base_path, ticker, "10-K")
    if path_10k:
        print("  Parsing SEC 10-K filing...")
        sec_metrics = extract_metrics(path_10k)
        text_10k = get_10k_text(ticker, base_path)

    print("  Running phases 1-4 analysis...")
    phases_1_4 = [
        phase1_competence_filter(data, text_10k),
        phase2_moat_analysis(data, text_10k, finviz_data, enriched_news=enriched_news),
        phase3_quantitative_vitals(data, finviz_data),
        phase4_management(data, text_10k, finviz_data),
    ]

    # Sector peer comparison (needed for relative valuation in phase 5)
    print("  Fetching sector peer data...")
    info = data.get("info", {})
    peer_tickers, peer_info_cache = select_sector_peers(ticker, info, n=5)
    if peer_tickers:
        print(f"  Comparing against: {', '.join(peer_tickers)}")
        peer_data = fetch_peer_metrics(peer_tickers, peer_info_cache)
        sector_comparison = phase6_sector_comparison(data, peer_data)
    else:
        print("  No sector peers found for comparison.")
        peer_data = []
        sector_comparison = None

    print("  Running multi-method valuation (Phase 5)...")
    phases = phases_1_4 + [phase5_valuation(data, peer_data, finviz_data)]

    verdict = compute_strategy(phases, sector_comparison)

    print("  Generating technical chart...")
    technical_chart = technical.generate_technical_chart(ticker, data.get("history"), news=enriched_news)

    # Console summary
    print()
    company = data.get("info", {}).get("shortName", ticker)
    print(f"  Company: {company}")
    print()
    for p in phases:
        bar = "=" * p["score"] + "-" * (p["max_score"] - p["score"])
        print(f"  {p['name']:35} {p['score']:2}/{p['max_score']:<2}  [{bar}]")
    print(f"  {'':35} {'--------'}")
    print(f"  {'TOTAL':35} {verdict['total_score']:2}/{verdict['max_score']:<2}  ({verdict['percentage']*100:.0f}%)")
    print(f"  {'Fundamentals':35} {verdict['fundamentals_pct']*100:.0f}%")
    print(f"  {'Valuation':35} {verdict['valuation_pct']*100:.0f}%")
    print()
    print(f"  Strategy: {verdict['strategy_label']}")
    print(f"  {verdict['strategy_detail']}")
    tp = verdict.get("target_prices", {})
    if tp.get("fair_value") and tp.get("buy_below"):
        print(f"  Composite Fair Value: ${tp['fair_value']:,.0f} | Buy Below: ${tp['buy_below']:,.0f}")
        # Show individual method values from phase 5
        p5 = phases[4]
        parts = []
        if p5.get("raw_dcf"):
            parts.append(f"DCF ${p5['raw_dcf']:,.0f}")
        if p5.get("raw_relative"):
            parts.append(f"Relative ${p5['raw_relative']:,.0f}")
        if p5.get("raw_epv"):
            parts.append(f"EPV ${p5['raw_epv']:,.0f}")
        if p5.get("raw_analyst"):
            parts.append(f"Analyst ${p5['raw_analyst']:,.0f}")
        if parts:
            print(f"  Methods: {' | '.join(parts)}")
    print()

    html = generate_html_report(ticker, data, phases, verdict, sec_metrics, sector_comparison, technical_chart)
    report_path = Path(base_path) / f"{ticker}_analysis.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Report saved to: {report_path}")
    print()


if __name__ == "__main__":
    report_base = "reports"
    filings_root = Path(report_base) / "sec-edgar-filings"

    if not filings_root.exists():
        print(f"No reports found in {report_base}. Please run downloader.py first.")
    else:
        tickers = [d.name for d in filings_root.iterdir() if d.is_dir()]
        if not tickers:
            print("No ticker folders found.")
        else:
            for t in tickers:
                analyze_ticker(t, report_base)
