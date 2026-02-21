import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

def generate_technical_chart(ticker, data, theme="light", news=None):
    """
    Generates an interactive HTML chart with:
    - Candlestick price data
    - SMA 50 & 200
    - Bollinger Bands
    - Volume
    - RSI (14)
    - MACD
    """
    if data is None or data.empty:
        return "<div>No historical data available for chart.</div>"

    # Ensure index is datetime
    df = data.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Calculate Indicators
    # SMA
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    
    # Bollinger Bands (20, 2)
    df['BB_Mid'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * 2)
    df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)
    
    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD (12, 26, 9)
    # Note: Using EMA for MACD is standard
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

    # Determine colors based on theme
    # We'll default to a clean look that fits the existing report
    bg_color = "white"
    grid_color = "#f0f0f0"
    text_color = "#333"
    
    if theme == "dark":
        bg_color = "#1e1e1e"
        grid_color = "#333"
        text_color = "#ddd"

    # Create Subplots
    # Row 1: Price (Candles + MA + BB) - 60% height
    # Row 2: Volume - 10% height
    # Row 3: RSI - 15% height
    # Row 4: MACD - 15% height
    fig = make_subplots(
        rows=4, cols=1, 
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.1, 0.15, 0.20],
        subplot_titles=(f"{ticker} Price Action", "Volume", "RSI (14)", "MACD")
    )

    # 1. Price Chart
    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="Price",
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350' # vivid green/red
    ), row=1, col=1)

    # SMA 50
    fig.add_trace(go.Scatter(
        x=df.index, y=df['SMA_50'], line=dict(color='orange', width=1.5), name="SMA 50"
    ), row=1, col=1)

    # SMA 200
    fig.add_trace(go.Scatter(
        x=df.index, y=df['SMA_200'], line=dict(color='blue', width=1.5), name="SMA 200"
    ), row=1, col=1)

    # Bollinger Bands
    # Upper/Lower as faint lines, maybe with fill? 
    # For now, just lines to avoid visual noise
    fig.add_trace(go.Scatter(
        x=df.index, y=df['BB_Upper'], 
        line=dict(color='gray', width=1, dash='dot'), 
        name="BB Upper", visible='legendonly' # hidden by default to reduce clutter
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df['BB_Lower'], 
        line=dict(color='gray', width=1, dash='dot'), 
        name="BB Lower", visible='legendonly',
        fill='tonexty', fillcolor='rgba(200,200,200,0.1)' # faint fill
    ), row=1, col=1)

    # News event markers on price chart
    if news:
        from collections import defaultdict
        _news_style = {
            "positive": {"color": "rgba(40,167,69,0.8)", "symbol": "triangle-up"},
            "negative": {"color": "rgba(220,53,69,0.8)", "symbol": "triangle-down"},
            "neutral":  {"color": "rgba(128,128,128,0.6)", "symbol": "diamond"},
        }
        buckets = defaultdict(lambda: {"x": [], "y": [], "text": []})
        for article in news:
            news_date = pd.to_datetime(article.get("date"))
            if news_date is pd.NaT or news_date < df.index[0] or news_date > df.index[-1]:
                continue
            label = article.get("sentiment_label", "neutral")
            idx = df.index.get_indexer([news_date], method="nearest")[0]
            buckets[label]["x"].append(df.index[idx])
            buckets[label]["y"].append(float(df["High"].iloc[idx]) * 1.02)
            compound = article.get("sentiment_compound", 0)
            buckets[label]["text"].append(
                f"{article.get('title', '')[:80]}<br>Sentiment: {compound:+.2f}"
            )
        for label, pts in buckets.items():
            if not pts["x"]:
                continue
            s = _news_style.get(label, _news_style["neutral"])
            fig.add_trace(go.Scatter(
                x=pts["x"], y=pts["y"],
                mode="markers",
                marker=dict(size=10, color=s["color"], symbol=s["symbol"],
                            line=dict(width=1, color="white")),
                text=pts["text"],
                hoverinfo="text",
                name=f"News ({label})",
                showlegend=True,
                legendgroup="news",
            ), row=1, col=1)

    # 2. Volume
    colors = np.where(df['Open'] >= df['Close'], '#ef5350', '#26a69a').tolist()
    fig.add_trace(go.Bar(
        x=df.index, y=df['Volume'],
        marker_color=colors,
        name="Volume"
    ), row=2, col=1)

    # 3. RSI
    fig.add_trace(go.Scatter(
        x=df.index, y=df['RSI'],
        line=dict(color='#9c27b0', width=2),
        name="RSI"
    ), row=3, col=1)
    # Add 70/30 lines
    fig.add_shape(type="line", row=3, col=1,
                  x0=df.index[0], x1=df.index[-1], y0=70, y1=70,
                  line=dict(color="red", width=1, dash="dash"))
    fig.add_shape(type="line", row=3, col=1,
                  x0=df.index[0], x1=df.index[-1], y0=30, y1=30,
                  line=dict(color="green", width=1, dash="dash"))

    # 4. MACD
    fig.add_trace(go.Scatter(
        x=df.index, y=df['MACD'],
        line=dict(color='black', width=1.5),
        name="MACD"
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df['Signal'],
        line=dict(color='red', width=1.5),
        name="Signal"
    ), row=4, col=1)
    # Histogram
    macd_hist = df['MACD'] - df['Signal']
    hist_colors = np.where(macd_hist.fillna(0) >= 0, 'green', 'red').tolist()
    fig.add_trace(go.Bar(
        x=df.index, y=macd_hist,
        marker_color=hist_colors,
        name="MACD Hist"
    ), row=4, col=1)

    # Layout Updates
    fig.update_layout(
        title_text=f"Technical Analysis: {ticker}",
        height=900,  # Tall enough for subplots
        showlegend=True,
        xaxis_rangeslider_visible=False, # We have zoom capability anyway, slider takes space
        plot_bgcolor=bg_color,
        paper_bgcolor=bg_color,
        font=dict(color=text_color),
        margin=dict(l=50, r=50, t=50, b=50) # Tighter margins
    )
    
    # Improve Grid
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor=grid_color)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor=grid_color)

    # Return HTML string
    # include_plotlyjs='cdn' ensures the library is loaded from CDN, 
    # making the file smaller but requiring internet.
    # If the user wants offline, we can use include_plotlyjs=True (adds ~3MB to file)
    # For now, CDN is cleaner.
    return fig.to_html(full_html=False, include_plotlyjs='cdn')
