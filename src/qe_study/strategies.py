"""Five public, deliberately simple strategy baselines.

Every function returns an int8 array of the desired position (-1 short / 0 flat /
+1 long) *as known at the close of each bar*. The engine shifts the series by one
bar before executing, so no look-ahead is possible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ma_trend(df: pd.DataFrame, fast: int = 20, slow: int = 60) -> np.ndarray:
    close = df["close"].to_numpy(dtype="float64")
    fast_ma = pd.Series(close).rolling(fast).mean().to_numpy()
    slow_ma = pd.Series(close).rolling(slow).mean().to_numpy()
    state = np.zeros(len(close), dtype="int8")
    valid = ~np.isnan(slow_ma)
    state[valid & (fast_ma > slow_ma)] = 1
    state[valid & (fast_ma < slow_ma)] = -1
    return state


def bollinger_mr(
    df: pd.DataFrame, window: int = 20, k: float = 2.0, exit_z: float = 0.5
) -> np.ndarray:
    close = df["close"].to_numpy(dtype="float64")
    series = pd.Series(close)
    mean = series.rolling(window).mean().to_numpy()
    std = series.rolling(window).std(ddof=0).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (close - mean) / std
    state = np.zeros(len(close), dtype="int8")
    current = 0
    for i in range(len(close)):
        if np.isnan(z[i]):
            continue
        if current == 0:
            if z[i] <= -k:
                current = 1
            elif z[i] >= k:
                current = -1
        elif current == 1 and z[i] >= -exit_z:
            current = 0
        elif current == -1 and z[i] <= exit_z:
            current = 0
        state[i] = current
    return state


def donchian(df: pd.DataFrame, entry: int = 20, exit_: int = 10) -> np.ndarray:
    high = pd.Series(df["high"].to_numpy(dtype="float64"))
    low = pd.Series(df["low"].to_numpy(dtype="float64"))
    close = df["close"].to_numpy(dtype="float64")
    upper = high.rolling(entry).max().shift(1).to_numpy()
    lower = low.rolling(entry).min().shift(1).to_numpy()
    exit_high = high.rolling(exit_).max().shift(1).to_numpy()
    exit_low = low.rolling(exit_).min().shift(1).to_numpy()

    state = np.zeros(len(close), dtype="int8")
    current = 0
    for i in range(len(close)):
        if np.isnan(upper[i]) or np.isnan(exit_low[i]):
            continue
        if current == 0:
            if close[i] > upper[i]:
                current = 1
            elif close[i] < lower[i]:
                current = -1
        elif current == 1 and close[i] < exit_low[i]:
            current = 0
        elif current == -1 and close[i] > exit_high[i]:
            current = 0
        state[i] = current
    return state


def funding_carry(
    df: pd.DataFrame, funding: np.ndarray, window: int = 24, threshold: float = 0.0002
) -> np.ndarray:
    """Short perps when funding paid to shorts is elevated, long when the reverse."""
    cumulative = pd.Series(funding).rolling(window, min_periods=1).sum().to_numpy()
    state = np.zeros(len(cumulative), dtype="int8")
    state[cumulative > threshold] = -1
    state[cumulative < -threshold] = 1
    return state


def random_entry(n: int, seed: int, flip_prob: float = 0.05) -> np.ndarray:
    rng = np.random.default_rng(seed)
    choices = np.array([-1, 0, 1], dtype="int8")
    state = np.zeros(n, dtype="int8")
    current = 0
    for i in range(n):
        if rng.random() < flip_prob:
            current = int(rng.choice(choices))
        state[i] = current
    return state


def buy_hold(n: int, warmup: int = 1) -> np.ndarray:
    """Benchmark: always long. Not a strategy under test."""
    state = np.ones(n, dtype="int8")
    state[:warmup] = 0
    return state


STRATEGIES = ("ma_trend", "bollinger_mr", "donchian", "funding_carry", "random_entry")
BENCHMARKS = ("buy_hold",)


def build(name: str, df: pd.DataFrame, funding: np.ndarray, seed: int) -> np.ndarray:
    if name == "ma_trend":
        return ma_trend(df)
    if name == "bollinger_mr":
        return bollinger_mr(df)
    if name == "donchian":
        return donchian(df)
    if name == "funding_carry":
        return funding_carry(df, funding)
    if name == "random_entry":
        return random_entry(len(df), seed)
    if name == "buy_hold":
        return buy_hold(len(df))
    raise ValueError(f"unknown strategy: {name}")
