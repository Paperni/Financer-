"""Integration smoke test for the institutional swing trading system."""

import sys

def main():
    errors = []
    sep = "=" * 60

    print(sep)
    print("  INTEGRATION SMOKE TEST")
    print(sep)

    # 1. Imports
    print("\n[1] Imports...")
    try:
        import indicators
        import portfolio as pf
        import live_trader
        import smart_trader
        print("  OK: All 4 modules imported.")
    except Exception as e:
        errors.append(f"Import: {e}")
        print(f"  FAIL: {e}")
        sys.exit(1)

    # 2. Indicators
    print("\n[2] Indicator calculations...")
    try:
        import pandas as pd
        import numpy as np
        np.random.seed(42)
        n = 100
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        df = pd.DataFrame({
            "Open": close - 0.3,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": np.random.randint(1000000, 5000000, n).astype(float),
        })
        df = indicators.calculate_indicators(df)
        for col in ["SMA_50", "RSI", "MACD", "ATR", "Vol_MA", "Vol_3bar"]:
            assert col in df.columns, f"Missing {col}"
        rsi = df["RSI"].dropna()
        assert rsi.min() >= 0 and rsi.max() <= 100
        print(f"  OK: All indicators. RSI [{rsi.min():.1f}, {rsi.max():.1f}]")
    except Exception as e:
        errors.append(f"Indicators: {e}")
        print(f"  FAIL: {e}")

    # 3. 8-point scoring
    print("\n[3] 8-point scoring...")
    try:
        row = df.iloc[-1]
        score, reasons = indicators.score_setup(row, 1.5, True)
        print(f"  OK: Score={score}/8 (no fundamentals), reasons={list(reasons.keys())}")
        passed, s, r = indicators.check_buy_signal_detailed(row, 1.5, True)
        print(f"  OK: Detailed -> passed={passed}, score={s}")

        # With PEG data (P/E 25, revenue growth 40% -> PEG < 1, +1 point)
        fundies_good = {"pe": 25.0, "revenue_growth": 40.0, "fetched_at": 0}
        score_with_peg, reasons_peg = indicators.score_setup(row, 1.5, True, fundies_good)
        assert score_with_peg == score + 1, f"PEG should add 1 point: {score_with_peg} vs {score}+1"
        assert "peg" in reasons_peg
        print(f"  OK: With PEG (P/E=25, RevG=40%): score={score_with_peg}/8, peg reason: {reasons_peg['peg']}")

        # Overvalued PEG (P/E 80, revenue growth 30% -> no point)
        fundies_bad = {"pe": 80.0, "revenue_growth": 30.0, "fetched_at": 0}
        score_no_peg, reasons_no = indicators.score_setup(row, 1.5, True, fundies_bad)
        assert score_no_peg == score, f"Overvalued PEG should add 0: {score_no_peg} vs {score}"
        assert "peg" not in reasons_no
        print(f"  OK: Overvalued (P/E=80, RevG=30%): score={score_no_peg}/8, no PEG point")
    except Exception as e:
        errors.append(f"Scoring: {e}")
        print(f"  FAIL: {e}")

    # 4. Volume contraction
    print("\n[4] Volume contraction...")
    try:
        result = indicators.check_volume_contraction(df)
        print(f"  OK: contracting={result}")
    except Exception as e:
        errors.append(f"VolContr: {e}")
        print(f"  FAIL: {e}")

    # 5. ATR position sizing
    print("\n[5] ATR position sizing...")
    try:
        s1 = pf.calc_position(150.0, 2.5, 100000, "RISK_ON")
        s2 = pf.calc_position(150.0, 2.5, 100000, "CAUTIOUS")
        s3 = pf.calc_position(150.0, None, 100000, "RISK_ON")
        assert s1["qty"] > 0 and s2["qty"] <= s1["qty"] and s3["qty"] > 0
        assert s1["sl"] < 150 < s1["tp1"] < s1["tp2"] < s1["tp3"]
        print(f"  OK: RiskOn={s1['qty']}sh, Cautious={s2['qty']}sh, Fallback={s3['qty']}sh")
        print(f"      SL=${s1['sl']}, TP1=${s1['tp1']}, TP2=${s1['tp2']}, TP3=${s1['tp3']}")
    except Exception as e:
        errors.append(f"Sizing: {e}")
        print(f"  FAIL: {e}")

    # 6. Full trade lifecycle
    print("\n[6] Full trade lifecycle (buy -> TP1 -> TP2 -> TP3 -> trail)...")
    try:
        w = {"cash": 100000.0, "initial_capital": 100000.0, "holdings": {}, "history": []}
        pf.execute_buy(w, "TEST", 100.0, atr=3.0, regime="RISK_ON", signals={"reasoning": "test"})
        pos = w["holdings"]["TEST"]
        iq = pos["qty"]
        print(f"  BUY: {iq} shares @ $100, SL=${pos['sl']}, TP1=${pos['tp1']}, TP2=${pos['tp2']}, TP3=${pos['tp3']}")

        # TP1
        r = pf.check_exits(w, "TEST", pos["tp1"] + 0.01)
        assert r and r[0] == "TP1", f"Expected TP1, got {r}"
        assert w["holdings"]["TEST"]["sl"] == 100.0, "SL should be at breakeven"
        rem1 = w["holdings"]["TEST"]["qty"]
        print(f"  TP1: Sold {iq - rem1} shares. SL->breakeven. Remaining: {rem1}")

        # TP2
        r = pf.check_exits(w, "TEST", pos["tp2"] + 0.01)
        assert r and r[0] == "TP2"
        rem2 = w["holdings"]["TEST"]["qty"]
        print(f"  TP2: Sold {rem1 - rem2} shares. Remaining: {rem2}")

        # TP3
        r = pf.check_exits(w, "TEST", pos["tp3"] + 0.01)
        assert r and r[0] == "TP3"
        rem3 = w["holdings"]["TEST"]["qty"]
        print(f"  TP3: Sold {rem2 - rem3} shares. Runner: {rem3}")

        # Trail stop
        if "TEST" in w["holdings"] and w["holdings"]["TEST"]["qty"] > 0:
            pf.check_exits(w, "TEST", 125.0)  # new high
            assert w["holdings"]["TEST"]["trail_high"] == 125.0
            r = pf.check_exits(w, "TEST", 120.0)  # drop below trail
            if r:
                print(f"  Trail: Sold runner at $120. Reason: {r[0]}")

        sells = [h for h in w["history"] if h["Action"] == "SELL"]
        total_pnl = sum(s["PnL"] for s in sells)
        print(f"  OK: {len(sells)} sells, total PnL: ${total_pnl:+.2f}")
    except Exception as e:
        errors.append(f"Lifecycle: {e}")
        import traceback
        traceback.print_exc()

    # 7. Time stop
    print("\n[7] Time stop...")
    try:
        import datetime
        import zoneinfo
        w = {"cash": 100000.0, "initial_capital": 100000.0, "holdings": {}, "history": []}
        pf.execute_buy(w, "DEAD", 50.0, atr=1.0, regime="RISK_ON", signals={"reasoning": "test"})
        old = (pf.now_et() - datetime.timedelta(hours=pf.TIME_STOP_HOURS + 1)).isoformat()
        w["holdings"]["DEAD"]["entry_time"] = old
        r = pf.check_exits(w, "DEAD", 50.50)
        assert r and r[0] == "Time Stop", f"Expected Time Stop, got {r}"
        print(f"  OK: Time stop triggered after {pf.TIME_STOP_HOURS+1}h (threshold: {pf.TIME_STOP_HOURS}h)")
    except Exception as e:
        errors.append(f"TimeStop: {e}")
        print(f"  FAIL: {e}")

    # 8. Market hours + DataCache
    print("\n[8] Market hours + DataCache...")
    try:
        is_open, status = pf.is_market_open()
        cache = indicators.DataCache()
        assert cache.get_market_regime() == "UNKNOWN"
        assert cache.get("AAPL") is None
        assert cache.get_relative_strength("AAPL") is None
        print(f"  OK: Market={status}, Cache defaults safe")
    except Exception as e:
        errors.append(f"MarketCache: {e}")
        print(f"  FAIL: {e}")

    # 9. smart_trader compat
    print("\n[9] smart_trader compatibility...")
    try:
        from smart_trader import calculate_hourly_indicators, run_draft
        assert callable(calculate_hourly_indicators)
        assert callable(run_draft)
        print("  OK: Exports verified")
    except Exception as e:
        errors.append(f"SmartTrader: {e}")
        print(f"  FAIL: {e}")

    # 10. Momentum scoring
    print("\n[10] Momentum scoring...")
    try:
        ms = indicators.calculate_momentum_score(df)
        assert ms != -999
        print(f"  OK: score={ms:.4f}")
    except Exception as e:
        errors.append(f"Momentum: {e}")
        print(f"  FAIL: {e}")

    # Summary
    print(f"\n{sep}")
    if errors:
        print(f"  FAILED: {len(errors)} test(s)")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print("  ALL 10 TESTS PASSED")
    print(sep)


if __name__ == "__main__":
    main()
