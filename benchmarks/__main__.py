"""Entry point for ``python -m benchmarks``."""

from __future__ import annotations

import sys

from benchmarks.cli import main

if __name__ == "__main__":
    sys.exit(main())
