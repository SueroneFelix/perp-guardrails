"""The CLI must not let a partial config matrix overwrite published tables.

Run with: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qe_study.cli import main  # noqa: E402


class TagGuardTest(unittest.TestCase):
    def test_config_subset_without_tag_is_refused(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(["run", "--configs", "control,cap_1x"])
        self.assertIn("--tag", str(raised.exception))

    def test_config_subset_with_tag_gets_past_the_guard(self) -> None:
        # a start date after the cached data yields no rows, so the run stops at
        # "no results" — the point is that the tag guard did not fire
        with self.assertRaises(SystemExit) as raised:
            main([
                "run", "--configs", "control", "--tag", "leverage",
                "--symbols", "BTCUSDT", "--start", "2030-01-01T00:00:00Z",
            ])
        self.assertNotIn("needs --tag", str(raised.exception))
        self.assertIn("no results", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
