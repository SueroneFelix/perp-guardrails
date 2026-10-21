#!/usr/bin/env python
"""Entry point so the study runs without installing the package."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from qe_study.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
