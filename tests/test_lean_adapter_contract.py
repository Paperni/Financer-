from historical_tester.validators.lean_adapter import LeanValidationAdapter


def test_lean_adapter_name():
    assert LeanValidationAdapter().name == "lean"

