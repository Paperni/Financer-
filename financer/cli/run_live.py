"""CLI runner for the Financer Live execution loop."""

import argparse
import logging
from typing import Optional

from financer.live.config import BALANCED_PROFILE, CONSERVATIVE_PROFILE, ExecutionMode
from financer.live.loop import run_live_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main(profile_name: str, mode_str: Optional[str] = None):
    """Entry point for the live execution daemon."""
    
    if profile_name.lower() == "balanced":
        config = BALANCED_PROFILE.model_copy(deep=True)
    else:
        config = CONSERVATIVE_PROFILE.model_copy(deep=True)
        
    if mode_str:
        try:
            config.mode = ExecutionMode(mode_str.lower())
        except ValueError:
            logger.error(f"Invalid mode '{mode_str}'. Must be one of: [dry_run, manual, auto]")
            return

    logger.info(f"Loaded config profile '{profile_name}' with mode {config.mode.value}.")
    
    try:
        run_live_loop(config)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Stopping Financer live loop.")
    except Exception as e:
        logger.error(f"Live loop died unexpectedly: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Financer algorithmic brain in Live mode.")
    parser.add_argument(
        "--profile", type=str, default="conservative", choices=["conservative", "balanced"],
        help="The risk configuration profile to use."
    )
    parser.add_argument(
        "--mode", type=str, choices=["dry_run", "manual", "auto"],
        help="Override the execution mode. If not provided, defaults to profile settings (likely dry_run)."
    )
    
    args = parser.parse_args()
    main(args.profile, args.mode)
