"""Asset drafting phase for the Swing Engine based on momentum."""

from __future__ import annotations

import pandas as pd


def draft_assets(latest_features: dict[str, pd.Series], n_select: int = 10) -> list[str]:
    """Sort tickers by absolute momentum and return the top `n_select`.

    Expects `latest_features` to map ticker -> a single row (Series) of features.
    """
    scores = []

    for ticker, row in latest_features.items():
        try:
            # Simple momentum metric using roc_20 and relative strength
            roc_20 = float(row.get("roc_20", 0.0))
            if pd.isna(roc_20):
                continue

            rs_20 = float(row.get("rs_20", 1.0))
            if pd.isna(rs_20):
                rs_20 = 1.0

            # Momentum composite
            momentum_score = roc_20 * rs_20
            scores.append((ticker, momentum_score))
        except (KeyError, ValueError, TypeError):
            continue

    scores.sort(key=lambda x: x[1], reverse=True)
    return [x[0] for x in scores[:n_select]]
