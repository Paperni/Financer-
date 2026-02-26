import cProfile
import pstats
from financer.cli.run_replay import run_replay

if __name__ == "__main__":
    import time
    print("Profiling run_replay on 5 assets...")
    t0 = time.time()
    
    # Pre-profile execution to trigger downloads and caching
    run_replay(tickers=["AAPL", "MSFT", "GOOGL", "AMZN", "META"], start="2021-01-01", end="2025-12-31")
    
    t1 = time.time()
    print(f"Warmup took {t1 - t0:.2f}s")
    
    # Profile the fast execution path
    cProfile.run("run_replay(tickers=['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META'], start='2021-01-01', end='2025-12-31')", "campaign.prof")
    
    p = pstats.Stats("campaign.prof")
    p.sort_stats("cumtime").print_stats(30)
