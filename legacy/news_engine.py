"""
News fetching and VADER sentiment analysis for Financer.
Fetches headlines from FINVIZ (primary) or yfinance (fallback),
then enriches each with VADER compound/pos/neg/neu scores.
"""
import pandas as pd
from datetime import datetime

import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

try:
    from finvizfinance.quote import finvizfinance as Finviz
    HAS_FINVIZ = True
except ImportError:
    HAS_FINVIZ = False

import yfinance as yf


# ── VADER singleton ───────────────────────────────────────────────────────────
_vader = None

def _get_vader():
    global _vader
    if _vader is None:
        try:
            _vader = SentimentIntensityAnalyzer()
        except LookupError:
            nltk.download("vader_lexicon", quiet=True)
            _vader = SentimentIntensityAnalyzer()
    return _vader


# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse_date(val):
    try:
        return pd.to_datetime(val)
    except Exception:
        return datetime.now()


# ── Fetching ──────────────────────────────────────────────────────────────────
def fetch_news(ticker, max_items=20):
    """Fetch recent news headlines. Returns list of dicts with title/date/link/source."""
    articles = []

    # Primary: FINVIZ
    if HAS_FINVIZ:
        try:
            stock = Finviz(ticker)
            df = stock.ticker_news()
            if df is not None and not df.empty:
                for _, row in df.head(max_items).iterrows():
                    title = str(row.get("Title", row.get("title", "")))
                    if not title or title == "nan":
                        continue
                    articles.append({
                        "title": title,
                        "date": _parse_date(row.get("Date", row.get("date", ""))),
                        "link": str(row.get("Link", row.get("link", ""))),
                        "source": "FINVIZ",
                    })
        except Exception:
            pass  # fall through to yfinance

    # Fallback: yfinance
    if not articles:
        try:
            news_list = yf.Ticker(ticker).news or []
            for item in news_list[:max_items]:
                articles.append({
                    "title": item.get("title", ""),
                    "date": datetime.fromtimestamp(item.get("providerPublishTime", 0)),
                    "link": item.get("link", ""),
                    "source": "yfinance",
                })
        except Exception:
            pass

    return articles


# ── Sentiment ─────────────────────────────────────────────────────────────────
def enrich_sentiment(articles):
    """Add VADER sentiment scores to each article dict. Modifies in place and returns the list."""
    sia = _get_vader()
    for article in articles:
        title = article.get("title", "")
        if title and title != "nan":
            scores = sia.polarity_scores(title)
            article["sentiment_compound"] = scores["compound"]
            article["sentiment_pos"] = scores["pos"]
            article["sentiment_neg"] = scores["neg"]
            article["sentiment_neu"] = scores["neu"]
            if scores["compound"] >= 0.05:
                article["sentiment_label"] = "positive"
            elif scores["compound"] <= -0.05:
                article["sentiment_label"] = "negative"
            else:
                article["sentiment_label"] = "neutral"
        else:
            article["sentiment_compound"] = 0.0
            article["sentiment_pos"] = 0.0
            article["sentiment_neg"] = 0.0
            article["sentiment_neu"] = 1.0
            article["sentiment_label"] = "neutral"
    return articles


# ── Convenience ───────────────────────────────────────────────────────────────
def fetch_and_score(ticker, max_items=20):
    """Fetch news and enrich with VADER sentiment in one call."""
    return enrich_sentiment(fetch_news(ticker, max_items))
