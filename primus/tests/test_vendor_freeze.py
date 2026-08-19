from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from primus.errors import IntegrityError
from primus.jsonutil import file_hash
from primus.vendor import MANIFEST_PATH, VENDOR_ROOT, activate, manifest, verify

ROOT = Path(__file__).resolve().parents[1]


def test_every_pinned_file_matches_its_digest() -> None:
    checks = verify("chessbench-evaluator")
    assert len(checks) == len(manifest()["files"])


def test_manifest_covers_every_vendored_python_file() -> None:
    """A file added to the frozen tree but not to the manifest would be unpinned.

    Only the upstream subtree is pinned; `primus/vendor/__init__.py` is the
    first-party loader and is covered by version control instead.
    """
    pinned = {(VENDOR_ROOT / name).resolve() for name in manifest()["files"]}
    present = {
        path.resolve()
        for path in (VENDOR_ROOT / "loop_evolution").rglob("*.py")
        if "__pycache__" not in path.parts
    }
    assert present == pinned


def test_verify_rejects_a_modified_source(tmp_path: Path) -> None:
    target = VENDOR_ROOT / "loop_evolution" / "platform" / "common.py"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# drift\n")
        with pytest.raises(IntegrityError):
            verify("chessbench-evaluator")
    finally:
        target.write_bytes(original)
    assert file_hash(target) == manifest()["files"]["loop_evolution/platform/common.py"]


def test_verify_rejects_a_missing_source() -> None:
    target = VENDOR_ROOT / "loop_evolution" / "platform" / "runtime" / "answers.py"
    original = target.read_bytes()
    try:
        target.unlink()
        with pytest.raises(IntegrityError):
            verify("chessbench-evaluator")
    finally:
        target.write_bytes(original)


def test_scorer_imports_from_the_frozen_tree_only() -> None:
    """The scorer must resolve inside primus, never from an external checkout."""
    code = (
        "import json, sys;"
        "from primus.vendor import activate;"
        "activate('chessbench-evaluator');"
        "import loop_evolution.platform.evaluation.chessbench as m;"
        "from loop_evolution.platform.evaluation.chessbench import ChessBench100Scorer;"
        "print(json.dumps(m.__file__))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={"PYTHONPATH": str(ROOT / "src"), "SYSTEMROOT": "C:\\Windows", "PATH": ""},
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    resolved = Path(json.loads(completed.stdout.strip())).resolve()
    assert resolved.is_relative_to(VENDOR_ROOT)


def test_no_source_reaches_into_an_external_checkout() -> None:
    """`ouroboros_source` was the runtime coupling; only migration may name it."""
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        if "__pycache__" in path.parts or path.is_relative_to(VENDOR_ROOT):
            continue
        text = path.read_text(encoding="utf-8")
        if "ouroboros_source" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_chess_domain_config_names_no_host_path() -> None:
    evaluator = json.loads(
        (ROOT / "config" / "domains" / "chess.json").read_text(encoding="utf-8")
    )["evaluator"]
    assert evaluator["scorer"] == "vendor:chessbench-evaluator"
    assert not any(
        isinstance(value, str) and (":\\" in value or ":/" in value)
        for value in evaluator.values()
    )


def test_manifest_records_reproducible_provenance() -> None:
    upstream = manifest()["upstream"]
    assert upstream["verbatim"] is True
    for key in ("project", "version", "commit", "source_root", "vendored_on"):
        assert upstream.get(key), f"missing provenance: {key}"
    assert MANIFEST_PATH.is_file()


def test_activate_puts_the_frozen_tree_first() -> None:
    root = activate("chessbench-evaluator")
    assert sys.path[0] == str(VENDOR_ROOT) == str(root)
    assert sys.path.count(str(VENDOR_ROOT)) == 1
