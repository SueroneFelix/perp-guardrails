"""Risk/return metrics computed from a bar-level equity curve."""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def daily_equity(equity: np.ndarray, ts: np.ndarray) -> pd.Series:
    index = pd.to_datetime(ts, unit="ms", utc=True)
    series = pd.Series(equity, index=index)
    return series.resample("1d").last().dropna()


def summarize(equity: np.ndarray, ts: np.ndarray) -> dict[str, float]:
    if len(equity) == 0:
        return {}

    daily = daily_equity(equity, ts)
    rets = daily.pct_change().dropna()
    final = float(equity[-1])
    start = float(C.INITIAL_EQUITY)
    days = max(len(daily), 1)

    total_return = final / start - 1.0
    cagr = (final / start) ** (365.0 / days) - 1.0 if final > 0 else -1.0

    running_max = np.maximum.accumulate(equity)
    with np.errstate(invalid="ignore", divide="ignore"):
        drawdown = equity / running_max - 1.0
    max_dd = float(np.nanmin(drawdown)) if len(drawdown) else 0.0

    vol = float(rets.std(ddof=1) * np.sqrt(365)) if len(rets) > 1 else 0.0
    sharpe = float(rets.mean() / rets.std(ddof=1) * np.sqrt(365)) if len(rets) > 1 and rets.std(ddof=1) > 0 else 0.0

    if len(rets) >= 20:
        cutoff = np.quantile(rets.to_numpy(), 0.05)
        tail = rets[rets <= cutoff]
        cvar5 = float(tail.mean()) if len(tail) else float(cutoff)
    else:
        cvar5 = float(rets.min()) if len(rets) else 0.0
    worst_day = float(rets.min()) if len(rets) else 0.0

    return {
        "final_equity": final,
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "calmar": (cagr / abs(max_dd)) if max_dd < 0 else np.nan,
        "vol_annual": vol,
        "sharpe": sharpe,
        "cvar_5pct": cvar5,
        "worst_day": worst_day,
        "days": float(days),
    }
