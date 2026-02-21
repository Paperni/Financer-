from historical_tester.engines.base import EngineContext
from historical_tester.engines.native_engine import NativeEngine


def test_engine_context_shape():
    ctx = EngineContext(tester_kwargs={"start_date": "x"})
    assert isinstance(ctx.tester_kwargs, dict)


def test_native_engine_name():
    assert NativeEngine.name == "native"

