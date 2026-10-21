"""Global, frozen parameters for the reproducibility study.

Any change here invalidates published results — bump STUDY_VERSION instead.
"""

STUDY_VERSION = "0.2.0"
EXCHANGE = "binance-usdm-perpetual"
INTERVAL = "1h"

START = "2022-01-01T00:00:00Z"
END = "2026-01-01T00:00:00Z"  # exclusive: covers calendar 2022-01..2025-12

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "ARBUSDT",
]

INITIAL_EQUITY = 10_000.0

# Cost model (Binance USDⓈ-M, VIP0 taker + conservative slippage)
TAKER_FEE = 0.0005  # 5 bps per side
SLIPPAGE = 0.0002   # 2 bps adverse per side
MAINT_MARGIN = 0.005

FUNDING_HOURS = (0, 8, 16)

# Sizing
CONTROL_LEVERAGE = 5.0  # typical retail perp leverage used as the baseline

# Guardrail parameters under test
EXPOSURE_CAP = 1.0       # max gross notional / equity
DAILY_LOSS_LIMIT = 0.05  # 5% of day-start equity -> flatten + halt
DUPLICATE_PROB = 0.10    # share of orders that get re-sent (webhook retry)
DUPLICATE_WINDOW_S = 30  # idempotency window

SEED = 20260101

BAR_MS = 3_600_000
