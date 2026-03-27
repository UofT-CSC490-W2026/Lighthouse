#!/usr/bin/env python3
"""Compatibility wrapper for the packaged dataset-indexing CLI."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lighthouse_eval.cli.index_dataset import main


if __name__ == "__main__":
    main()
