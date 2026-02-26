from historical_tester.optimizers.base import OptimizationContext
from historical_tester.optimizers.freqtrade_style import FreqtradeStyleOptimizer


def test_optimizer_context():
    ctx = OptimizationContext(base_kwargs={}, override_sets=[[]])
    assert ctx.objective_name == "return_drawdown_score"


def test_optimizer_name():
    assert FreqtradeStyleOptimizer.name == "freqtrade_style"

