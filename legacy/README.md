# Legacy Scripts

These files are **quarantined** from the main `financer/` package. They are kept for reference and parameter mining during migration but must not be imported by `financer/` code.

| File | Successor Module |
| :--- | :--- |
| `analyzer.py` | `financer/analytics/` |
| `data_engine.py` / `data_static.py` | `financer/data/` |
| `downloader.py` | `financer/data/` |
| `indicators.py` | `financer/features/` |
| `live_trader.py` / `trader.py` / `smart_trader.py` | `financer/live/` |
| `metrics.py` | `financer/analytics/metrics.py` |
| `news_engine.py` | Future Slice 8 (FinBERT) |
| `portfolio.py` | `financer/models/portfolio.py` |
| `qualitative.py` / `technical.py` | `financer/engines/` + `financer/features/` |

**Deletion criteria**: A file may only be deleted after all its logic (especially signal parameters and alpha heuristics) has been verified ported to `financer/`.
