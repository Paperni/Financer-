from historical_tester.engines.backtrader_engine import BacktraderEngine


def test_backtrader_engine_name():
    assert BacktraderEngine.name == "backtrader"

