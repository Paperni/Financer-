# Technical Debt & Legacy Code

During the initial slices of the Financer refactor (Slices 1-6), a strictly decoupled, domain-driven architecture was introduced under the `financer/` python package. 

However, many legacy files remain in the repository root. **Do not delete them yet.** They still contain valuable logic (especially specific indicator parameters, ML logic, and old reporting scripts) that will be migrating in future Slices.

## Legacy Modules List
The following files in the project root are considered legacy and should be migrated to the `financer/` module or deprecated:
- `analyzer.py`
- `data_engine.py` & `data_static.py`
- `indicators.py`
- `live_trader.py` & `trader.py` & `smart_trader.py`
- `metrics.py`
- `news_engine.py`
- `portfolio.py`
- `qualitative.py` & `technical.py`
- `downloader.py`
- `diagnose_signals.py`

## Duplicate Responsibilities
There are overlapping concepts between the legacy root files and the new `financer/` package:
- Old `portfolio.py` vs new `financer/models/portfolio.py`
- Old `indicators.py` vs new `financer/features/` pipeline using TA-Lib
- Old `live_trader.py` vs new `financer/live/loop.py`

## Deletion Criteria
A legacy file may only be deleted when:
1. All of its functional responsibilities have been successfully migrated into `financer/`.
2. All hardcoded parameters or alpha-generating logic have been verified as ported.
3. The legacy file is no longer referenced by any `scripts/` or `tests/`.
