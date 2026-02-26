"""Shared execution policy logic and constants."""

# Risk units
STOP_LOSS_ATR_MULTIPLIER = 1.5
TRAILING_STOP_ATR_MULTIPLIER = 1.0

# Take Profit Tiers (in multiples of the initial risk R)
# Where 1R = STOP_LOSS_ATR_MULTIPLIER * ATR
TP_TIERS_R = [2.0, 3.0, 4.0]

# Time Stop 
TIME_STOP_DAYS = 15
