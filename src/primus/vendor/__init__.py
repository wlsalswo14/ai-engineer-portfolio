"""Frozen third-party evaluator sources, pinned by digest.

Primus used to reach into a mutable external checkout at evaluation time, so the
"frozen evaluation contract" actually tracked whatever that working tree happened
to contain. The sources now live here and are verified against VENDOR.json before
they are importable.
"""

from __future__ import annotations

import sys
from pathlib import Path

from primus.errors import IntegrityError
from primus.jsonutil import file_hash, read_json

VENDOR_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = VENDOR_ROOT / "VENDOR.json"


def manifest() -> dict:
    return read_json(MANIFEST_PATH)


def verify(component: str = "chessbench-evaluator") -> list[str]:
    """Check every pinned file against its recorded digest.

    Returns one digest line per file so `doctor` can report what it verified.
    """
    payload = manifest()
    if payload.get("component") != component:
        raise IntegrityError(
            f"vendor manifest is for {payload.get('component')!r}, not {component!r}"
        )
    files = payload.get("files") or {}
    if not files:
        raise IntegrityError("vendor manifest pins no files")
    checks: list[str] = []
    for relative, expected in sorted(files.items()):
        path = VENDOR_ROOT / relative
        if not path.is_file():
            raise IntegrityError(f"vendored source is missing: {relative}")
        actual = file_hash(path)
        if actual != expected:
            raise IntegrityError(
                f"vendored source digest mismatch: {relative} "
                f"expected {expected[:16]} got {actual[:16]}"
            )
        checks.append(f"{relative}:{actual[:16]}")
    return checks


def activate(component: str = "chessbench-evaluator") -> Path:
    """Verify the pinned sources, then put them ahead of anything installed.

    The frozen copy must win over an installed or externally checked-out
    `loop_evolution`, otherwise the evaluation contract is not actually frozen.
    """
    verify(component)
    entry = str(VENDOR_ROOT)
    while entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)
    return VENDOR_ROOT
