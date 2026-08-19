from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from loop_evolution.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
