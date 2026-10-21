"""Bar-by-bar execution simulator with pluggable guardrails.

Accounting model
----------------
* Long/short perpetual futures, one position per symbol, full flip on signal change.
* Signals are computed on bar close and executed at the *next* bar's open.
* Costs: 5 bps taker fee + 2 bps adverse slippage on every fill.
* Funding is charged/credited at settlement bars on the marked notional.
* Liquidation is approximated as "intrabar worst-case mark wipes equity" (no
  partial liquidation, no insurance fund), which is conservative for tail metrics.
* Position size is fixed at entry and is *not* rebalanced bar-to-bar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import config as C
from .rules import GuardConfig

DAY_MS = 86_400_000


@dataclass
class SimResult:
    equity: np.ndarray
    orders: int = 0
    duplicates_blocked: int = 0
    duplicates_executed: int = 0
    cap_blocked: int = 0
    halts: int = 0
    liquidations: int = 0
    max_gross_leverage: float = 0.0
    ruined: bool = False


def _fill(cash: float, qty: float, delta: float, price: float) -> tuple[float, float]:
    if delta == 0.0:
        return cash, qty
    exec_price = price * (1.0 + C.SLIPPAGE) if delta > 0 else price * (1.0 - C.SLIPPAGE)
    cash -= delta * exec_price
    cash -= abs(delta) * exec_price * C.TAKER_FEE
    return cash, qty + delta


def simulate(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    ts: np.ndarray,
    funding: np.ndarray,
    states: np.ndarray,
    cfg: GuardConfig,
    seed: int,
) -> SimResult:
    n = len(close)
    equity = np.zeros(n, dtype="float64")
    if n == 0:
        return SimResult(equity=equity)

    desired = np.zeros(n, dtype="int8")
    desired[1:] = states[:-1]  # execute next bar: no look-ahead

    cash = C.INITIAL_EQUITY
    qty = 0.0
    state = 0
    day_id = -1
    day_start = cash
    halted = False
    dup_rng = np.random.default_rng(seed)

    res = SimResult(equity=equity)

    for i in range(n):
        bar_day = int(ts[i] // DAY_MS)
        if bar_day != day_id:
            day_id = bar_day
            day_start = cash + qty * (close[i - 1] if i else open_[i])
            halted = False

        price = open_[i]
        target = int(desired[i])

        if target != state and not halted:
            mark = cash + qty * price
            if mark > 0:
                notional = target * cfg.max_leverage * mark
                delta = notional / price - qty
                cash, qty = _fill(cash, qty, delta, price)
                res.orders += 1

                if dup_rng.random() < cfg.duplicate_prob:
                    if cfg.dedupe:
                        res.duplicates_blocked += 1
                    else:
                        # a retried webhook replays the *same* order, not a rebalance
                        side = 1.0 if delta > 0 else -1.0
                        replay = side * abs(delta)
                        if cfg.exposure_cap is not None:
                            equity_now = cash + qty * price
                            breaches = (
                                equity_now <= 0
                                or abs(qty + replay) * price > cfg.exposure_cap * equity_now * 1.001
                            )
                            if breaches:
                                res.cap_blocked += 1
                            else:
                                cash, qty = _fill(cash, qty, replay, price)
                                res.duplicates_executed += 1
                        else:
                            cash, qty = _fill(cash, qty, replay, price)
                            res.duplicates_executed += 1

                gross = abs(qty * price) / max(cash + qty * price, 1e-9)
                res.max_gross_leverage = max(res.max_gross_leverage, gross)
                state = target

        rate = funding[i]
        if rate != 0.0 and qty != 0.0:
            cash -= qty * close[i] * rate

        mark_close = cash + qty * close[i]
        worst = low[i] if qty > 0 else (high[i] if qty < 0 else close[i])
        if qty != 0.0 and cash + qty * worst <= 0.0:
            equity[i:] = 0.0
            res.liquidations += 1
            res.ruined = True
            return res

        equity[i] = mark_close

        if cfg.daily_loss_limit is not None and not halted and day_start > 0:
            if mark_close / day_start - 1.0 <= -cfg.daily_loss_limit:
                cash, qty = _fill(cash, qty, -qty, close[i])
                equity[i] = cash
                state = 0
                halted = True
                res.orders += 1
                res.halts += 1

    return res
