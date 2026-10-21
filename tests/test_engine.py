"""Behavioural tests for the execution simulator.

Run with: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qe_study.engine import simulate  # noqa: E402
from qe_study.rules import GuardConfig  # noqa: E402

HOUR = 3_600_000
N = 200


def _flat_series(price: float = 100.0) -> tuple[np.ndarray, ...]:
    arr = np.full(N, price, dtype="float64")
    ts = np.arange(N, dtype="int64") * HOUR
    funding = np.zeros(N, dtype="float64")
    return arr, arr, arr, arr, ts, funding


class CapTest(unittest.TestCase):
    def test_cap_bounds_gross_exposure(self) -> None:
        open_, high, low, close, ts, funding = _flat_series()
        states = np.ones(N, dtype="int8")

        capped = simulate(open_, high, low, close, ts, funding, states,
                          GuardConfig(name="cap", exposure_cap=1.0), seed=1)
        uncapped = simulate(open_, high, low, close, ts, funding, states,
                            GuardConfig(name="five", leverage=5.0), seed=1)

        self.assertLessEqual(capped.max_gross_leverage, 1.001)
        self.assertGreater(uncapped.max_gross_leverage, 4.9)


class DedupeTest(unittest.TestCase):
    def test_dedupe_prevents_doubled_entry(self) -> None:
        open_, high, low, close, ts, funding = _flat_series()
        states = np.ones(N, dtype="int8")
        base = dict(leverage=1.0, duplicate_prob=1.0)

        blocked = simulate(open_, high, low, close, ts, funding, states,
                           GuardConfig(name="dedupe", dedupe=True, **base), seed=7)
        replayed = simulate(open_, high, low, close, ts, funding, states,
                            GuardConfig(name="nodedupe", dedupe=False, **base), seed=7)

        self.assertGreaterEqual(blocked.duplicates_blocked, 1)
        self.assertEqual(blocked.duplicates_executed, 0)
        self.assertGreaterEqual(replayed.duplicates_executed, 1)
        self.assertAlmostEqual(blocked.max_gross_leverage, 1.0, places=2)
        self.assertAlmostEqual(replayed.max_gross_leverage, 2.0, places=2)


class KillSwitchTest(unittest.TestCase):
    def test_daily_limit_flattens_position(self) -> None:
        open_, high, low, close, ts, funding = _flat_series()
        for idx, px in ((2, 90.0), (3, 90.0), (4, 70.0)):
            open_[idx:] = px
            high[idx:] = px
            low[idx:] = px
            close[idx:] = px
        states = np.ones(N, dtype="int8")

        killed = simulate(open_, high, low, close, ts, funding, states,
                          GuardConfig(name="kill", daily_loss_limit=0.05), seed=3)
        untouched = simulate(open_, high, low, close, ts, funding, states,
                             GuardConfig(name="control"), seed=3)

        self.assertEqual(killed.halts, 1)
        self.assertEqual(untouched.halts, 0)
        # after the kill switch flattens, further falls no longer hurt it
        self.assertGreater(killed.equity[-1], untouched.equity[-1])


class NoLookAheadTest(unittest.TestCase):
    def test_signal_is_executed_one_bar_later(self) -> None:
        open_, high, low, close, ts, funding = _flat_series()
        open_[1:] = 200.0
        high[1:] = 200.0
        low[1:] = 200.0
        close[1:] = 200.0
        # state turns long only at the last bar: no trade should happen
        states = np.zeros(N, dtype="int8")
        states[-1] = 1

        result = simulate(open_, high, low, close, ts, funding, states,
                          GuardConfig(name="cap", exposure_cap=1.0), seed=5)
        self.assertEqual(result.orders, 0)
        self.assertAlmostEqual(result.equity[-1], 10_000.0, places=6)


if __name__ == "__main__":
    unittest.main()
