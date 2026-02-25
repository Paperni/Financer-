from financer.cli.run_live import main
import pytest
def d():
    pytest.main(['-k', 'dry_run', '-s', 'tests/test_live_loop.py'])
if __name__ == '__main__':
    d()
