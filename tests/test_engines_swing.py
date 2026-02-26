import pandas as pd
from financer.engines.swing.engine import SwingEngine
from financer.engines.swing.policy import determine_allocation
from financer.engines.swing.scorecard import score_setup
from financer.models.enums import Direction, Regime

def test_swing_policy_allocation():
    alloc = determine_allocation(Regime.RISK_ON)
    assert alloc.swing_pct == 0.80
    assert alloc.cash_pct == 0.0

    alloc_off = determine_allocation(Regime.RISK_OFF)
    assert alloc_off.swing_pct == 0.0
    assert alloc_off.cash_pct == 0.80


def test_swing_scorecard():
    # Synthetic perfect setup
    row = pd.Series({
        "above_50": True,
        "rsi_14": 40.0,
        "macd_hist": 0.5,
        "rs_20": 1.1,
        "peg_proxy": 1.0,
        "earnings_within_7d": False
    })
    score, reasons = score_setup(row)
    assert score >= 5
    assert len(reasons) > 0


def test_swing_engine_emits_trade_intent():
    engine = SwingEngine(min_entry_score=4.0)

    # Strong momentum and perfect setup
    perfect_row = pd.Series({
        "sma_50": 100.0,
        "above_50": True,
        "regime": Regime.RISK_ON,
        "rsi_14": 35.0,
        "macd_hist": 0.5,
        "rs_20": 1.1,
        "peg_proxy": 1.0,
        "earnings_within_7d": False,
        "roc_20": 0.15,
        "atr_14": 2.0,
        "Close": 150.0
    })

    # Weak momentum and terrible setup
    bad_row = pd.Series({
        "sma_50": 100.0,
        "above_50": False,
        "regime": Regime.RISK_OFF,
        "rsi_14": 80.0,
        "macd_hist": -0.5,
        "rs_20": 0.9,
        "peg_proxy": 3.0,
        "earnings_within_7d": True,
        "roc_20": -0.10,
        "atr_14": 2.0,
        "Close": 50.0
    })

    features = {
        "AAPL": perfect_row,
        "TSLA": bad_row
    }

    intents = engine.evaluate(features)

    # Assert
    assert len(intents) == 1
    assert intents[0].ticker == "AAPL"
    assert intents[0].direction == Direction.BUY
    assert len(intents[0].reasons) > 0
    assert intents[0].target_price == 158.0  # 150 + 4*2
    assert intents[0].stop_price == 147.0    # 150 - 1.5*2
