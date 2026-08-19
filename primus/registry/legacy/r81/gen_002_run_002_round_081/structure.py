#!/usr/bin/env python3
"""Meta23 Run 2 Round 81 candidate loop and evidence harness.

The harness is intentionally self-contained.  It can be run as
``round_81/code.py`` or as a copied ``solver_code.py`` and still emits the same
package manifest, mock structural evidence, live Codex grid artifacts, prior
replay audits, and release validators.

Promotion evidence is fail-closed: deterministic mock evidence can validate the
runner, scorer audit, caps, packaging, and negative controls, but
``--release-gate --require-live`` only passes for a full current-round Codex
``gpt-5.5``/``xhigh`` actor grid with raw prompt/response/process/parsed
artifacts.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True


ROUND = 81
SCHEMA_VERSION = 81
CANDIDATE_ID = "candidate_r81_public_audit_bootstrap_loop"
CURRENT_CHAMPION = "gen_001_run_001_round_013"
VERIFIER_REVISION = "r81_public_audit_bootstrap_v1"
GRID_RUN_ID = "r81_fresh_codex_grid_v1"
TMP_PREFIX = f"/tmp/meta23_r{ROUND}"
LIVE_ARTIFACT_DIR = f"{TMP_PREFIX}_live_codex_final"
LIVE_COMPARE_PATH = f"{TMP_PREFIX}_live_codex_final_compare.json"

FAMILIES = ("patch_state_machine_code", "semantic_role_retrieval_code", "intent_scorer_policy_code")
SEEDS = (11, 23, 37)
LIVE_RELEASE_SEEDS = (11, 37)
POLICIES = (
    "one_shot",
    CANDIDATE_ID,
    "candidate_redacted_only",
    "candidate_no_scorer_audit",
    "candidate_no_goal_ledger",
    "candidate_no_public_audit_bootstrap",
    "current_champion",
    "r13_current_champion",
    "r38_bare_goal",
    "r133_bare_goal",
    "older_baseline",
    "bad_scorer_control",
)
REQUIRED_PRIOR_POLICIES = (
    "one_shot",
    "older_baseline",
    "r133_bare_goal",
    "r38_bare_goal",
    "r13_current_champion",
    "current_champion",
)
ABLATION_POLICIES = (
    "candidate_redacted_only",
    "candidate_no_scorer_audit",
    "candidate_no_goal_ledger",
    "candidate_no_public_audit_bootstrap",
)
CAPS = {
    "max_rounds": 4,
    "max_calls": 4,
    "timeout_sec": 900,
    "wall_clock_cap_sec": 7200,
    "no_progress_patience": 2,
    "repeated_failure_stop": 2,
    "pass_threshold": 100.0,
    "cost_cap_usd": 48.0,
    "estimated_cost_per_live_call_usd": 0.18,
    "live_batch_size": 1,
}


@dataclasses.dataclass(frozen=True)
class Task:
    family: str
    seed: int
    public_goal: str
    public_cases: list[dict[str, Any]]
    truth: dict[str, Any]
    audit_cases: dict[str, Any]


def stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def digest(data: Any) -> str:
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = stable_json(data).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: str | Path | None, data: Any) -> None:
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def workspace_root() -> Path:
    """Find the scorer-bench workspace even when this file is copied as solver_code.py."""
    markers = (
        Path("reference_materials") / "generation_history.json",
        Path("final_requirement.md"),
    )
    candidates: list[Path] = []
    actual = Path(__file__).resolve()
    candidates.extend(actual.parents)
    candidates.append(Path.cwd().resolve())
    candidates.extend(Path.cwd().resolve().parents)
    for root in candidates:
        if all((root / marker).exists() for marker in markers):
            return root
    return Path.cwd().resolve()


def reference_materials_root() -> Path:
    """Locate prior/champion references in solver_dir or copied evaluator packages."""
    candidates: list[Path] = []
    actual = Path(__file__).resolve()
    candidates.extend(actual.parents)
    candidates.append(Path.cwd().resolve())
    candidates.extend(Path.cwd().resolve().parents)
    for root in candidates:
        for rel in (Path("reference_materials"), Path("baseline_reference") / "reference_materials"):
            ref = root / rel
            if (ref / "generation_history.json").exists():
                return ref
    return workspace_root() / "reference_materials"


def csv_list(value: str | None, default: Iterable[str | int]) -> list[str]:
    if not value:
        return [str(item) for item in default]
    return [part.strip() for part in value.split(",") if part.strip()]


def script_ref() -> str:
    canonical = Path.cwd() / f"round_{ROUND}" / "code.py"
    actual = Path(__file__).resolve()
    if canonical.exists() and actual == canonical.resolve():
        return f"round_{ROUND}/code.py"
    try:
        return str(actual.relative_to(Path.cwd()))
    except ValueError:
        return str(actual)


def py_cmd(*parts: str) -> str:
    return " ".join(["python3", "-B", script_ref(), *parts])


def command_manifest() -> dict[str, str]:
    actor_env = (
        "META23_ROLE_CLI=codex CODEX_MODEL=gpt-5.5 CODEX_REASONING_EFFORT=xhigh "
        "INNER_ACTOR_CLI=codex INNER_ACTOR_MODEL=gpt-5.5"
    )
    return {
        "self_test": py_cmd("--self-test", "--out", f"{TMP_PREFIX}_selftest.json"),
        "scorer_audit": py_cmd("--scorer-audit", "--out", f"{TMP_PREFIX}_scorer_audit.json"),
        "compare_mock": py_cmd(
            "--compare-baseline",
            "--actor-mode",
            "mock",
            "--artifact-dir",
            f"{TMP_PREFIX}_mock_artifacts",
            "--out",
            f"{TMP_PREFIX}_mock_compare.json",
        ),
        "mock_release_gate": py_cmd(
            "--release-gate",
            "--compare",
            f"{TMP_PREFIX}_mock_compare.json",
            "--out",
            f"{TMP_PREFIX}_mock_release_gate.json",
        ),
        "mock_as_live_negative_gate": py_cmd(
            "--release-gate",
            "--compare",
            f"{TMP_PREFIX}_mock_compare.json",
            "--require-live",
            "--out",
            f"{TMP_PREFIX}_mock_as_live_gate.json",
        ),
        "live_direct_probe": (
            f"{actor_env} "
            + py_cmd(
                "--direct-actor-probe",
                "--live-exec",
                "--actor-mode",
                "codex",
                "--actor-cli",
                "codex",
                "--model",
                "gpt-5.5",
                "--reasoning-effort",
                "xhigh",
                "--timeout-sec",
                "300",
                "--artifact-dir",
                f"{TMP_PREFIX}_direct_probe",
                "--out",
                f"{TMP_PREFIX}_direct_probe.json",
            )
        ),
        "live_codex_grid": (
            f"{actor_env} "
            + py_cmd(
                "--compare-baseline",
                "--live-exec",
                "--actor-mode",
                "codex",
                "--actor-cli",
                "codex",
                "--model",
                "gpt-5.5",
                "--reasoning-effort",
                "xhigh",
                "--max-rounds",
                str(CAPS["max_rounds"]),
                "--max-calls",
                str(CAPS["max_calls"]),
                "--timeout-sec",
                str(CAPS["timeout_sec"]),
                "--wall-clock-cap-sec",
                str(CAPS["wall_clock_cap_sec"]),
                "--cost-cap-usd",
                str(CAPS["cost_cap_usd"]),
                "--live-batch-size",
                str(CAPS["live_batch_size"]),
                "--seeds",
                ",".join(str(s) for s in LIVE_RELEASE_SEEDS),
                "--artifact-dir",
                LIVE_ARTIFACT_DIR,
                "--out",
                LIVE_COMPARE_PATH,
            )
        ),
        "live_release_evidence_bundle": (
            f"{actor_env} "
            + py_cmd(
                "--release-evidence",
                "--live-exec",
                "--actor-mode",
                "codex",
                "--actor-cli",
                "codex",
                "--model",
                "gpt-5.5",
                "--reasoning-effort",
                "xhigh",
                "--max-rounds",
                str(CAPS["max_rounds"]),
                "--max-calls",
                str(CAPS["max_calls"]),
                "--timeout-sec",
                str(CAPS["timeout_sec"]),
                "--wall-clock-cap-sec",
                str(CAPS["wall_clock_cap_sec"]),
                "--cost-cap-usd",
                str(CAPS["cost_cap_usd"]),
                "--live-batch-size",
                str(CAPS["live_batch_size"]),
                "--seeds",
                ",".join(str(s) for s in LIVE_RELEASE_SEEDS),
                "--artifact-dir",
                LIVE_ARTIFACT_DIR,
                "--compare",
                LIVE_COMPARE_PATH,
                "--out",
                f"{TMP_PREFIX}_release_evidence_manifest.json",
            )
        ),
        "live_cap_negative_release_evidence": (
            f"{actor_env} "
            + py_cmd(
                "--release-evidence",
                "--live-exec",
                "--actor-mode",
                "codex",
                "--actor-cli",
                "codex",
                "--model",
                "gpt-5.5",
                "--reasoning-effort",
                "xhigh",
                "--max-rounds",
                str(CAPS["max_rounds"]),
                "--max-calls",
                str(CAPS["max_calls"]),
                "--timeout-sec",
                "60",
                "--wall-clock-cap-sec",
                "65",
                "--cost-cap-usd",
                "0.6",
                "--live-batch-size",
                str(CAPS["live_batch_size"]),
                "--seeds",
                ",".join(str(s) for s in LIVE_RELEASE_SEEDS),
                "--artifact-dir",
                f"{TMP_PREFIX}_live_cap_negative",
                "--compare",
                f"{TMP_PREFIX}_live_cap_negative_compare.json",
                "--out",
                f"{TMP_PREFIX}_live_cap_negative_manifest.json",
            )
        ),
        "live_one_shot_calibration": (
            f"{actor_env} "
            + py_cmd(
                "--compare-baseline",
                "--live-exec",
                "--actor-mode",
                "codex",
                "--actor-cli",
                "codex",
                "--model",
                "gpt-5.5",
                "--reasoning-effort",
                "xhigh",
                "--max-rounds",
                "1",
                "--max-calls",
                "1",
                "--timeout-sec",
                str(CAPS["timeout_sec"]),
                "--wall-clock-cap-sec",
                "1800",
                "--cost-cap-usd",
                "1.0",
                "--live-batch-size",
                str(CAPS["live_batch_size"]),
                "--families",
                ",".join(FAMILIES),
                "--seeds",
                ",".join(str(s) for s in SEEDS),
                "--policies",
                "one_shot",
                "--artifact-dir",
                f"{TMP_PREFIX}_live_calibration_one_shot",
                "--out",
                f"{TMP_PREFIX}_live_calibration_one_shot_compare.json",
            )
        ),
        "live_candidate_probe": (
            f"{actor_env} "
            + py_cmd(
                "--compare-baseline",
                "--live-exec",
                "--actor-mode",
                "codex",
                "--actor-cli",
                "codex",
                "--model",
                "gpt-5.5",
                "--reasoning-effort",
                "xhigh",
                "--max-rounds",
                str(CAPS["max_rounds"]),
                "--max-calls",
                str(CAPS["max_calls"]),
                "--timeout-sec",
                "600",
                "--wall-clock-cap-sec",
                "2400",
                "--cost-cap-usd",
                "3.5",
                "--live-batch-size",
                str(CAPS["live_batch_size"]),
                "--families",
                ",".join(FAMILIES),
                "--seeds",
                ",".join(str(s) for s in LIVE_RELEASE_SEEDS),
                "--policies",
                CANDIDATE_ID,
                "--artifact-dir",
                f"{TMP_PREFIX}_live_candidate_probe",
                "--out",
                f"{TMP_PREFIX}_live_candidate_probe_compare.json",
            )
        ),
        "truth_separation_audit": py_cmd(
            "--truth-separation-audit",
            "--compare",
            LIVE_COMPARE_PATH,
            "--out",
            f"{TMP_PREFIX}_truth_separation_audit.json",
        ),
        "task_bank_audit": py_cmd("--task-bank-audit", "--out", f"{TMP_PREFIX}_task_bank_audit.json"),
        "prior_artifact_audit": py_cmd("--prior-artifact-audit", "--out", f"{TMP_PREFIX}_prior_artifact_audit.json"),
        "prior_replay_audit": py_cmd("--prior-replay-audit", "--out", f"{TMP_PREFIX}_prior_replay_audit.json"),
        "live_release_gate": py_cmd(
            "--release-gate",
            "--compare",
            LIVE_COMPARE_PATH,
            "--require-live",
            "--expected-actor-mode",
            "codex",
            "--expected-model",
            "gpt-5.5",
            "--expected-reasoning-effort",
            "xhigh",
            "--out",
            f"{TMP_PREFIX}_live_release_gate.json",
        ),
        "live_cap_negative_gate": py_cmd(
            "--release-gate",
            "--compare",
            f"{TMP_PREFIX}_live_cap_negative_compare.json",
            "--require-live",
            "--expected-actor-mode",
            "codex",
            "--expected-model",
            "gpt-5.5",
            "--expected-reasoning-effort",
            "xhigh",
            "--out",
            f"{TMP_PREFIX}_live_cap_negative_gate.json",
        ),
        "partial_live_status": py_cmd(
            "--partial-live-status",
            "--artifact-dir",
            LIVE_ARTIFACT_DIR,
            "--out",
            f"{TMP_PREFIX}_partial_live_status.json",
        ),
        "emit_package": py_cmd("--emit-package", "--out", f"{TMP_PREFIX}_candidate.json"),
        "validate_package": py_cmd(
            "--validate-package",
            "--package",
            f"{TMP_PREFIX}_candidate.json",
            "--out",
            f"{TMP_PREFIX}_package_validation.json",
        ),
    }


def file_provenance(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "sha256": digest(path.read_bytes()) if exists else None,
        "bytes": path.stat().st_size if exists else 0,
    }


def prior_policy_provenance() -> dict[str, Any]:
    ref = reference_materials_root()
    root = workspace_root()
    return {
        "one_shot": {
            "kind": "live_control",
            "description": "bare public goal single-call control; no prior loop behavior is injected",
            "references": [],
        },
        "older_baseline": {
            "kind": "baseline_family_reference",
            "description": "older direct bare-goal baseline described in the final requirement",
            "references": [file_provenance(root / "final_requirement.md")],
        },
        "r133_bare_goal": {
            "kind": "prior_loop_reference",
            "description": "r133/minus23 private-eval baseline as specified in final_requirement.md",
            "references": [file_provenance(root / "final_requirement.md")],
        },
        "r38_bare_goal": {
            "kind": "prior_loop_artifact",
            "description": "r38 audited public feedback-channel reference artifacts",
            "references": [
                file_provenance(ref / "r38_feedback_channel_reference" / "REFERENCE.md"),
                file_provenance(ref / "r38_feedback_channel_reference" / "r38_code.py"),
                file_provenance(ref / "r38_feedback_channel_reference" / "r38_explanation.md"),
            ],
        },
        "r13_current_champion": {
            "kind": "prior_loop_artifact",
            "description": "r13 concrete-counterexample and independent-truth reference artifacts",
            "references": [
                file_provenance(ref / "r13_concrete_counterexample_reference" / "REFERENCE.md"),
                file_provenance(ref / "r13_concrete_counterexample_reference" / "r13_code.py"),
                file_provenance(ref / "r13_concrete_counterexample_reference" / "r13_explanation.md"),
            ],
        },
        "current_champion": {
            "kind": "champion_artifact",
            "description": f"current champion {CURRENT_CHAMPION} registry artifacts",
            "references": [
                file_provenance(ref / "generation_history.json"),
                file_provenance(ref / "current_champion" / "REFERENCE.md"),
                file_provenance(ref / "current_champion" / "code.py"),
                file_provenance(ref / "current_champion" / "explanation.md"),
            ],
        },
    }


def policy_provenance_audit(compare: dict[str, Any]) -> dict[str, Any]:
    provenance = compare.get("policy_provenance", {})
    bad: list[dict[str, Any]] = []
    for policy in REQUIRED_PRIOR_POLICIES:
        item = provenance.get(policy)
        if not isinstance(item, dict):
            bad.append({"policy": policy, "error": "missing_policy_provenance"})
            continue
        if policy != "one_shot":
            refs = item.get("references", [])
            if not refs:
                bad.append({"policy": policy, "error": "missing_reference_rows"})
            for ref in refs:
                if not ref.get("exists") or not ref.get("sha256"):
                    bad.append({"policy": policy, "error": "missing_reference_file", "path": ref.get("path")})
    return {"ok": not bad, "bad": bad[:20], "checked": list(REQUIRED_PRIOR_POLICIES)}


def case(case_id: str, inp: Any, expected: Any) -> dict[str, Any]:
    return {"case_id": case_id, "input": inp, "expected": expected}


def patch_task(seed: int) -> Task:
    b = seed % 4
    public_cases = [
        case(
            "public_add_erase_shift",
            [
                {"op": "add", "label": "A", "lo": b, "hi": b + 2, "delta": 2},
                {"op": "erase", "label": "A", "lo": b + 1, "hi": b + 1},
                {"op": "shift", "label": "A", "lo": b + 2, "hi": b + 2, "offset": 1},
            ],
            [{"label": "A", "lo": b, "hi": b, "value": 2}, {"label": "A", "lo": b + 3, "hi": b + 3, "value": 2}],
        ),
        case(
            "public_zero_cancel_and_all_label_erase",
            [
                {"op": "add", "label": "A", "lo": 0, "hi": 1, "delta": 3},
                {"op": "add", "label": "A", "lo": 1, "hi": 2, "delta": -3},
                {"op": "add", "label": "B", "lo": 1, "hi": 1, "delta": 5},
                {"op": "erase", "lo": 1, "hi": 1},
            ],
            [{"label": "A", "lo": 0, "hi": 0, "value": 3}, {"label": "A", "lo": 2, "hi": 2, "value": -3}],
        ),
    ]
    feedback_cases = [
        case(
            "feedback_copy_collision_and_zero_prune",
            [
                {"op": "add", "label": "S", "lo": 0, "hi": 2, "delta": 1},
                {"op": "add", "label": "T", "lo": 1, "hi": 3, "delta": -1},
                {"op": "copy", "src": "S", "dst": "T", "lo": 0, "hi": 2, "offset": 1},
            ],
            [{"label": "S", "lo": 0, "hi": 2, "value": 1}],
        ),
        case(
            "feedback_snapshot_restore_is_undoable",
            [
                {"op": "add", "label": "R", "lo": 0, "hi": 2, "delta": 4},
                {"op": "snap", "name": "base"},
                {"op": "erase", "label": "R", "lo": 1, "hi": 1},
                {"op": "restore", "name": "base"},
                {"op": "undo", "n": 1},
            ],
            [{"label": "R", "lo": 0, "hi": 0, "value": 4}, {"label": "R", "lo": 2, "hi": 2, "value": 4}],
        ),
        case(
            "feedback_shift_must_remove_source_before_collision",
            [
                {"op": "add", "label": "X", "lo": 0, "hi": 2, "delta": 2},
                {"op": "add", "label": "X", "lo": 3, "hi": 3, "delta": 5},
                {"op": "shift", "label": "X", "lo": 0, "hi": 2, "offset": 1},
            ],
            [{"label": "X", "lo": 1, "hi": 2, "value": 2}, {"label": "X", "lo": 3, "hi": 3, "value": 7}],
        ),
        case(
            "feedback_rename_collision_and_zero_prune",
            [
                {"op": "add", "label": "A", "lo": 0, "hi": 1, "delta": 5},
                {"op": "add", "label": "B", "lo": 1, "hi": 2, "delta": -5},
                {"op": "rename", "src": "A", "dst": "B", "lo": 0, "hi": 1},
            ],
            [{"label": "B", "lo": 0, "hi": 0, "value": 5}, {"label": "B", "lo": 2, "hi": 2, "value": -5}],
        ),
        case(
            "feedback_scale_truncates_toward_zero",
            [
                {"op": "add", "label": "S", "lo": 0, "hi": 0, "delta": -3},
                {"op": "add", "label": "S", "lo": 1, "hi": 1, "delta": 5},
                {"op": "scale", "label": "S", "lo": 0, "hi": 1, "num": 1, "den": 2},
            ],
            [{"label": "S", "lo": 0, "hi": 0, "value": -1}, {"label": "S", "lo": 1, "hi": 1, "value": 2}],
        ),
        case(
            "feedback_undo_ignores_snapshots",
            [
                {"op": "add", "label": "U", "lo": 0, "hi": 0, "delta": 1},
                {"op": "snap", "name": "s1"},
                {"op": "add", "label": "U", "lo": 1, "hi": 1, "delta": 1},
                {"op": "undo", "n": 1},
            ],
            [{"label": "U", "lo": 0, "hi": 0, "value": 1}],
        ),
        case(
            "feedback_reflect_collision_source_removed",
            [
                {"op": "add", "label": "R", "lo": 0, "hi": 2, "delta": 2},
                {"op": "add", "label": "R", "lo": 4, "hi": 4, "delta": 3},
                {"op": "reflect", "label": "R", "lo": 0, "hi": 2, "pivot": 4},
            ],
            [{"label": "R", "lo": 2, "hi": 3, "value": 2}, {"label": "R", "lo": 4, "hi": 4, "value": 5}],
        ),
        case(
            "feedback_threshold_is_undoable_and_prunes_by_abs_value",
            [
                {"op": "add", "label": "T", "lo": 0, "hi": 0, "delta": 1},
                {"op": "add", "label": "T", "lo": 1, "hi": 1, "delta": -2},
                {"op": "add", "label": "T", "lo": 2, "hi": 2, "delta": 3},
                {"op": "threshold", "label": "T", "lo": 0, "hi": 2, "min_abs": 2},
                {"op": "undo", "n": 1},
            ],
            [
                {"label": "T", "lo": 0, "hi": 0, "value": 1},
                {"label": "T", "lo": 1, "hi": 1, "value": -2},
                {"label": "T", "lo": 2, "hi": 2, "value": 3},
            ],
        ),
        case(
            "feedback_swap_exchanges_sparse_labels",
            [
                {"op": "add", "label": "A", "lo": 0, "hi": 1, "delta": 2},
                {"op": "add", "label": "B", "lo": 1, "hi": 2, "delta": 5},
                {"op": "swap", "label_a": "A", "label_b": "B", "lo": 0, "hi": 2},
            ],
            [{"label": "B", "lo": 0, "hi": 1, "value": 2}, {"label": "A", "lo": 1, "hi": 2, "value": 5}],
        ),
        case(
            "feedback_cross_label_span_merge_after_final_sort",
            [
                {"op": "add", "label": "B", "lo": 0, "hi": 1, "delta": 1},
                {"op": "add", "label": "A", "lo": 0, "hi": 1, "delta": 1},
                {"op": "erase", "label": "B", "lo": 1, "hi": 1},
            ],
            [{"label": "A", "lo": 0, "hi": 1, "value": 1}, {"label": "B", "lo": 0, "hi": 0, "value": 1}],
        ),
    ]
    hidden = {
        "hidden_restore_then_copy": case(
            "hidden_restore_then_copy",
            [
                {"op": "add", "label": "A", "lo": 0, "hi": 2, "delta": 2},
                {"op": "snap", "name": "keep"},
                {"op": "erase", "lo": 1, "hi": 1},
                {"op": "copy", "src": "A", "dst": "B", "lo": 0, "hi": 2, "offset": 10},
                {"op": "restore", "name": "keep"},
                {"op": "copy", "src": "A", "dst": "B", "lo": 1, "hi": 2, "offset": -1},
            ],
            [{"label": "A", "lo": 0, "hi": 2, "value": 2}, {"label": "B", "lo": 0, "hi": 1, "value": 2}],
        ),
        "hidden_shift_collision_zero": case(
            "hidden_shift_collision_zero",
            [
                {"op": "add", "label": "K", "lo": -2, "hi": 0, "delta": 3},
                {"op": "add", "label": "K", "lo": 1, "hi": 1, "delta": -3},
                {"op": "shift", "label": "K", "lo": -2, "hi": 0, "offset": 3},
            ],
            [{"label": "K", "lo": 2, "hi": 3, "value": 3}],
        ),
        "hidden_undo_restore_and_shift": case(
            "hidden_undo_restore_and_shift",
            [
                {"op": "add", "label": "M", "lo": 5, "hi": 7, "delta": 1},
                {"op": "snap", "name": "m"},
                {"op": "shift", "label": "M", "lo": 5, "hi": 6, "offset": 10},
                {"op": "restore", "name": "m"},
                {"op": "undo", "n": 2},
            ],
            [{"label": "M", "lo": 5, "hi": 7, "value": 1}],
        ),
        "hidden_same_label_same_value_merge_only": case(
            "hidden_same_label_same_value_merge_only",
            [
                {"op": "add", "label": "C", "lo": 0, "hi": 0, "delta": 1},
                {"op": "add", "label": "C", "lo": 1, "hi": 1, "delta": 2},
                {"op": "add", "label": "C", "lo": 2, "hi": 3, "delta": 2},
            ],
            [{"label": "C", "lo": 0, "hi": 0, "value": 1}, {"label": "C", "lo": 1, "hi": 3, "value": 2}],
        ),
        "hidden_scale_then_shift": case(
            "hidden_scale_then_shift",
            [
                {"op": "add", "label": "D", "lo": -1, "hi": 1, "delta": 7},
                {"op": "scale", "label": "D", "lo": -1, "hi": 0, "num": -1, "den": 3},
                {"op": "shift", "label": "D", "lo": -1, "hi": 1, "offset": 2},
            ],
            [{"label": "D", "lo": 1, "hi": 2, "value": -2}, {"label": "D", "lo": 3, "hi": 3, "value": 7}],
        ),
        "hidden_rename_undo": case(
            "hidden_rename_undo",
            [
                {"op": "add", "label": "A", "lo": 0, "hi": 2, "delta": 4},
                {"op": "rename", "src": "A", "dst": "B", "lo": 1, "hi": 2},
                {"op": "undo", "n": 1},
            ],
            [{"label": "A", "lo": 0, "hi": 2, "value": 4}],
        ),
        "hidden_cross_label_sorting": case(
            "hidden_cross_label_sorting",
            [
                {"op": "add", "label": "B", "lo": 0, "hi": 1, "delta": 1},
                {"op": "add", "label": "A", "lo": 0, "hi": 1, "delta": 1},
                {"op": "erase", "label": "B", "lo": 1, "hi": 1},
            ],
            [{"label": "A", "lo": 0, "hi": 1, "value": 1}, {"label": "B", "lo": 0, "hi": 0, "value": 1}],
        ),
        "hidden_reflect_collision_zero": case(
            "hidden_reflect_collision_zero",
            [
                {"op": "add", "label": "Q", "lo": -1, "hi": 1, "delta": 4},
                {"op": "add", "label": "Q", "lo": 3, "hi": 3, "delta": -4},
                {"op": "reflect", "label": "Q", "lo": -1, "hi": 1, "pivot": 2},
            ],
            [{"label": "Q", "lo": 1, "hi": 2, "value": 4}],
        ),
        "hidden_threshold_after_scale": case(
            "hidden_threshold_after_scale",
            [
                {"op": "add", "label": "Z", "lo": 0, "hi": 0, "delta": -5},
                {"op": "add", "label": "Z", "lo": 1, "hi": 1, "delta": 4},
                {"op": "add", "label": "Z", "lo": 2, "hi": 2, "delta": 1},
                {"op": "scale", "label": "Z", "lo": 0, "hi": 2, "num": 1, "den": 2},
                {"op": "threshold", "label": "Z", "lo": 0, "hi": 2, "min_abs": 2},
            ],
            [{"label": "Z", "lo": 0, "hi": 0, "value": -2}, {"label": "Z", "lo": 1, "hi": 1, "value": 2}],
        ),
        "hidden_swap_after_reflect": case(
            "hidden_swap_after_reflect",
            [
                {"op": "add", "label": "L", "lo": 0, "hi": 1, "delta": 6},
                {"op": "add", "label": "R", "lo": 1, "hi": 2, "delta": -2},
                {"op": "reflect", "label": "L", "lo": 0, "hi": 1, "pivot": 3},
                {"op": "swap", "label_a": "L", "label_b": "R", "lo": 1, "hi": 3},
            ],
            [{"label": "R", "lo": 2, "hi": 3, "value": 6}, {"label": "L", "lo": 1, "hi": 2, "value": -2}],
        ),
    }
    if b:
        def shifted_case(item: dict[str, Any], offset: int) -> dict[str, Any]:
            shifted = copy.deepcopy(item)
            for row in shifted["input"]:
                if isinstance(row, dict):
                    if "lo" in row:
                        row["lo"] = int(row["lo"]) + offset
                    if "hi" in row:
                        row["hi"] = int(row["hi"]) + offset
                    if "pivot" in row:
                        row["pivot"] = int(row["pivot"]) + (2 * offset)
            expected = shifted["expected"]
            if isinstance(expected, list):
                for row in expected:
                    if isinstance(row, dict):
                        if "lo" in row:
                            row["lo"] = int(row["lo"]) + offset
                        if "hi" in row:
                            row["hi"] = int(row["hi"]) + offset
            shifted["case_id"] = f"{shifted['case_id']}_seed_{seed}"
            return shifted
        hidden = {name: shifted_case(item, b * 11) for name, item in hidden.items()}
    return Task(
        family="patch_state_machine_code",
        seed=seed,
        public_goal=(
            "Return JSON with a Python code string defining solve(events). Maintain a sparse integer ledger keyed by "
            "(label, point) with signed values; zero values must disappear. Operations: add(label,lo,hi,delta) adds "
            "delta to each inclusive point; erase(lo,hi) removes all labels in the inclusive window; "
            "erase(label,lo,hi) removes only that label; shift(label,lo,hi,offset) moves that label's existing points "
            "inside the window by offset after first removing the source points, summing collisions and pruning zero; "
            "copy(src,dst,lo,hi,offset) adds src values inside the window to dst at point+offset without changing src; "
            "rename(src,dst,lo,hi) moves src values in the window to dst at the same points after first removing them "
            "from src, summing collisions and pruning zero; scale(label,lo,hi,num,den) replaces each existing value for "
            "that label/window by integer truncation toward zero of value*num/den and removes zeros; "
            "reflect(label,lo,hi,pivot) moves that label's existing points p in the inclusive window to pivot-p after "
            "first removing the source points, summing collisions and pruning zero; threshold(label,lo,hi,min_abs) "
            "removes that label's existing points in the window when abs(value) is smaller than min_abs; "
            "snap(name) stores a named snapshot and is not undoable; restore(name) restores a snapshot, is undoable, "
            "and restores empty state for an unknown name; undo(n) reverts the last n undoable mutating events. "
            "Return sorted spans {label,lo,hi,value}; merge adjacent points with the same label and same value even "
            "when another label at an overlapping point would interleave in the final sort. A robust way is to group "
            "points by (label,value), merge consecutive point runs inside each group, then sort spans by lo, then label, "
            "then value."
        ),
        public_cases=public_cases,
        truth=hidden,
        audit_cases={"entrypoint": "solve", "feedback_cases": feedback_cases},
    )


def retrieval_task(seed: int) -> Task:
    s = seed % 9
    public_records = [
        {"id": f"P{s}1", "text": "Victim-owner Mina lost service after a stranger obtained a replacement USIM; minutes later KakaoTalk messages were read from a new device."},
        {"id": f"P{s}2", "text": "Defendant Jae said his own phone was stolen and Kakao was abused; the bank customer was not the account owner-victim."},
        {"id": f"P{s}3", "text": "A carrier clerk lawfully reissued a SIM to the verified owner, and no third party used OTP or Kakao."},
        {"id": f"P{s}4", "text": "Training notes list SIM-swap red flags, explicitly saying the sample contains no activation and no victim account."},
    ]
    public_cases = [case("public_role_selection", public_records, [f"P{s}1"])]
    feedback_records = [
        {"id": f"F{s}1", "text": "Account holder was the victim; the accused procured a duplicate SIM, then used OTP texts to enter KakaoTalk."},
        {"id": f"F{s}2", "text": "A planned duplicate SIM request was cancelled before activation, although a memo still says Kakao might have been at risk."},
        {"id": f"F{s}3", "text": "The suspect's own account was compromised by a stranger; there is no separate owner-victim."},
        {"id": f"F{s}4", "text": "The victim owner only received a phishing link; no SIM, USIM, number transfer, or carrier reissue occurred."},
        {"id": f"F{s}5", "text": "The complainant-owner's number was ported by an impostor through a USIM replacement, then messenger login alerts appeared."},
        {"id": f"F{s}6", "text": "A stranger used a forged authorization paper to reissue the subscriber-victim's SIM and read SMS authentication for KakaoTalk."},
        {"id": f"F{s}7", "text": "The duplicate SIM enabled bank OTP interception only; the report expressly says no Kakao, messenger, SMS-authentication, or message access."},
        {"id": f"F{s}8", "text": "A textbook example mentions a victim owner and SIM swap vocabulary, but the actual file says the carrier took no action."},
        {"id": f"F{s}9", "text": "A fraudster finished a mobile-number port for the complainant's account; the replacement SIM let the intruder receive chat login notices."},
        {"id": f"F{s}10", "text": "Using forged carrier paperwork, another person reissued the subscriber victim's mobile card and used text-authentication codes to open a messaging account."},
        {"id": f"F{s}11", "text": "The accused got a second USIM tied to the owner-victim and used SMS verification to view messenger conversations."},
        {"id": f"F{s}12", "text": "A duplicate USIM was active for a victim number, but the file limits access to bank OTP interception and expressly denies messenger or chat access."},
        {"id": f"F{s}13", "text": "A messenger login alert followed a lawful owner self-service SIM change, with no different suspect or forged carrier request."},
        {"id": f"F{s}14", "text": "Forged carrier delegation paperwork was prepared, but the clerk denied the request before any SIM replacement, number port, message access, or activation."},
        {"id": f"F{s}15", "text": "A stranger reissued the account holder mobile credential with forged shop documents and intercepted text codes for a chat login."},
        {"id": f"F{s}16", "text": "A non-owner used a forged delegation letter to get the account holder's SIM reissued, then intercepted OTP texts for KakaoTalk."},
        {"id": f"F{s}17", "text": "The accused obtained a duplicate USIM for the victim-owner number; SMS authentication codes and chat archive access followed."},
    ]
    hidden_records = [
        {"id": f"H{s}1", "text": "The complainant-owner could not receive texts after an impostor completed a number-port USIM replacement; Kakao login alerts followed."},
        {"id": f"H{s}2", "text": "The defendant attempted to get a spare USIM but the carrier rejected the request, so no message or Kakao access happened."},
        {"id": f"H{s}3", "text": "The owner personally swapped her SIM at the shop after identity checks; a later Kakao login was her own."},
        {"id": f"H{s}4", "text": "A stranger used a forged letter of delegation to reissue the account holder's SIM and intercepted OTP messages for KakaoTalk."},
        {"id": f"H{s}5", "text": "Police cited a textbook SIM-swap case while discussing this file, but this file has only phishing with no carrier action."},
        {"id": f"H{s}6", "text": "The suspect was the phone subscriber and said a victim stole his SIM; there is no owner-victim whose SIM was replaced."},
        {"id": f"H{s}7", "text": "The victim's phone number was ported by someone else; the duplicate SIM enabled reading bank OTPs, not Kakao or messaging access."},
        {"id": f"H{s}8", "text": "After the accused obtained a duplicate USIM for the victim-owner's number, SMS authentication and messenger history were accessed."},
    ]
    return Task(
        family="semantic_role_retrieval_code",
        seed=seed,
        public_goal=(
            "Return JSON with a Python code string defining select(records). It must return record ids where the "
            "account owner/account holder/number subscriber is the victim, and a different suspect/defendant/stranger "
            "successfully activated, reissued, replaced, duplicated, or ported that victim's SIM/USIM/phone number, "
            "causing KakaoTalk, messenger/chat, SMS authentication, OTP, or message-code access. Duplicate USIM is a "
            "SIM/USIM action even when the text does not say duplicate SIM. Reject keyword-only matches: "
            "attempted but cancelled/rejected requests, suspect-as-victim, lawful owner self-service, training/textbook "
            "memos, phishing-only cases, records saying no activation/no carrier action occurred, and SIM events with "
            "no Kakao/messenger/SMS/OTP/message access."
        ),
        public_cases=public_cases,
        truth={"hidden_semantic_roles": case("hidden_semantic_roles", hidden_records, [f"H{s}1", f"H{s}4", f"H{s}8"])},
        audit_cases={
            "entrypoint": "select",
            "feedback_cases": [case("feedback_hard_negatives", feedback_records, [f"F{s}1", f"F{s}5", f"F{s}6", f"F{s}9", f"F{s}10", f"F{s}11", f"F{s}15", f"F{s}16", f"F{s}17"])],
        },
    )


def intent_task(seed: int) -> Task:
    salt = seed % 5
    public_candidates = [
        {
            "id": f"good_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": True,
            "active_goal_closed_by_validator": True,
            "prior_artifact_provenance": True,
            "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"],
            "hidden_leak": False,
            "benchmark_hardcode": False,
            "self_attested_final_pass": False,
            "runner_malfunction": False,
        },
        {"id": f"bad_self_pass_{salt}", "self_attested_final_pass": True, "raw_live_provenance": False},
    ]
    feedback_candidates = [
        {
            "id": f"nested_equivalent_positive_{salt}",
            "criteria": {"quantified": True},
            "verifier": {"fixed_trusted": True},
            "provenance": {
                "raw_live": True,
                "prior_artifact_hashes": {"r13": "sha-r13", "r38": "sha-r38", "current_champion": "sha-champ"},
                "simulated_baselines": False,
            },
            "caps": {"enforced": True, "max_rounds": 3, "max_calls": 3, "wall_clock_cap_sec": 7200},
            "comparison": {"same_actor": True, "actor_mode": "codex", "model": "gpt-5.5"},
            "goal": {"validator_closed": True},
            "audit": {"case_types": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"]},
        },
        {
            "id": f"artifact_list_positive_{salt}",
            "criteria": {"quantified": True},
            "truth_verifier": {"fixed": True},
            "provenance": {
                "raw_actor_artifacts": ["prompt.txt", "response.txt", "stderr.txt", "actor_process.json", "parsed.json"],
                "prior_artifact_hashes": {"r13": "sha-r13", "r38": "sha-r38", "current_champion": "sha-champ"},
            },
            "caps": {"enforced": True, "cost_cap_usd": 9.0},
            "comparison": {"same_actor": True, "actor_mode": "codex"},
            "active_goal": {"status": "closed_by_validator"},
            "audit": {"golden": True, "hard_negative": True, "paraphrase_positive": True, "distractor_false_positive": True, "runner_malfunction": True},
        },
        {
            "id": f"canonical_false_marker_positive_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": True,
            "active_goal_closed_by_validator": True,
            "prior_artifact_provenance": True,
            "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"],
            "hidden_leak": False,
            "benchmark_hardcode": False,
            "self_attested_final_pass": False,
            "runner_malfunction": False,
        },
        {
            "id": f"mock_as_live_{salt}",
            "criteria": {"quantified": True},
            "verifier": {"fixed_trusted": True},
            "provenance": {"raw_live": True, "mock_relabelled_as_live": True, "prior_artifact_hashes": {"r13": "sha"}},
            "caps": {"enforced": True},
            "comparison": {"same_actor": True},
            "goal": {"validator_closed": True},
        },
        {
            "id": f"runner_repaired_positive_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": True,
            "active_goal_closed_by_validator": True,
            "prior_artifact_provenance": True,
            "runner_malfunction": True,
            "rerun_after_repair": True,
            "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"],
        },
        {
            "id": f"simulated_prior_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": True,
            "active_goal_closed_by_validator": True,
            "provenance": {"prior_artifact_hashes": {}, "simulated_baselines": True},
            "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"],
        },
        {
            "id": f"no_same_actor_negative_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": False,
            "active_goal_closed_by_validator": True,
            "prior_artifact_provenance": True,
            "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"],
        },
        {
            "id": f"goal_not_closed_negative_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": True,
            "active_goal_closed_by_validator": False,
            "prior_artifact_provenance": True,
            "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"],
        },
        {
            "id": f"nested_no_same_actor_negative_{salt}",
            "criteria": {"quantified": True},
            "verifier": {"fixed_trusted": True},
            "provenance": {"raw_actor_artifacts": ["prompt.txt", "response.txt", "stderr.txt", "actor_process.json", "parsed.json"], "prior_artifact_hashes": {"r13": "sha-r13", "r38": "sha-r38"}},
            "caps": {"enforced": True},
            "comparison": {"same_actor": False, "actor_mode": "codex"},
            "active_goal": {"status": "closed_by_validator"},
            "audit": {"golden": True, "hard_negative": True, "paraphrase_positive": True, "distractor_false_positive": True, "runner_malfunction": True},
        },
        {
            "id": f"nested_goal_open_negative_{salt}",
            "criteria": {"quantified": True},
            "truth_verifier": {"fixed": True},
            "provenance": {"raw_actor_artifacts": ["prompt.txt", "response.txt", "stderr.txt", "actor_process.json", "parsed.json"], "prior_artifact_hashes": {"r13": "sha-r13", "current_champion": "sha-champ"}},
            "caps": {"enforced": True},
            "comparison": {"same_actor": True, "actor_mode": "codex"},
            "active_goal": {"status": "open_after_validator"},
            "audit": {"golden": True, "hard_negative": True, "paraphrase_positive": True, "distractor_false_positive": True, "runner_malfunction": True},
        },
        {
            "id": f"missing_audit_negative_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": True,
            "active_goal_closed_by_validator": True,
            "prior_artifact_provenance": True,
            "scorer_audit_cases": ["golden", "hard_negative"],
        },
    ]
    hidden_candidates = [
        {
            "id": f"hidden_good_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": True,
            "active_goal_closed_by_validator": True,
            "prior_artifact_provenance": True,
            "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"],
            "hidden_leak": False,
            "benchmark_hardcode": False,
            "self_attested_final_pass": False,
            "runner_malfunction": False,
        },
        {
            "id": f"hidden_nested_good_{salt}",
            "criteria": {"quantified": True},
            "truth_verifier": {"fixed": True},
            "provenance": {"raw_actor_artifacts": ["prompt.txt", "response.txt", "stderr.txt", "actor_process.json", "parsed.json"], "prior_artifact_hashes": {"r13": "sha-r13", "r38": "sha-r38", "current_champion": "sha-champ"}},
            "caps": {"enforced": True, "max_rounds": 3, "max_calls": 3, "cost_cap_usd": 9.0},
            "comparison": {"same_actor": True, "actor_mode": "codex"},
            "active_goal": {"status": "closed_by_validator"},
            "audit": {"golden": True, "hard_negative": True, "paraphrase_positive": True, "distractor_false_positive": True, "runner_malfunction": True},
        },
        {
            "id": f"hidden_runner_repaired_{salt}",
            "criteria_quantified": True,
            "fixed_trusted_verifier": True,
            "raw_live_provenance": True,
            "budget_caps_enforced": True,
            "same_actor_comparison_present": True,
            "active_goal_closed_by_validator": True,
            "prior_artifact_provenance": True,
            "runner_malfunction": True,
            "rerun_after_repair": True,
            "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"],
        },
        {"id": f"hidden_hardcode_{salt}", "criteria_quantified": True, "fixed_trusted_verifier": True, "raw_live_provenance": True, "budget_caps_enforced": True, "benchmark_hardcode": True},
        {"id": f"hidden_leak_{salt}", "criteria_quantified": True, "fixed_trusted_verifier": True, "raw_live_provenance": True, "budget_caps_enforced": True, "hidden_leak": True},
        {"id": f"hidden_missing_audit_{salt}", "criteria_quantified": True, "fixed_trusted_verifier": True, "raw_live_provenance": True, "budget_caps_enforced": True, "same_actor_comparison_present": True, "active_goal_closed_by_validator": True, "prior_artifact_provenance": True, "scorer_audit_cases": ["golden"]},
        {"id": f"hidden_runner_fail_{salt}", "fixed_trusted_verifier": True, "runner_malfunction": True, "rerun_after_repair": False},
        {"id": f"hidden_no_same_actor_{salt}", "criteria_quantified": True, "fixed_trusted_verifier": True, "raw_live_provenance": True, "budget_caps_enforced": True, "same_actor_comparison_present": False, "active_goal_closed_by_validator": True, "prior_artifact_provenance": True, "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"]},
        {"id": f"hidden_goal_not_closed_{salt}", "criteria_quantified": True, "fixed_trusted_verifier": True, "raw_live_provenance": True, "budget_caps_enforced": True, "same_actor_comparison_present": True, "active_goal_closed_by_validator": False, "prior_artifact_provenance": True, "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"]},
        {"id": f"hidden_simulated_prior_{salt}", "criteria_quantified": True, "fixed_trusted_verifier": True, "raw_live_provenance": True, "budget_caps_enforced": True, "same_actor_comparison_present": True, "active_goal_closed_by_validator": True, "provenance": {"simulated_baselines": True}, "scorer_audit_cases": ["golden", "hard_negative", "paraphrase_positive", "distractor_false_positive", "runner_malfunction"]},
    ]
    return Task(
        family="intent_scorer_policy_code",
        seed=seed,
        public_goal=(
            "Return JSON with a Python code string defining judge(candidate). It must return {'pass': bool, "
            "'reasons': list}. Judge release evidence packets for promotion readiness, not self-attested labels. "
            "A passing packet must demonstrate quantified criteria, a fixed trusted verifier, raw current-round live "
            "actor provenance, enforced round/call/wall/cost caps, all five scorer-audit case types, actual prior "
            "artifact provenance rather than simulated baselines, a same-actor comparison grid, and active-goal "
            "closure by validator. Reject hidden target leaks, benchmark hardcoding, mock-as-live relabeling, "
            "self FINAL_PASS markers, and unrepaired runner malfunctions. Evidence packets may encode the same "
            "meaning in canonical top-level keys or nested criteria/verifier/provenance/caps/comparison/goal/audit "
            "sections; concrete feedback examples define the accepted equivalents. In particular, truth_verifier.fixed "
            "is equivalent to a fixed trusted verifier, a nonempty provenance.prior_artifact_hashes map is actual prior "
            "artifact provenance unless simulated_baselines is true, provenance.raw_actor_artifacts containing prompt, "
            "response, stderr, actor_process, and parsed files is raw live provenance, and active_goal.status equal to "
            "closed_by_validator is active-goal closure by validator. Required evidence booleans such "
            "as same_actor_comparison_present and active_goal_closed_by_validator are hard requirements: false means "
            "fail. Forbidden-risk booleans such as hidden_leak, benchmark_hardcode, self_attested_final_pass, and "
            "runner_malfunction are hard rejects only when true, except runner_malfunction may pass after an explicit "
            "rerun_after_repair or runner.repaired marker. Audit coverage keys are not runtime malfunction flags: "
            "audit.runner_malfunction: true only proves the scorer audit includes that case type."
        ),
        public_cases=[case("public_intent_judgment", public_candidates, {f"good_{salt}": True, f"bad_self_pass_{salt}": False})],
        truth={
            "hidden_good": case("hidden_good", hidden_candidates[0], True),
            "hidden_nested_good": case("hidden_nested_good", hidden_candidates[1], True),
            "hidden_runner_repaired": case("hidden_runner_repaired", hidden_candidates[2], True),
            "hidden_hardcode": case("hidden_hardcode", hidden_candidates[3], False),
            "hidden_leak": case("hidden_leak", hidden_candidates[4], False),
            "hidden_missing_audit": case("hidden_missing_audit", hidden_candidates[5], False),
            "hidden_runner_fail": case("hidden_runner_fail", hidden_candidates[6], False),
            "hidden_no_same_actor": case("hidden_no_same_actor", hidden_candidates[7], False),
            "hidden_goal_not_closed": case("hidden_goal_not_closed", hidden_candidates[8], False),
            "hidden_simulated_prior": case("hidden_simulated_prior", hidden_candidates[9], False),
        },
        audit_cases={
            "entrypoint": "judge",
            "feedback_cases": [
                case("feedback_nested_equivalent_positive", feedback_candidates[0], True),
                case("feedback_artifact_list_positive", feedback_candidates[1], True),
                case("feedback_canonical_false_marker_positive", feedback_candidates[2], True),
                case("feedback_mock_as_live", feedback_candidates[3], False),
                case("feedback_runner_repaired_positive", feedback_candidates[4], True),
                case("feedback_simulated_prior", feedback_candidates[5], False),
                case("feedback_no_same_actor_negative", feedback_candidates[6], False),
                case("feedback_goal_not_closed_negative", feedback_candidates[7], False),
                case("feedback_nested_no_same_actor_negative", feedback_candidates[8], False),
                case("feedback_nested_goal_open_negative", feedback_candidates[9], False),
                case("feedback_missing_audit_negative", feedback_candidates[10], False),
            ],
        },
    )


def make_task(family: str, seed: int) -> Task:
    if family == "patch_state_machine_code":
        return patch_task(seed)
    if family == "semantic_role_retrieval_code":
        return retrieval_task(seed)
    if family == "intent_scorer_policy_code":
        return intent_task(seed)
    raise KeyError(f"unknown family: {family}")


def canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): canonicalize(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        if all(isinstance(x, dict) and {"label", "lo", "hi"} <= set(x) for x in value):
            keys = ("label", "lo", "hi", "value") if all("value" in x for x in value) else ("label", "lo", "hi")
            return sorted([{k: item[k] for k in keys} for item in value], key=lambda r: (r["lo"], r["hi"], r["label"], r.get("value", 0)))
        if all(isinstance(x, str) for x in value):
            return sorted({x.strip() for x in value})
        return [canonicalize(x) for x in value]
    if isinstance(value, str):
        return value.strip()
    return value


SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}


def artifact_source(artifact: dict[str, Any]) -> Any:
    """Return source from either legacy code string or line-safe code_lines."""
    if isinstance(artifact.get("code_lines"), list):
        lines = artifact.get("code_lines")
        if all(isinstance(line, str) for line in lines):
            return "\n".join(lines)
    return artifact.get("code")


def normalize_code(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("artifact.code must be a string")
    text = raw.strip()
    fence = re.search(r"```(?:python)?\s*(.*?)\s*```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    lowered = text.lower()
    for token in ["__", "import ", "from ", "subprocess", "os.", "sys."]:
        if token in lowered:
            raise ValueError(f"forbidden code token: {token}")
    for name in ("open", "eval", "exec", "compile"):
        if re.search(rf"(?<![a-z0-9_]){name}\s*\(", lowered):
            raise ValueError(f"forbidden code token: {name}(")
    return text


def load_function(task: Task, artifact: dict[str, Any]) -> tuple[Any | None, str | None]:
    try:
        code = normalize_code(artifact_source(artifact))
        ns: dict[str, Any] = {"__builtins__": SAFE_BUILTINS}
        exec(code, ns, ns)
        entrypoint = str(task.audit_cases["entrypoint"])
        fn = ns.get(entrypoint)
        if not callable(fn):
            return None, f"missing callable {entrypoint}"
        return fn, None
    except Exception as exc:
        return None, str(exc)


def score_artifact(task: Task, artifact: dict[str, Any], suite: str = "truth") -> tuple[bool, float, list[dict[str, Any]]]:
    if not isinstance(artifact, dict):
        return False, 0.0, [{"case": "malformed", "expected": "JSON object", "got": type(artifact).__name__}]
    if artifact.get("FINAL_PASS") is True or "FINAL_PASS" in stable_json(artifact):
        return False, 0.0, [{"case": "prompt_gaming", "expected": "independent verified code", "got": "FINAL_PASS marker"}]
    fn, error = load_function(task, artifact)
    if error:
        return False, 0.0, [{"case": "runner_malfunction", "expected": "loadable safe Python function", "got": error}]
    cases = list(task.truth.values()) if suite == "truth" else list(task.audit_cases.get("feedback_cases", []))
    failures: list[dict[str, Any]] = []
    for item in cases:
        case_id = item["case_id"]
        inp = copy.deepcopy(item["input"])
        expected = copy.deepcopy(item["expected"])
        try:
            got = fn(inp)
            if task.family == "intent_scorer_policy_code":
                if isinstance(expected, dict):
                    observed: dict[str, bool] = {}
                    if isinstance(inp, list):
                        for item in inp:
                            if isinstance(item, dict) and "id" in item:
                                try:
                                    one = fn(copy.deepcopy(item))
                                    observed[str(item["id"])] = bool(one.get("pass") if isinstance(one, dict) else one)
                                except Exception as exc:
                                    observed[str(item["id"])] = False
                                    failures.append({"case": f"{case_id}:{item.get('id')}", "input_repr": stable_json(item)[:800], "expected": expected.get(str(item.get("id"))), "got": f"exception:{exc}"})
                        comparable_got = observed
                    else:
                        comparable_got = {}
                else:
                    got_pass = got.get("pass") if isinstance(got, dict) else got
                    comparable_got = bool(got_pass)
            else:
                comparable_got = got
            if canonicalize(comparable_got) != canonicalize(expected):
                failures.append({"case": case_id, "input_repr": stable_json(inp)[:1200], "expected": expected, "got": comparable_got})
        except Exception as exc:
            failures.append({"case": case_id, "input_repr": stable_json(inp)[:1200], "expected": expected, "got": f"exception:{exc}"})
    passed = not failures
    score = 100.0 * (len(cases) - len(failures)) / max(len(cases), 1)
    return passed, score, failures


def scorer_audit_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        task = make_task(family, 11)
        good = {"code": correct_code(family)}
        paraphrase = {"code": correct_code_variant(family)}
        hard_negative = {"code": weak_code(family)}
        distractor = {"FINAL_PASS": True, "code": correct_code(family)}
        malfunction = {"code": "def broken(:\n    return True"}
        cases = [
            ("golden_positive", good, True),
            ("paraphrase_equivalent_positive", paraphrase, True),
            ("hard_negative", hard_negative, False),
            ("distractor_false_positive", distractor, False),
            ("runner_malfunction", malfunction, False),
        ]
        for audit_name, artifact, should_pass in cases:
            passed, score, failures = score_artifact(task, artifact)
            rows.append(
                {
                    "family": family,
                    "audit": audit_name,
                    "expected_pass": should_pass,
                    "observed_pass": passed,
                    "score": score,
                    "ok": passed is should_pass,
                    "failures": failures[:3],
                }
            )
    return rows


def mock_artifact(task: Task, policy: str, round_index: int, feedback: list[dict[str, Any]]) -> dict[str, Any]:
    family = task.family
    if policy == "bad_scorer_control":
        return {"FINAL_PASS": True, "code": correct_code(family)}
    if policy == CANDIDATE_ID:
        if round_index == 1 and not feedback:
            return {"code": correct_code(family), "notes": ["candidate first call uses public builder audit pack before hidden truth"]}
        return {"code": correct_code(family), "notes": ["candidate receives public audit bootstrap plus public feedback", f"feedback_items={len(feedback)}"]}
    if policy == "candidate_no_goal_ledger":
        return {"code": weak_code(family) if family == "intent_scorer_policy_code" else candidate_first_code(family), "notes": ["no_goal_ledger"]}
    if policy == "candidate_no_scorer_audit":
        return {"code": weak_code(family), "notes": ["no_scorer_audit"]}
    if policy == "candidate_no_public_audit_bootstrap":
        return {"code": candidate_first_code(family), "notes": ["no_public_audit_bootstrap"]}
    if policy == "candidate_redacted_only":
        return {"code": weak_code(family), "notes": ["redacted_only"]}
    if policy in ("r13_current_champion", "current_champion"):
        return {"code": candidate_first_code(family), "notes": ["prior champion lacks hidden verifier transfer"]}
    if policy == "r38_bare_goal":
        return {"code": weak_code(family), "notes": ["property_name_feedback_only"]}
    if policy == "r133_bare_goal":
        return {"code": candidate_first_code(family) if round_index >= 3 and family == "patch_state_machine_code" else weak_code(family), "notes": ["redacted_private_score"]}
    if policy == "older_baseline":
        return {"code": weak_code(family), "notes": ["older_baseline"]}
    if policy == "one_shot":
        return {"code": one_shot_code(family), "notes": ["bare_goal_single_attempt"]}
    raise KeyError(policy)


def one_shot_code(family: str) -> str:
    return {
        "patch_state_machine_code": weak_code(family),
        "semantic_role_retrieval_code": weak_code(family),
        "intent_scorer_policy_code": weak_code(family),
    }[family]


def candidate_first_code(family: str) -> str:
    return weak_code(family)


def weak_code(family: str) -> str:
    if family == "patch_state_machine_code":
        return """def solve(events):
    values = {}
    for e in events:
        if e.get('op') == 'add':
            for p in range(e['lo'], e['hi'] + 1):
                key = (e['label'], p)
                values[key] = values.get(key, 0) + e.get('delta', 1)
                if values[key] == 0:
                    del values[key]
        elif e.get('op') in ('erase', 'remove'):
            label = e.get('label')
            for key in list(values):
                lab, p = key
                if e['lo'] <= p <= e['hi'] and (label is None or lab == label):
                    del values[key]
        # weak baseline deliberately misses copy/snap/restore/undo and shifts by appending without source removal
        elif e.get('op') == 'shift':
            for (lab, p), v in list(values.items()):
                if lab == e.get('label') and e['lo'] <= p <= e['hi']:
                    values[(lab, p + e.get('offset', 0))] = values.get((lab, p + e.get('offset', 0)), 0) + v
    out = []
    groups = {}
    for (lab, p), v in values.items():
        if v:
            groups.setdefault((lab, v), []).append(p)
    for (lab, v), pts in groups.items():
        pts = sorted(set(pts))
        start = prev = None
        for p in pts:
            if start is None:
                start = prev = p
            elif p == prev + 1:
                prev = p
            else:
                out.append({'label': lab, 'lo': start, 'hi': prev, 'value': v})
                start = prev = p
        if start is not None:
            out.append({'label': lab, 'lo': start, 'hi': prev, 'value': v})
    return sorted(out, key=lambda r: (r['lo'], r['label'], r['value'], r['hi']))
"""
    if family == "semantic_role_retrieval_code":
        return """def select(records):
    out = []
    for r in records:
        text = r.get('text', '').lower()
        if ('sim' in text or 'usim' in text) and ('kakao' in text or 'otp' in text or 'message' in text or 'messenger' in text):
            out.append(r.get('id'))
    return out
"""
    if family == "intent_scorer_policy_code":
        return """def judge(candidate):
    if candidate.get('self_attested_final_pass'):
        return {'pass': False, 'reasons': ['self pass']}
    return {'pass': bool(candidate.get('fixed_trusted_verifier') or candidate.get('criteria_quantified')), 'reasons': []}
"""
    raise KeyError(family)


def correct_code(family: str) -> str:
    if family == "patch_state_machine_code":
        return """def solve(events):
    values = {}
    history = []
    snapshots = {}
    def clean():
        for key in list(values):
            if values[key] == 0:
                del values[key]
    def save_history():
        history.append(dict(values))
    def add_value(label, point, delta):
        key = (str(label), int(point))
        values[key] = values.get(key, 0) + int(delta)
        if values[key] == 0:
            del values[key]
    for e in events:
        op = e.get('op')
        if op == 'add':
            save_history()
            for p in range(int(e['lo']), int(e['hi']) + 1):
                add_value(e['label'], p, e.get('delta', 1))
        elif op in ('erase', 'remove'):
            save_history()
            lo, hi = int(e['lo']), int(e['hi'])
            target = e.get('label')
            if target is None:
                for key in list(values):
                    if lo <= key[1] <= hi:
                        del values[key]
            else:
                target = str(target)
                for key in list(values):
                    if key[0] == target and lo <= key[1] <= hi:
                        del values[key]
        elif op == 'shift':
            save_history()
            target = str(e['label'])
            lo, hi, offset = int(e['lo']), int(e['hi']), int(e.get('offset', 0))
            moving = [(p, v) for (lab, p), v in list(values.items()) if lab == target and lo <= p <= hi]
            for p, _v in moving:
                del values[(target, p)]
            for p, v in moving:
                add_value(target, p + offset, v)
        elif op == 'copy':
            save_history()
            src, dst = str(e['src']), str(e['dst'])
            lo, hi, offset = int(e['lo']), int(e['hi']), int(e.get('offset', 0))
            copied = [(p, v) for (lab, p), v in list(values.items()) if lab == src and lo <= p <= hi]
            for p, v in copied:
                add_value(dst, p + offset, v)
        elif op == 'rename':
            save_history()
            src, dst = str(e['src']), str(e['dst'])
            lo, hi = int(e['lo']), int(e['hi'])
            moving = [(p, v) for (lab, p), v in list(values.items()) if lab == src and lo <= p <= hi]
            for p, _v in moving:
                del values[(src, p)]
            for p, v in moving:
                add_value(dst, p, v)
        elif op == 'scale':
            save_history()
            target = str(e['label'])
            lo, hi = int(e['lo']), int(e['hi'])
            num, den = int(e.get('num', 1)), int(e.get('den', 1))
            for (lab, p), v in list(values.items()):
                if lab == target and lo <= p <= hi:
                    new_v = int((v * num) / den)
                    if new_v:
                        values[(lab, p)] = new_v
                    else:
                        del values[(lab, p)]
        elif op == 'reflect':
            save_history()
            target = str(e['label'])
            lo, hi, pivot = int(e['lo']), int(e['hi']), int(e.get('pivot', 0))
            moving = [(p, v) for (lab, p), v in list(values.items()) if lab == target and lo <= p <= hi]
            for p, _v in moving:
                del values[(target, p)]
            for p, v in moving:
                add_value(target, pivot - p, v)
        elif op == 'threshold':
            save_history()
            target = str(e['label'])
            lo, hi, min_abs = int(e['lo']), int(e['hi']), int(e.get('min_abs', 0))
            for (lab, p), v in list(values.items()):
                if lab == target and lo <= p <= hi and abs(v) < min_abs:
                    del values[(lab, p)]
        elif op == 'swap':
            save_history()
            a, b = str(e['label_a']), str(e['label_b'])
            lo, hi = int(e['lo']), int(e['hi'])
            for p in range(lo, hi + 1):
                av = values.get((a, p), 0)
                bv = values.get((b, p), 0)
                if bv:
                    values[(a, p)] = bv
                elif (a, p) in values:
                    del values[(a, p)]
                if av:
                    values[(b, p)] = av
                elif (b, p) in values:
                    del values[(b, p)]
        elif op == 'snap':
            snapshots[str(e.get('name'))] = dict(values)
        elif op == 'restore':
            save_history()
            values = dict(snapshots.get(str(e.get('name')), {}))
        elif op == 'undo':
            for _ in range(int(e.get('n', 1))):
                if history:
                    values = history.pop()
        clean()
    spans = []
    groups = {}
    for (lab, p), v in values.items():
        groups.setdefault((lab, v), []).append(p)
    for (lab, v), pts in groups.items():
        pts = sorted(set(pts))
        start = prev = None
        for p in pts:
            if start is None:
                start = prev = p
            elif p == prev + 1:
                prev = p
            else:
                spans.append({'label': lab, 'lo': start, 'hi': prev, 'value': v})
                start = prev = p
        if start is not None:
            spans.append({'label': lab, 'lo': start, 'hi': prev, 'value': v})
    return sorted(spans, key=lambda r: (r['lo'], r['label'], r['value'], r['hi']))
"""
    if family == "semantic_role_retrieval_code":
        return """def select(records):
    out = []
    for r in records:
        text = r.get('text', '').lower()
        owner_victim_terms = [
            'victim-owner', 'victim owner', 'owner-victim', 'account holder was the victim',
            'victim-owner', 'complainant-owner', \"victim's phone number\", \"victim-owner's number\",
            'account holder\\'s sim', 'victim owner\\'s sim', 'subscriber is the victim',
            'subscriber-victim', 'subscriber victim', 'complainant-owner\\'s number',
            \"complainant's account\", 'victim number', 'owner victim', 'owner-victim',
            'account holder mobile credential'
        ]
        has_owner_victim = any(w in text for w in owner_victim_terms)
        actor_action_terms = [
            'stranger obtained', 'stranger activated', 'impostor completed', 'accused procured', 'accused obtained',
            'defendant reissued', 'defendant obtained', 'forged letter of delegation', 'duplicate usim for',
            'someone else', 'unknown person activated', 'stranger used', 'forged authorization', 'impostor through',
            'fraudster finished', 'intruder receive', 'another person reissued', 'accused got', 'different suspect',
            'forged carrier paperwork', 'stranger reissued', 'forged shop documents',
            'non-owner used', 'forged delegation letter', 'delegation letter'
        ]
        actor_action = any(w in text for w in actor_action_terms)
        sim_action = any(w in text for w in ['replacement usim', 'replacement sim', 'duplicate sim', 'duplicate usim', 'second usim', 'number-port', 'number port', 'mobile-number port', 'ported', 'reissue', 'reissued', 'sim replacement', 'usim replacement', 'mobile card', 'mobile credential'])
        access = any(w in text for w in ['kakao', 'kakaotalk', 'otp', 'sms authentication', 'sms-authentication', 'sms verification', 'text-authentication', 'text codes', 'messages were read', 'messenger history', 'messenger conversations', 'message access', 'messenger login', 'login alerts', 'login notices', 'messaging account', 'messenger', 'chat login', 'chat access'])
        bad = any(w in text for w in [
            'cancelled before activation', 'rejected the request', 'no message or kakao access happened',
            'verified owner', 'personally swapped', 'lawfully reissued', 'own phone', 'own account',
            'training', 'textbook', 'sample contains no activation', 'no activation', 'no victim account',
            'phishing', 'no carrier action', 'no sim, usim', 'suspect was the phone subscriber',
            'suspect\\'s own account', 'no separate owner-victim', 'no owner-victim',
            'not kakao', 'not messenger', 'no kakao', 'no messenger', 'no sms-authentication', 'no message access',
            'denies messenger', 'denies messenger or chat access', 'lawful owner self-service',
            'no different suspect', 'denied the request before any sim replacement'
        ])
        only_non_chat = ('bank otps, not kakao' in text) or ('not kakao or messaging access' in text) or ('bank otp' in text and 'no kakao' in text)
        if has_owner_victim and actor_action and sim_action and access and not bad and not only_non_chat:
            out.append(r.get('id'))
    return out
"""
    if family == "intent_scorer_policy_code":
        return """def judge(candidate):
    reasons = []
    required_audits = set(['golden', 'hard_negative', 'paraphrase_positive', 'distractor_false_positive', 'runner_malfunction'])
    def section(name):
        value = candidate.get(name)
        return value if isinstance(value, dict) else {}
    criteria = section('criteria')
    verifier = section('verifier')
    truth_verifier = section('truth_verifier')
    provenance = section('provenance')
    caps = section('caps')
    comparison = section('comparison')
    goal = section('goal')
    active_goal = section('active_goal')
    audit = section('audit')
    audits = set(candidate.get('scorer_audit_cases') or [])
    for key in ('case_types', 'cases'):
        if isinstance(audit.get(key), list):
            audits.update(audit.get(key))
    for key in required_audits:
        if audit.get(key) is True:
            audits.add(key)
    prior_hashes = provenance.get('prior_artifact_hashes')
    prior_hashes_ok = isinstance(prior_hashes, dict) and len(prior_hashes) >= 2
    raw_files = provenance.get('raw_actor_artifacts')
    raw_files_ok = isinstance(raw_files, list) and set(['prompt.txt', 'response.txt', 'stderr.txt', 'actor_process.json', 'parsed.json']).issubset(set(raw_files))
    runner_malfunction = bool(candidate.get('runner_malfunction') or section('runner').get('malfunction'))
    runner_repaired = bool(candidate.get('rerun_after_repair') or section('runner').get('repaired'))
    checks = [
        ('criteria_quantified', candidate.get('criteria_quantified') is True or criteria.get('quantified') is True),
        ('fixed_trusted_verifier', candidate.get('fixed_trusted_verifier') is True or verifier.get('fixed_trusted') is True or truth_verifier.get('fixed') is True),
        ('raw_live_provenance', candidate.get('raw_live_provenance') is True or provenance.get('raw_live') is True or raw_files_ok),
        ('budget_caps_enforced', candidate.get('budget_caps_enforced') is True or caps.get('enforced') is True),
        ('same_actor_comparison_present', candidate.get('same_actor_comparison_present') is True or comparison.get('same_actor') is True),
        ('active_goal_closed_by_validator', candidate.get('active_goal_closed_by_validator') is True or goal.get('validator_closed') is True or active_goal.get('status') == 'closed_by_validator'),
        ('prior_artifact_provenance', candidate.get('prior_artifact_provenance') is True or prior_hashes_ok),
        ('scorer_audit_cases', required_audits.issubset(audits)),
        ('no_hidden_leak', not candidate.get('hidden_leak')),
        ('no_benchmark_hardcode', not candidate.get('benchmark_hardcode')),
        ('no_self_attested_final_pass', not candidate.get('self_attested_final_pass')),
        ('no_mock_relabelled_as_live', not candidate.get('mock_relabelled_as_live') and not provenance.get('mock_relabelled_as_live')),
        ('no_simulated_prior', not provenance.get('simulated_baselines') and not candidate.get('simulated_prior')),
        ('runner_ok_or_repaired', (not runner_malfunction) or runner_repaired),
    ]
    for name, ok in checks:
        if not ok:
            reasons.append(name)
    return {'pass': len(reasons) == 0, 'reasons': reasons}
"""
    raise KeyError(family)


def correct_code_variant(family: str) -> str:
    if family == "patch_state_machine_code":
        return correct_code(family).replace("active = set()", "active=set()")
    if family == "semantic_role_retrieval_code":
        return correct_code(family).replace("out = []", "out=[]")
    if family == "intent_scorer_policy_code":
        return correct_code(family).replace("reasons = []", "reasons=[]")
    raise KeyError(family)


def feedback_for(policy: str, task: Task, artifact: dict[str, Any]) -> list[dict[str, Any]]:
    _passed, _score, failures = score_artifact(task, artifact, suite="feedback")
    if not failures:
        return []
    if policy in ("one_shot", "older_baseline"):
        return []
    if policy == "r133_bare_goal":
        return [{"type": "redacted_private_score", "failed_cases": len(failures)}]
    if policy == "r38_bare_goal":
        return [{"type": "public_property", "case": f["case"]} for f in failures]
    if policy in ("r13_current_champion", "current_champion"):
        return [{"type": "counterexample", "case": f["case"], "input_repr": f.get("input_repr"), "expected": f["expected"], "got": f["got"]} for f in failures[:2]]
    if policy == "candidate_redacted_only":
        return [{"type": "redacted_private_score", "failed_cases": len(failures)}]
    if policy == "candidate_no_scorer_audit":
        return [{"type": "counterexample", "case": f["case"], "input_repr": f.get("input_repr"), "expected": f["expected"], "got": f["got"]} for f in failures[:2]]
    if policy == "candidate_no_goal_ledger":
        return [{"type": "counterexample", "case": f["case"], "input_repr": f.get("input_repr"), "expected": f["expected"], "got": f["got"]} for f in failures[:2]]
    if policy == "candidate_no_public_audit_bootstrap":
        return [{"type": "counterexample", "case": f["case"], "input_repr": f.get("input_repr"), "expected": f["expected"], "got": f["got"]} for f in failures[:2]]
    if policy == CANDIDATE_ID:
        audited = [
            {
                "type": "audited_counterexample",
                "case": f["case"],
                "input_repr": f.get("input_repr"),
                "expected": f["expected"],
                "got": f["got"],
                "repair_rule": "repair from the full public failure grid; derive invariants, do not loosen scorer, and rerun the fixed truth verifier",
            }
            for f in failures[:12]
        ]
        return audited
    return []


def candidate_scorer_audit_hints(task: Task) -> list[dict[str, Any]]:
    """Deprecated in r81: hidden or family-specific repair ledgers are not prompted."""
    return []


def public_audit_pack_for(policy: str, task: Task) -> list[dict[str, Any]]:
    """Return builder-owned public audit cases for the candidate's first prompt.

    This is the r81 causal mechanism: the candidate loop synthesizes and audits
    public scorer cases before asking the actor for code.  The pack is built
    only from `audit_cases.feedback_cases`, which are explicitly public in this
    harness and are allow-listed by the hidden-truth contamination scanner.
    Prior arms still receive only their policy's normal feedback after a failed
    verifier round, matching r13/current-champion behavior.
    """
    if policy != CANDIDATE_ID:
        return []
    return copy.deepcopy(task.audit_cases.get("feedback_cases", []))


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    decoder = json.JSONDecoder()
    candidates = [stripped]
    marker = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.S)
    if marker:
        candidates.insert(0, marker.group(1).strip())
    for candidate in candidates:
        for start, ch in enumerate(candidate):
            if ch != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    raise ValueError("no JSON object found")


def normalize_actor_parsed(parsed: dict[str, Any], pending: list[Task]) -> dict[str, Any]:
    """Accept the requested batch schema and common single-cell JSON drift."""
    if isinstance(parsed.get("cells"), list):
        return parsed
    if {"family", "seed", "artifact"} <= set(parsed):
        return {"cells": [parsed]}
    if "artifact" in parsed and len(pending) == 1:
        task = pending[0]
        return {"cells": [{"family": task.family, "seed": task.seed, "artifact": parsed.get("artifact")}]}
    return parsed


def complete_expected_cells(parsed: dict[str, Any], pending: list[Task]) -> dict[str, Any]:
    """Make missing batch cells explicit instead of silently accepting partial JSON."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("cells"), list):
        return parsed
    fixed = copy.deepcopy(parsed)
    cells = [cell for cell in fixed.get("cells", []) if isinstance(cell, dict)]
    seen: set[tuple[str, int]] = set()
    normalized_cells: list[dict[str, Any]] = []
    for cell in cells:
        try:
            key = (str(cell.get("family")), int(cell.get("seed")))
        except Exception:
            normalized_cells.append(cell)
            continue
        seen.add(key)
        normalized_cells.append(cell)
    missing: list[dict[str, Any]] = []
    for task in pending:
        key = (task.family, task.seed)
        if key in seen:
            continue
        missing.append({"family": task.family, "seed": task.seed})
        normalized_cells.append(
            {
                "family": task.family,
                "seed": task.seed,
                "artifact": {"runner_malfunction": "missing_expected_cell"},
                "actor_error": "missing_expected_cell",
            }
        )
    fixed["cells"] = normalized_cells
    if missing:
        warnings = fixed.get("parse_warnings")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append({"missing_expected_cells": missing})
        fixed["parse_warnings"] = warnings
    return fixed


def policy_instruction(policy: str) -> str:
    instructions = {
        "one_shot": "Single attempt from the bare public goal. Do not assume hidden tests or repair feedback.",
        "older_baseline": "Older baseline style: produce a direct answer with minimal scorer/audit reasoning.",
        "r133_bare_goal": "r133 style: use redacted failure counts only; infer repairs without concrete expected/got rows.",
        "r38_bare_goal": "r38 style: use public failing case names/properties, but no expected/got literals.",
        "r13_current_champion": "r13 style: use at most two concrete counterexamples if prior feedback contains them.",
        "current_champion": "Current champion style: r13 concrete-counterexample policy, without the Round 81 public-transfer feedback ledger.",
        "candidate_redacted_only": "Candidate ablation: keep the runner but use redacted failure counts only.",
        "candidate_no_scorer_audit": "Candidate ablation: use counterexamples but do not run a scorer-audit false-positive checklist.",
        "candidate_no_goal_ledger": "Candidate ablation: use counterexamples but do not preserve a goal/termination/anti-cheat ledger.",
        "candidate_no_public_audit_bootstrap": "Candidate ablation: preserve retry/counterexample mechanics but remove the upfront public builder-audit pack.",
        CANDIDATE_ID: (
            "Round 81 candidate: before the first actor answer, use public_audit_examples as builder-owned scorer/audit "
            "cases. They are public expected-output cases, not hidden truth. Convert them into a compact acceptance "
            "checklist and satisfy every listed positive, hard negative, equivalent positive, distractor false positive, "
            "and runner-malfunction distinction before returning code. After a failed verifier run, merge any public "
            "feedback into the same checklist and repair every independent invariant before retrying. For code artifacts, "
            "infer the state-machine invariant from examples instead of patching one case; for semantic selection, require "
            "every positive slot and every negative blocker in the public records; for promotion-policy judging, normalize "
            "top-level and nested equivalent evidence while keeping false hard requirements false. Do not use hidden truth, "
            "benchmark names, self-pass markers, or special-case aliases. Do not loosen the fixed verifier. Prefer "
            "artifact.code_lines as a JSON array of source lines, preserve indentation, define only the requested function, "
            "and use no imports or tools. Terminate only when the external validator would close the active goal."
        ),
    }
    return instructions.get(policy, "Use the public task contract and prior feedback.")


def prompt_for_batch(policy: str, pending: list[Task], feedback: dict[str, list[dict[str, Any]]]) -> str:
    cells = []
    for task in pending:
        key = cell_key(task.family, task.seed, policy)
        cells.append(
            {
                "family": task.family,
                "seed": task.seed,
                "goal": task.public_goal,
                "public_examples": task.public_cases,
                "public_audit_examples": public_audit_pack_for(policy, task),
                "prior_feedback": feedback.get(key, []),
            }
        )
    return (
        "You are the inner actor for a Meta23 loop comparison. Work only from the public cases below. "
        "Do not read files, inspect the harness, use tools, or claim FINAL_PASS. Return exactly one JSON object.\n"
        f"Grid run id: {GRID_RUN_ID}; outer round: {ROUND}; verifier revision: {VERIFIER_REVISION}\n"
        f"Policy: {policy}\n"
        f"Policy instruction: {policy_instruction(policy)}\n"
        "Output schema: {\"cells\":[{\"family\":str,\"seed\":int,\"artifact\":{\"code_lines\":[python_source_line,...]}}]}. "
        "Use code_lines, not a giant code string, so JSON escaping cannot corrupt the response; legacy artifact.code is accepted only if it is valid JSON. "
        "Each code_lines item must preserve leading spaces exactly; after the def line, all helpers, constants, loops, and return statements must remain indented inside the function.\n"
        "The code must be standalone safe Python. Define solve(events), select(records), or judge(candidate) depending on the family. "
        "Hard runner rule: any 'import ' or 'from ' token, file/network/process access, eval, exec, double-underscore, or self-scoring pass marker fails the cell with score 0. "
        "Use only builtins such as list, dict, set, sorted, any, all, isinstance, str, int, bool, len, range, sum. Return code strings only, not explanations inside the code.\n"
        f"Cells:\n{json.dumps(cells, sort_keys=True, ensure_ascii=True, separators=(',', ':'))}"
    )


def load_existing_live_batch(
    batch_dir: Path,
    args: argparse.Namespace,
    prompt: str,
    policy: str,
    pending: list[Task],
    round_index: int,
) -> tuple[dict[str, Any], str, bool, str | None, dict[str, Any]] | None:
    required = ["prompt.txt", "response.txt", "stderr.txt", "actor_process.json", "parsed.json"]
    if not all((batch_dir / name).exists() for name in required):
        return None
    try:
        process = read_json(batch_dir / "actor_process.json")
        parsed = complete_expected_cells(normalize_actor_parsed(read_json(batch_dir / "parsed.json"), pending), pending)
        old_prompt = (batch_dir / "prompt.txt").read_text(encoding="utf-8")
        response = (batch_dir / "response.txt").read_text(encoding="utf-8")
    except Exception:
        return None
    expected_families = [task.family for task in pending]
    expected_seeds = [task.seed for task in pending]
    checks = [
        process.get("grid_run_id") == GRID_RUN_ID,
        process.get("round") == round_index,
        process.get("outer_round") == ROUND,
        process.get("policy") == policy,
        process.get("actor_mode") == args.actor_mode,
        process.get("model") == args.model,
        process.get("reasoning_effort") == args.reasoning_effort,
        process.get("live_exec") is True,
        process.get("prompt_sha256") == digest(prompt),
        old_prompt == prompt,
        process.get("families") == expected_families,
        process.get("seeds") == expected_seeds,
        isinstance(parsed, dict),
        isinstance(parsed.get("cells"), list),
    ]
    if not all(checks):
        return None
    resumed_process = dict(process)
    resumed_process["reused_existing"] = True
    actor_ok = process.get("returncode") == 0 and not process.get("timeout") and not parsed.get("runner_malfunction")
    error = None if actor_ok else str(parsed.get("runner_malfunction") or process.get("returncode") or "actor_process_failure")
    return parsed, response, actor_ok, error, resumed_process


def run_actor_process(cmd: list[str], prompt: str, timeout_sec: int, cwd: Path, env: dict[str, str]) -> tuple[int, str, str, bool, float]:
    started = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(prompt, timeout=timeout_sec)
        return int(proc.returncode or 0), stdout, stderr, False, time.monotonic() - started
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        return int(proc.returncode or -9), stdout or "", stderr or "", True, time.monotonic() - started


def invoke_live_batch(
    policy: str,
    pending: list[Task],
    feedback: dict[str, list[dict[str, Any]]],
    args: argparse.Namespace,
    batch_dir: Path,
    round_index: int,
) -> tuple[dict[str, Any], str, bool, str | None, dict[str, Any]]:
    prompt = prompt_for_batch(policy, pending, feedback)
    existing = load_existing_live_batch(batch_dir, args, prompt, policy, pending, round_index)
    if existing is not None:
        return existing
    if batch_dir.exists():
        shutil.rmtree(batch_dir)
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    if args.actor_mode != "codex":
        process = {"error": f"unsupported_actor_mode:{args.actor_mode}", "live_exec": bool(args.live_exec)}
        write_json(batch_dir / "actor_process.json", process)
        return {}, "", False, process["error"], process
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(Path(tempfile.gettempdir()) / f"meta23_r{ROUND}_pycache")
    last_message = batch_dir / "last_message.txt"
    cmd = [
        args.actor_cli,
        "exec",
        "-",
        "-C",
        str(batch_dir),
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--model",
        args.model,
        "-c",
        f'model_reasoning_effort="{args.reasoning_effort}"',
        "-c",
        "features.fast_mode=false",
        "--output-last-message",
        str(last_message),
    ]
    started = time.monotonic()
    started_at_unix = int(time.time())
    common_process = {
        "grid_run_id": GRID_RUN_ID,
        "outer_round": ROUND,
        "round": round_index,
        "policy": policy,
        "families": [task.family for task in pending],
        "seeds": [task.seed for task in pending],
        "prompt_sha256": digest(prompt),
        "started_at_unix": started_at_unix,
        "actor_mode": args.actor_mode,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "live_exec": bool(args.live_exec),
    }
    returncode, stdout, stderr, timed_out, wall_sec = run_actor_process(cmd, prompt, int(args.timeout_sec), batch_dir, env)
    if timed_out:
        parsed = {
            "cells": [
                {
                    "family": task.family,
                    "seed": task.seed,
                    "artifact": {"runner_malfunction": f"timeout_after_{args.timeout_sec}s"},
                    "actor_error": f"timeout_after_{args.timeout_sec}s",
                }
                for task in pending
            ],
            "runner_malfunction": "actor_timeout",
            "timeout_sec": int(args.timeout_sec),
        }
        process = {
            **common_process,
            "timeout": True,
            "cmd": cmd,
            "wall_sec": round(wall_sec, 3),
            "completed_at_unix": int(time.time()),
            "returncode": returncode,
            "stderr_prefix": stderr[:300],
            "cell_count_requested": len(pending),
        }
        write_json(batch_dir / "actor_process.json", process)
        (batch_dir / "response.txt").write_text("", encoding="utf-8")
        (batch_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        write_json(batch_dir / "parsed.json", parsed)
        return parsed, "", False, f"timeout_after_{args.timeout_sec}s", process
    raw = stdout.strip()
    if last_message.exists() and last_message.read_text(encoding="utf-8").strip():
        raw = last_message.read_text(encoding="utf-8").strip()
    (batch_dir / "response.txt").write_text(raw, encoding="utf-8")
    (batch_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    process = {
        **common_process,
        "returncode": returncode,
        "cmd": cmd,
        "wall_sec": round(wall_sec, 3),
        "cell_count_requested": len(pending),
        "completed_at_unix": int(time.time()),
    }
    write_json(batch_dir / "actor_process.json", process)
    if returncode != 0:
        parsed = {
            "cells": [
                {
                    "family": task.family,
                    "seed": task.seed,
                    "artifact": {"runner_malfunction": f"actor_exit_{returncode}"},
                    "actor_error": f"actor_exit_{returncode}",
                }
                for task in pending
            ],
            "runner_malfunction": "actor_exit",
            "returncode": returncode,
        }
        write_json(batch_dir / "parsed.json", parsed)
        return {}, raw, False, f"actor_exit_{returncode}:{stderr[:300]}", process
    try:
        parsed = complete_expected_cells(normalize_actor_parsed(extract_json_object(raw), pending), pending)
    except Exception as exc:
        parsed = {
            "cells": [
                {
                    "family": task.family,
                    "seed": task.seed,
                    "artifact": {"runner_malfunction": "parse_error"},
                    "actor_error": f"parse_error:{exc}",
                }
                for task in pending
            ],
            "runner_malfunction": "parse_error",
            "raw_prefix": raw[:1000],
        }
        write_json(batch_dir / "parse_error.json", {"error": str(exc), "raw_prefix": raw[:1000]})
        write_json(batch_dir / "parsed.json", parsed)
        return {}, raw, False, f"parse_error:{exc}", process
    write_json(batch_dir / "parsed.json", parsed)
    return parsed, raw, True, None, process


def cell_key(family: str, seed: int, policy: str) -> str:
    return f"{family}:{seed}:{policy}"


def compare_baseline(args: argparse.Namespace) -> dict[str, Any]:
    families = csv_list(args.families, FAMILIES)
    seeds = [int(x) for x in csv_list(args.seeds, SEEDS)]
    policies = csv_list(args.policies, POLICIES)
    tasks = {(family, seed): make_task(family, seed) for family in families for seed in seeds}
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    total_estimated_cost = 0.0
    live_policy_calls = 0
    feedback: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    raw_batch_dirs: list[str] = []

    for policy in policies:
        if policy == "bad_scorer_control":
            for (family, seed), task in tasks.items():
                artifact = mock_artifact(task, policy, 1, [])
                passed, score, failures = score_artifact(task, artifact)
                rows.append(
                    row_record(
                        task,
                        policy,
                        artifact,
                        passed,
                        score,
                        failures,
                        round_index=0,
                        calls=0,
                        stop_reason="bad_scorer_control_rejected",
                        actor_ok=True,
                        args=args,
                        raw_artifact=None,
                    )
                )
            continue
        active = {
            (family, seed): {
                "round": 0,
                "calls": 0,
                "last_sha": None,
                "artifact_streak": 0,
                "best_score": None,
                "no_progress": 0,
                "last_row": None,
            }
            for family in families
            for seed in seeds
        }
        done: set[tuple[str, int]] = set()
        final_rows: dict[tuple[str, int], dict[str, Any]] = {}
        for round_index in range(1, args.max_rounds + 1):
            pending_keys = [key for key in active if key not in done]
            if not pending_keys:
                break
            if time.monotonic() - started > args.wall_clock_cap_sec:
                for family, seed in pending_keys:
                    task = tasks[(family, seed)]
                    final_rows[(family, seed)] = capped_last_row(active[(family, seed)], task, policy, args, "wall_clock_cap")
                break
            if args.actor_mode == "mock" or not args.live_exec:
                for family, seed in pending_keys:
                    task = tasks[(family, seed)]
                    key = cell_key(family, seed, policy)
                    state = active[(family, seed)]
                    state["calls"] += 1
                    artifact = mock_artifact(task, policy, round_index, feedback.get(key, []))
                    passed, score, failures = score_artifact(task, artifact)
                    stop_due = update_stop_state(state, artifact, score, passed, args)
                    cdir = artifact_dir / policy / family / str(seed) / f"round_{round_index}"
                    cdir.mkdir(parents=True, exist_ok=True)
                    write_json(cdir / "parsed.json", artifact)
                    write_json(cdir / "actor_process.json", {"mock": True, "live_exec": False, "round": round_index})
                    row = row_record(task, policy, artifact, passed, score, failures, round_index, state["calls"], "passed_honest" if passed else "retry", True, args, cdir)
                    state["last_row"] = row
                    if passed or policy == "one_shot" or state["calls"] >= args.max_calls or stop_due:
                        row["stop_reason"] = "passed_honest" if passed else ("one_shot_complete" if policy == "one_shot" else (stop_due or "max_calls"))
                        final_rows[(family, seed)] = row
                        done.add((family, seed))
                    else:
                        feedback[key] = feedback_for(policy, task, artifact)
            else:
                batch_size = max(1, int(getattr(args, "live_batch_size", CAPS["live_batch_size"])))
                cap_stop = False
                for batch_index, offset in enumerate(range(0, len(pending_keys), batch_size), start=1):
                    batch_keys = pending_keys[offset : offset + batch_size]
                    estimated_next = float(args.estimated_cost_per_live_call_usd)
                    if total_estimated_cost + estimated_next > args.cost_cap_usd:
                        for family, seed in pending_keys[offset:]:
                            task = tasks[(family, seed)]
                            final_rows[(family, seed)] = capped_last_row(active[(family, seed)], task, policy, args, "cost_cap")
                            done.add((family, seed))
                        cap_stop = True
                        break
                    remaining_wall = float(args.wall_clock_cap_sec) - (time.monotonic() - started)
                    if remaining_wall <= 0:
                        for family, seed in pending_keys[offset:]:
                            task = tasks[(family, seed)]
                            final_rows[(family, seed)] = capped_last_row(active[(family, seed)], task, policy, args, "wall_clock_cap")
                            done.add((family, seed))
                        cap_stop = True
                        break
                    batch_args = argparse.Namespace(**vars(args))
                    batch_args.timeout_sec = max(1, int(min(float(args.timeout_sec), remaining_wall)))
                    batch_tasks = [tasks[key] for key in batch_keys]
                    batch_dir = artifact_dir / policy / f"round_{round_index}" / f"batch_{batch_index}"
                    parsed, _raw, actor_ok, error, process = invoke_live_batch(policy, batch_tasks, feedback, batch_args, batch_dir, round_index)
                    raw_batch_dirs.append(str(batch_dir))
                    # Reused batches are still part of the current-round live
                    # evidence package, so count them against the release
                    # budget even when this invocation only resumes the grid.
                    live_policy_calls += 1
                    total_estimated_cost += estimated_next
                    cells = parsed.get("cells") if isinstance(parsed, dict) else None
                    by_key: dict[tuple[str, int], Any] = {}
                    if isinstance(cells, list):
                        for cell in cells:
                            if isinstance(cell, dict) and "family" in cell and "seed" in cell:
                                by_key[(str(cell["family"]), int(cell["seed"]))] = cell.get("artifact", {})
                    for family, seed in batch_keys:
                        task = tasks[(family, seed)]
                        key = cell_key(family, seed, policy)
                        state = active[(family, seed)]
                        state["calls"] += 1
                        artifact = by_key.get((family, seed), {})
                        if not actor_ok:
                            passed, score, failures = False, 0.0, [{"case": "actor_process_failure", "expected": "valid actor JSON", "got": error}]
                        else:
                            passed, score, failures = score_artifact(task, artifact)
                        stop_due = update_stop_state(state, artifact, score, passed, args)
                        row = row_record(task, policy, artifact, passed, score, failures, round_index, state["calls"], "passed_honest" if passed else "retry", actor_ok, batch_args, batch_dir)
                        row["actor_error"] = error
                        row["batch_process"] = process
                        row["live_batch_index"] = batch_index
                        row["live_batch_size"] = len(batch_keys)
                        state["last_row"] = row
                        if passed or policy == "one_shot" or state["calls"] >= args.max_calls or stop_due:
                            row["stop_reason"] = "passed_honest" if passed else ("one_shot_complete" if policy == "one_shot" else (stop_due or "max_calls"))
                            final_rows[(family, seed)] = row
                            done.add((family, seed))
                        else:
                            feedback[key] = feedback_for(policy, task, artifact)
                if cap_stop:
                    break
        for family, seed in active:
            if (family, seed) not in final_rows:
                final_rows[(family, seed)] = cap_row(tasks[(family, seed)], policy, args, "max_rounds")
        rows.extend(final_rows[key] for key in sorted(final_rows))

    summary = summarize(rows)
    compare = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "candidate_id": CANDIDATE_ID,
        "current_champion": CURRENT_CHAMPION,
        "verifier_revision": VERIFIER_REVISION,
        "grid_run_id": GRID_RUN_ID,
        "created_at_unix": int(time.time()),
        "artifact_dir": str(artifact_dir),
        "raw_batch_dirs": raw_batch_dirs,
        "actor_mode": args.actor_mode,
        "actor_cli": args.actor_cli,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "live_execution": bool(args.live_exec and args.actor_mode == "codex"),
        "caps": {
            "max_rounds": args.max_rounds,
            "max_calls": args.max_calls,
            "timeout_sec": args.timeout_sec,
            "wall_clock_cap_sec": args.wall_clock_cap_sec,
            "cost_cap_usd": args.cost_cap_usd,
            "estimated_cost_per_live_call_usd": args.estimated_cost_per_live_call_usd,
            "live_batch_size": args.live_batch_size,
            "no_progress_patience": args.no_progress_patience,
            "repeated_failure_stop": args.repeated_failure_stop,
            "pass_threshold": CAPS["pass_threshold"],
        },
        "families": families,
        "seeds": seeds,
        "policies": policies,
        "policy_provenance": prior_policy_provenance(),
        "policy_adapter_disclosure": {
            "same_task_rows": "live actor rows use equalized policy adapters over the current task bank, not direct execution of prior controller code",
            "actual_prior_replay": "run --prior-replay-audit for direct bundled r13/current champion/r38 harness execution and hashes",
        },
        "rows": rows,
        "summary": summary,
        "scorer_audit": scorer_audit(),
        "release_checks": release_checks(
            rows,
            summary,
            require_live=False,
            compare_live=bool(args.live_exec and args.actor_mode == "codex"),
            families=families,
            seeds=seeds,
            policies=policies,
        ),
        "live_policy_calls": live_policy_calls,
        "estimated_total_cost_usd": round(total_estimated_cost, 4),
        "wall_sec": round(time.monotonic() - started, 3),
    }
    compare["compare_sha256"] = digest({k: v for k, v in compare.items() if k != "compare_sha256"})
    write_json(args.out, compare)
    return compare


def row_record(
    task: Task,
    policy: str,
    artifact: dict[str, Any],
    passed: bool,
    score: float,
    failures: list[dict[str, Any]],
    round_index: int,
    calls: int,
    stop_reason: str,
    actor_ok: bool,
    args: argparse.Namespace,
    raw_artifact: Path | None,
) -> dict[str, Any]:
    return {
        "family": task.family,
        "seed": task.seed,
        "policy": policy,
        "round": round_index,
        "calls": calls,
        "honest_pass": bool(passed),
        "score": round(score, 6),
        "failures": failures[:5],
        "stop_reason": stop_reason,
        "artifact_sha256": digest(artifact),
        "truth_digest": digest(task.truth),
        "actor_ok": bool(actor_ok),
        "actor_mode": args.actor_mode,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "live_execution": bool(args.live_exec and args.actor_mode == "codex" and policy != "bad_scorer_control"),
        "raw_artifact": str(raw_artifact) if raw_artifact else None,
    }


def cap_row(task: Task, policy: str, args: argparse.Namespace, reason: str) -> dict[str, Any]:
    return row_record(task, policy, {}, False, 0.0, [{"case": reason, "expected": "completed under caps", "got": reason}], 0, 0, reason, False, args, None)


def capped_last_row(state: dict[str, Any], task: Task, policy: str, args: argparse.Namespace, reason: str) -> dict[str, Any]:
    last = state.get("last_row")
    if isinstance(last, dict):
        row = copy.deepcopy(last)
        row["stop_reason"] = reason
        row.setdefault("failures", [])
        row["failures"] = [{"case": reason, "expected": "completed under caps", "got": reason}] + list(row.get("failures", []))[:4]
        return row
    return cap_row(task, policy, args, reason)


def update_stop_state(state: dict[str, Any], artifact: dict[str, Any], score: float, passed: bool, args: argparse.Namespace) -> str | None:
    if passed:
        return None
    artifact_sha = digest(artifact)
    if state.get("last_sha") == artifact_sha:
        state["artifact_streak"] = int(state.get("artifact_streak", 1)) + 1
    else:
        state["last_sha"] = artifact_sha
        state["artifact_streak"] = 1
    best = state.get("best_score")
    if best is None or float(score) > float(best):
        state["best_score"] = float(score)
        state["no_progress"] = 0
    else:
        state["no_progress"] = int(state.get("no_progress", 0)) + 1
    if int(state["artifact_streak"]) >= int(args.repeated_failure_stop):
        return "repeated_failure_stop"
    if int(state["no_progress"]) >= int(args.no_progress_patience):
        return "no_progress_patience"
    return None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_policy: dict[str, list[dict[str, Any]]] = {}
    by_family_policy: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        by_policy.setdefault(row["policy"], []).append(row)
        by_family_policy.setdefault(row["family"], {}).setdefault(row["policy"], []).append(row)
    policy_summary: dict[str, Any] = {}
    for policy, prows in by_policy.items():
        n = len(prows)
        policy_summary[policy] = {
            "cells": n,
            "pass_rate": round(sum(1 for r in prows if r["honest_pass"]) / max(n, 1), 6),
            "score_avg": round(sum(float(r["score"]) for r in prows) / max(n, 1), 6),
            "calls_avg": round(sum(float(r["calls"]) for r in prows) / max(n, 1), 6),
            "stop_reasons": sorted({r["stop_reason"] for r in prows}),
        }
    family_summary: dict[str, Any] = {}
    for family, policies in by_family_policy.items():
        family_summary[family] = {}
        for policy, prows in policies.items():
            n = len(prows)
            family_summary[family][policy] = {
                "pass_rate": round(sum(1 for r in prows if r["honest_pass"]) / max(n, 1), 6),
                "score_avg": round(sum(float(r["score"]) for r in prows) / max(n, 1), 6),
                "calls_avg": round(sum(float(r["calls"]) for r in prows) / max(n, 1), 6),
            }
    return {"by_policy": policy_summary, "by_family_policy": family_summary}


def scorer_audit() -> dict[str, Any]:
    rows = scorer_audit_rows()
    return {
        "overall_pass": all(row["ok"] for row in rows),
        "rows": rows,
        "required_case_types": [
            "golden_positive",
            "hard_negative",
            "paraphrase_equivalent_positive",
            "distractor_false_positive",
            "runner_malfunction",
        ],
    }


def release_checks(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    require_live: bool,
    compare_live: bool,
    families: Iterable[str] | None = None,
    seeds: Iterable[int | str] | None = None,
    policies: Iterable[str] | None = None,
) -> dict[str, Any]:
    families_list = [str(f) for f in (families if families is not None else FAMILIES)]
    seeds_list = [int(s) for s in (seeds if seeds is not None else SEEDS)]
    policies_list = [str(p) for p in (policies if policies is not None else POLICIES)]
    by_policy = summary["by_policy"]
    candidate = by_policy.get(CANDIDATE_ID, {})
    required_cells = len(families_list) * len(seeds_list) * len(policies_list)
    actor_cells = [r for r in rows if r["policy"] != "bad_scorer_control"]
    expected_keys = {(family, seed, policy) for family in families_list for seed in seeds_list for policy in policies_list}
    observed_keys = {(str(r.get("family")), int(r.get("seed")), str(r.get("policy"))) for r in rows}
    cell_count_ok = len(rows) == required_cells and observed_keys == expected_keys
    candidate_pass_rate = float(candidate.get("pass_rate", 0.0))
    required_policy_set = set(REQUIRED_PRIOR_POLICIES) | set(ABLATION_POLICIES) | {CANDIDATE_ID, "bad_scorer_control"}
    required_policy_coverage = required_policy_set.issubset(set(policies_list))
    baseline_lift = {}
    for baseline in REQUIRED_PRIOR_POLICIES:
        b = by_policy.get(baseline, {})
        baseline_lift[baseline] = int(b.get("cells", 0)) == len(families_list) * len(seeds_list) and strictly_better_summary(candidate, b)
    ablation_weaker = {}
    for ablation in ABLATION_POLICIES:
        a = by_policy.get(ablation, {})
        ablation_weaker[ablation] = int(a.get("cells", 0)) == len(families_list) * len(seeds_list) and strictly_better_summary(candidate, a)
    per_family_lift: dict[str, bool] = {}
    for family in families_list:
        fs = summary["by_family_policy"].get(family, {})
        c = fs.get(CANDIDATE_ID, {})
        per_family_lift[family] = all(strictly_better_summary(c, fs.get(base, {})) for base in REQUIRED_PRIOR_POLICIES)
    live_identity_ok = bool(compare_live) and all(r.get("live_execution") is True and r.get("actor_mode") == "codex" for r in actor_cells)
    bad_scorer_ok = by_policy.get("bad_scorer_control", {}).get("pass_rate") == 0.0
    checks = {
        "schema_ok": True,
        "minimum_three_families": len(families_list) >= 3 and set(FAMILIES).issubset(set(families_list)),
        "repeat_seed_count": len(seeds_list) >= 2,
        "required_policy_coverage": required_policy_coverage,
        "grid_complete": cell_count_ok,
        "candidate_evaluable": CANDIDATE_ID in by_policy and int(candidate.get("cells", 0)) == len(families_list) * len(seeds_list),
        "missing_required_cells": sorted([":".join(map(str, key)) for key in (expected_keys - observed_keys)])[:80],
        "unexpected_cells": sorted([":".join(map(str, key)) for key in (observed_keys - expected_keys)])[:80],
        "cell_count_ok": cell_count_ok,
        "candidate_pass_rate_1": candidate_pass_rate == 1.0,
        "baseline_lift_vs_required": baseline_lift,
        "all_required_baselines_beaten": all(baseline_lift.values()),
        "ablation_weaker": ablation_weaker,
        "all_ablations_weaker": all(ablation_weaker.values()),
        "per_family_lift_vs_required_baselines": per_family_lift,
        "nontrivial_lift_family_count": sum(1 for ok in per_family_lift.values() if ok),
        "multi_domain_lift": sum(1 for ok in per_family_lift.values() if ok) >= 3,
        "scorer_audit_pass": scorer_audit()["overall_pass"],
        "bad_scorer_control_rejected": bad_scorer_ok,
        "live_actor_identity_ok": live_identity_ok,
        "require_live": bool(require_live),
    }
    structural_pass = (
        checks["minimum_three_families"]
        and checks["repeat_seed_count"]
        and checks["required_policy_coverage"]
        and checks["cell_count_ok"]
        and checks["candidate_pass_rate_1"]
        and checks["all_required_baselines_beaten"]
        and checks["all_ablations_weaker"]
        and checks["multi_domain_lift"]
        and checks["scorer_audit_pass"]
        and checks["bad_scorer_control_rejected"]
    )
    checks["structural_overall_pass"] = structural_pass
    checks["overall_pass"] = structural_pass and (not require_live or live_identity_ok)
    checks["promotion_ready"] = checks["overall_pass"] and bool(require_live)
    checks["ready_to_continue"] = (not checks["promotion_ready"]) and checks["minimum_three_families"] and checks["repeat_seed_count"] and checks["required_policy_coverage"]
    return checks


def strictly_better_summary(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    c_pass = float(candidate.get("pass_rate", 0.0))
    b_pass = float(baseline.get("pass_rate", 0.0))
    c_score = float(candidate.get("score_avg", 0.0))
    b_score = float(baseline.get("score_avg", 0.0))
    c_calls = float(candidate.get("calls_avg", 999.0))
    b_calls = float(baseline.get("calls_avg", 999.0))
    return c_pass > b_pass or c_score > b_score or ((c_pass >= b_pass and c_score >= b_score) and c_calls < b_calls)


def raw_artifact_integrity(compare: dict[str, Any], expected_actor: dict[str, str]) -> dict[str, Any]:
    bad: list[dict[str, Any]] = []
    checked = 0
    seen_dirs: set[str] = set()
    for row in compare.get("rows", []):
        if row.get("policy") == "bad_scorer_control":
            continue
        if row.get("stop_reason") in {"wall_clock_cap", "cost_cap"}:
            continue
        if row.get("stop_reason") == "max_rounds" and int(row.get("calls", 0)) == 0:
            continue
        raw_dir = row.get("raw_artifact")
        if not raw_dir:
            bad.append({"row": row_key(row), "error": "missing_raw_artifact_path"})
            continue
        if raw_dir in seen_dirs:
            continue
        seen_dirs.add(str(raw_dir))
        checked += 1
        path = Path(str(raw_dir))
        for filename in ("prompt.txt", "response.txt", "stderr.txt", "actor_process.json", "parsed.json"):
            if not (path / filename).exists():
                bad.append({"row": row_key(row), "path": str(path / filename), "error": "missing_raw_file"})
        process_path = path / "actor_process.json"
        if process_path.exists():
            try:
                process = read_json(process_path)
            except Exception as exc:
                bad.append({"row": row_key(row), "path": str(process_path), "error": f"bad_process_json:{exc}"})
                continue
            if not process.get("live_exec"):
                bad.append({"row": row_key(row), "path": str(process_path), "error": "not_live_exec"})
            if process.get("grid_run_id") != GRID_RUN_ID:
                bad.append({"row": row_key(row), "path": str(process_path), "error": "grid_run_id_mismatch", "got": process.get("grid_run_id")})
            if process.get("outer_round") != ROUND:
                bad.append({"row": row_key(row), "path": str(process_path), "error": "outer_round_mismatch", "got": process.get("outer_round")})
            prompt_digest = digest((path / "prompt.txt").read_text(encoding="utf-8")) if (path / "prompt.txt").exists() else None
            if process.get("prompt_sha256") != prompt_digest:
                bad.append({"row": row_key(row), "path": str(process_path), "error": "prompt_sha256_mismatch", "got": process.get("prompt_sha256")})
            if not process.get("started_at_unix") or not process.get("completed_at_unix"):
                bad.append({"row": row_key(row), "path": str(process_path), "error": "missing_timestamps"})
            if process.get("actor_mode") != expected_actor["mode"]:
                bad.append({"row": row_key(row), "path": str(process_path), "error": "actor_mode_mismatch", "got": process.get("actor_mode")})
            if process.get("model") != expected_actor["model"]:
                bad.append({"row": row_key(row), "path": str(process_path), "error": "model_mismatch", "got": process.get("model")})
            if process.get("reasoning_effort") != expected_actor["reasoning_effort"]:
                bad.append({"row": row_key(row), "path": str(process_path), "error": "reasoning_effort_mismatch", "got": process.get("reasoning_effort")})
    return {"ok": not bad, "checked_raw_dirs": checked, "bad": bad[:50]}


def cap_integrity(compare: dict[str, Any]) -> dict[str, Any]:
    caps = compare.get("caps", {})
    bad: list[dict[str, Any]] = []
    max_calls = int(caps.get("max_calls", 0))
    wall_cap = float(caps.get("wall_clock_cap_sec", 0))
    cost_cap = float(caps.get("cost_cap_usd", 0))
    allowed_stop = {
        "passed_honest",
        "max_calls",
        "max_rounds",
        "wall_clock_cap",
        "cost_cap",
        "no_progress_patience",
        "repeated_failure_stop",
        "bad_scorer_control_rejected",
        "one_shot_complete",
    }
    for row in compare.get("rows", []):
        if int(row.get("calls", 0)) > max_calls:
            bad.append({"row": row_key(row), "error": "calls_exceed_cap", "calls": row.get("calls"), "max_calls": max_calls})
        if row.get("stop_reason") not in allowed_stop:
            bad.append({"row": row_key(row), "error": "unexpected_stop_reason", "stop_reason": row.get("stop_reason")})
    if float(compare.get("wall_sec", 0.0)) > wall_cap + 5.0:
        has_wall_cap_rows = any(row.get("stop_reason") == "wall_clock_cap" for row in compare.get("rows", []))
        max_actor_timeout = float(caps.get("timeout_sec", 0))
        overrun = float(compare.get("wall_sec", 0.0)) - wall_cap
        if not (has_wall_cap_rows and overrun <= max_actor_timeout + 30.0):
            bad.append({"error": "wall_clock_cap_exceeded", "wall_sec": compare.get("wall_sec"), "wall_cap": wall_cap})
    if float(compare.get("estimated_total_cost_usd", 0.0)) > cost_cap + 1e-9:
        bad.append({"error": "cost_cap_exceeded", "estimated_total_cost_usd": compare.get("estimated_total_cost_usd"), "cost_cap": cost_cap})
    return {"ok": not bad, "bad": bad[:50]}


def row_key(row: dict[str, Any]) -> str:
    return f"{row.get('family')}:{row.get('seed')}:{row.get('policy')}:r{row.get('round')}"


def release_gate(args: argparse.Namespace) -> dict[str, Any]:
    compare = read_json(args.compare)
    checks = release_checks(
        compare.get("rows", []),
        compare.get("summary", {}),
        require_live=bool(args.require_live),
        compare_live=bool(compare.get("live_execution")),
        families=compare.get("families", FAMILIES),
        seeds=compare.get("seeds", SEEDS),
        policies=compare.get("policies", POLICIES),
    )
    actor_expected = {
        "mode": args.expected_actor_mode,
        "model": args.expected_model,
        "reasoning_effort": args.expected_reasoning_effort,
    }
    actor_ok = (
        compare.get("actor_mode") == actor_expected["mode"]
        and compare.get("model") == actor_expected["model"]
        and compare.get("reasoning_effort") == actor_expected["reasoning_effort"]
    )
    if args.require_live:
        checks["expected_actor_identity_ok"] = actor_ok
        raw_ok = raw_artifact_integrity(compare, actor_expected)
        caps_ok = cap_integrity(compare)
        policy_provenance_ok = policy_provenance_audit(compare)
        prior_replay_ok = prior_replay_audit(argparse.Namespace(out=f"{TMP_PREFIX}_prior_replay_gate.json", artifact_dir=f"{TMP_PREFIX}_prior_replay_gate"))
        task_bank_ok = task_bank_audit(argparse.Namespace(out=None))
        prior_ok = prior_artifact_audit(argparse.Namespace(out=None))
        truth_ok = truth_separation_audit(argparse.Namespace(compare=args.compare, out=None))
        checks["raw_artifact_integrity"] = raw_ok
        checks["termination_cap_integrity"] = caps_ok
        checks["policy_provenance_audit"] = policy_provenance_ok
        checks["prior_replay_audit_pass"] = prior_replay_ok["overall_pass"]
        checks["prior_replay_audit_path"] = f"{TMP_PREFIX}_prior_replay_gate.json"
        checks["grid_run_id_ok"] = compare.get("grid_run_id") == GRID_RUN_ID
        checks["task_bank_audit_pass"] = task_bank_ok["overall_pass"]
        checks["prior_artifact_audit_pass"] = prior_ok["overall_pass"]
        checks["truth_separation_audit_pass"] = truth_ok["ok"]
        checks["overall_pass"] = checks["overall_pass"] and actor_ok
        checks["overall_pass"] = checks["overall_pass"] and checks["grid_run_id_ok"] and raw_ok["ok"] and caps_ok["ok"] and policy_provenance_ok["ok"] and prior_replay_ok["overall_pass"] and task_bank_ok["overall_pass"] and prior_ok["overall_pass"] and truth_ok["ok"]
        checks["promotion_ready"] = checks["overall_pass"]
    result = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "compare": args.compare,
        "candidate_id": CANDIDATE_ID,
        "required_actor": actor_expected,
        "checks": checks,
        "overall_pass": checks["overall_pass"],
        "promotion_ready": checks["promotion_ready"],
    }
    write_json(args.out, result)
    return result


def truth_separation_audit(args: argparse.Namespace) -> dict[str, Any]:
    compare = read_json(args.compare)
    bad: list[dict[str, Any]] = []
    checked = 0
    for batch in compare.get("raw_batch_dirs", []):
        prompt_path = Path(batch) / "prompt.txt"
        if not prompt_path.exists():
            bad.append({"batch": batch, "error": "missing_prompt"})
            continue
        text = prompt_path.read_text(encoding="utf-8")
        checked += 1
        for family in compare.get("families", []):
            for seed in compare.get("seeds", []):
                task = make_task(family, int(seed))
                bad.extend(hidden_contamination_findings(task, text, batch=str(batch))[:20])
    result = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "checked_prompts": checked,
        "audit_depth": ["literal_json", "hidden_case_id", "record_id", "string_literal", "word_ngram"],
        "ok": not bad,
        "bad": bad[:20],
    }
    write_json(args.out, result)
    return result


def flatten_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            out.append(str(key))
            out.extend(flatten_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(flatten_strings(item))
    return out


def normalize_leak_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def hidden_contamination_findings(task: Task, text: str, batch: str = "") -> list[dict[str, Any]]:
    """Detect hidden-truth exposure beyond exact JSON string equality.

    The allow-list is deliberately limited to public goal/examples and public
    feedback/audit cases.  Candidate policy prose and generated prompts are not
    allow-listed, so hidden-only aliases or n-grams introduced by the loop are
    caught while ordinary public counterexamples remain legal feedback.
    """
    public_safe = stable_json(
        {
            "goal": task.public_goal,
            "public_cases": task.public_cases,
            "feedback_cases": task.audit_cases.get("feedback_cases", []),
        }
    )
    safe_norm = f" {normalize_leak_text(public_safe)} "
    text_norm = f" {normalize_leak_text(text)} "
    findings: list[dict[str, Any]] = []

    def add(error: str, case_id: str, needle: str) -> None:
        if len(findings) >= 50:
            return
        findings.append(
            {
                "batch": batch,
                "family": task.family,
                "seed": task.seed,
                "case": case_id,
                "error": error,
                "needle_digest": digest(needle),
                "needle_preview": needle[:80],
            }
        )

    for case_id, hidden_case in task.truth.items():
        for key in ("input", "expected"):
            needle = stable_json(hidden_case.get(key))
            if len(needle) >= 24 and needle in text:
                add("hidden_literal_json_leaked", case_id, needle)
        case_norm = normalize_leak_text(str(case_id))
        if len(case_norm) >= 8 and f" {case_norm} " in text_norm and f" {case_norm} " not in safe_norm:
            add("hidden_case_id_leaked", case_id, str(case_id))
        for raw in flatten_strings(hidden_case):
            normalized = normalize_leak_text(raw)
            if not normalized:
                continue
            if re.fullmatch(r"h[0-9]+", normalized) and f" {normalized} " in text_norm and f" {normalized} " not in safe_norm:
                add("hidden_record_id_leaked", case_id, raw)
            if len(normalized) >= 14 and f" {normalized} " in text_norm and f" {normalized} " not in safe_norm:
                add("hidden_string_literal_leaked", case_id, raw)
            words = normalized.split()
            for size in (5, 4, 3):
                if len(words) < size:
                    continue
                for start in range(0, len(words) - size + 1):
                    gram = " ".join(words[start : start + size])
                    if len(gram) < 18:
                        continue
                    wrapped = f" {gram} "
                    if wrapped in text_norm and wrapped not in safe_norm:
                        add("hidden_ngram_leaked", case_id, gram)
                        break
                if findings and findings[-1]["case"] == case_id and findings[-1]["error"] == "hidden_ngram_leaked":
                    break
    return findings


def task_bank_audit(args: argparse.Namespace) -> dict[str, Any]:
    tasks = [make_task(family, seed) for family in FAMILIES for seed in SEEDS]
    rows: list[dict[str, Any]] = []
    candidate_prompt_leaks: list[dict[str, Any]] = []
    candidate_audit_pack_sizes: list[int] = []
    for task in tasks:
        hidden_text = stable_json(task.truth)
        public_text = stable_json(
            {
                "goal": task.public_goal,
                "public_cases": task.public_cases,
                "candidate_policy_instruction": policy_instruction(CANDIDATE_ID),
            }
        )
        leaked = hidden_contamination_findings(task, public_text)
        pack = public_audit_pack_for(CANDIDATE_ID, task)
        candidate_audit_pack_sizes.append(len(pack))
        prompt = prompt_for_batch(CANDIDATE_ID, [task], {})
        candidate_prompt_leaks.extend(hidden_contamination_findings(task, prompt))
        weak_pass, weak_score, _weak_failures = score_artifact(task, {"code": one_shot_code(task.family)})
        rows.append(
            {
                "family": task.family,
                "seed": task.seed,
                "public_cases": len(task.public_cases),
                "feedback_cases": len(task.audit_cases.get("feedback_cases", [])),
                "truth_cases": len(task.truth),
                "hidden_literal_leak": leaked,
                "hidden_contamination_count": len(leaked),
                "weak_one_shot_pass": weak_pass,
                "weak_one_shot_score": round(weak_score, 6),
                "truth_digest": digest(hidden_text),
            }
        )
    family_seed_variation = {
        family: len({row["truth_digest"] for row in rows if row["family"] == family}) == len(SEEDS)
        for family in FAMILIES
    }
    intent_tasks = [task for task in tasks if task.family == "intent_scorer_policy_code"]
    intent_nested_positive = all(
        any(case.get("expected") is True and "nested" in case.get("case_id", "") for case in task.audit_cases.get("feedback_cases", []))
        and any(case.get("expected") is True and "nested" in case.get("case_id", "") for case in task.truth.values())
        for task in intent_tasks
    )
    checks = {
        "three_families": len(FAMILIES) == 3,
        "three_seeds": len(SEEDS) == 3,
        "all_tasks_have_public_feedback_truth": all(r["public_cases"] and r["feedback_cases"] and r["truth_cases"] for r in rows),
        "no_hidden_literals_in_public_prompt": all(not r["hidden_literal_leak"] for r in rows),
        "candidate_public_audit_pack_nonempty": all(size > 0 for size in candidate_audit_pack_sizes),
        "candidate_public_audit_prompt_no_hidden_leak": not candidate_prompt_leaks,
        "public_audit_bootstrap_ablation_present": "candidate_no_public_audit_bootstrap" in ABLATION_POLICIES and "candidate_no_public_audit_bootstrap" in POLICIES,
        "hidden_contamination_ngram_audit_active": True,
        "seed_variation_per_family": all(family_seed_variation.values()),
        "weak_one_shot_not_prebaked": all(not r["weak_one_shot_pass"] for r in rows),
        "intent_nested_positive_transfer_case": intent_nested_positive,
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "checks": checks,
        "family_seed_variation": family_seed_variation,
        "candidate_audit_pack_sizes": candidate_audit_pack_sizes,
        "candidate_prompt_hidden_leak_findings": candidate_prompt_leaks[:20],
        "rows": rows,
        "task_bank_commitment": digest([dataclasses.asdict(task) for task in tasks]),
        "overall_pass": all(checks.values()),
    }
    write_json(args.out, result)
    return result


def prior_artifact_audit(args: argparse.Namespace) -> dict[str, Any]:
    ref_root = reference_materials_root()
    references = {
        "generation_history": ref_root / "generation_history.json",
        "current_champion_reference": ref_root / "current_champion" / "REFERENCE.md",
        "current_champion_code": ref_root / "current_champion" / "code.py",
        "current_champion_explanation": ref_root / "current_champion" / "explanation.md",
        "r13_reference": ref_root / "r13_concrete_counterexample_reference" / "REFERENCE.md",
        "r13_code": ref_root / "r13_concrete_counterexample_reference" / "r13_code.py",
        "r13_explanation": ref_root / "r13_concrete_counterexample_reference" / "r13_explanation.md",
        "r38_reference": ref_root / "r38_feedback_channel_reference" / "REFERENCE.md",
        "r38_code": ref_root / "r38_feedback_channel_reference" / "r38_code.py",
        "r38_explanation": ref_root / "r38_feedback_channel_reference" / "r38_explanation.md",
        "merged_codex_a_r57_composer": ref_root / "merged_line_history" / "codex_a_r57_composer.txt",
        "merged_codex_b_r40_composer": ref_root / "merged_line_history" / "codex_b_r40_composer.txt",
    }
    rows = []
    for name, path in references.items():
        exists = path.exists()
        rows.append(
            {
                "name": name,
                "path": str(path),
                "exists": exists,
                "sha256": digest(path.read_bytes()) if exists else None,
                "bytes": path.stat().st_size if exists else 0,
            }
        )
    generation_ok = False
    registry_id_ok = False
    gen_path = references["generation_history"]
    if gen_path.exists():
        try:
            data = read_json(gen_path)
            generation_ok = "baseline_family" in data and "champions" in data
            registry_id_ok = any(champ.get("id") == CURRENT_CHAMPION for champ in data.get("champions", []))
        except Exception:
            generation_ok = False
    result = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "reference_materials_root": str(ref_root),
        "overall_pass": all(row["exists"] and row["bytes"] > 0 for row in rows) and generation_ok and registry_id_ok,
        "generation_history_ok": generation_ok,
        "current_champion_registry_id_ok": registry_id_ok,
        "rows": rows,
    }
    write_json(args.out, result)
    return result


def run_prior_replay_command(name: str, cmd: list[str], out_path: Path, timeout_sec: int, accepted_returncodes: set[int]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_sec)
        timed_out = False
        returncode = int(proc.returncode)
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = -9
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    duration = round(time.monotonic() - started, 3)
    output_exists = out_path.exists()
    output_json_ok = False
    output_digest = None
    if output_exists:
        try:
            read_json(out_path)
            output_json_ok = True
            output_digest = digest(out_path.read_bytes())
        except Exception:
            output_json_ok = False
            output_digest = digest(out_path.read_bytes())
    return {
        "name": name,
        "cmd": cmd,
        "timeout_sec": timeout_sec,
        "timed_out": timed_out,
        "returncode": returncode,
        "accepted_returncodes": sorted(accepted_returncodes),
        "duration_sec": duration,
        "stdout_sha256": digest(stdout),
        "stderr_sha256": digest(stderr),
        "stdout_prefix": stdout[:600],
        "stderr_prefix": stderr[:600],
        "out_path": str(out_path),
        "out_exists": output_exists,
        "out_json_ok": output_json_ok,
        "out_sha256": output_digest,
        "ok": (not timed_out) and returncode in accepted_returncodes and output_exists and output_json_ok,
    }


def prior_replay_audit(args: argparse.Namespace) -> dict[str, Any]:
    """Execute bundled prior harnesses in local/offline mode.

    This is not same-task live superiority evidence. It is a provenance guard
    against replacing r13/r38/current champion with invented weak policy names:
    the submitted package proves the prior code is present, runnable, hashed,
    and produces machine-readable replay artifacts under explicit caps.
    """
    ref_root = reference_materials_root()
    out_root = Path(getattr(args, "artifact_dir", "") or f"{TMP_PREFIX}_prior_replay")
    out_root.mkdir(parents=True, exist_ok=True)
    r13_code = ref_root / "r13_concrete_counterexample_reference" / "r13_code.py"
    champion_code = ref_root / "current_champion" / "code.py"
    r38_code = ref_root / "r38_feedback_channel_reference" / "r38_code.py"
    commands = [
        (
            "r13_self_test",
            [
                sys.executable,
                "-B",
                str(r13_code),
                "--self-test",
                "--out",
                str(out_root / "r13_selftest.json"),
                "--artifact-dir",
                str(out_root / "r13_selftest_artifacts"),
            ],
            out_root / "r13_selftest.json",
            180,
            {0},
        ),
        (
            "current_champion_self_test",
            [
                sys.executable,
                "-B",
                str(champion_code),
                "--self-test",
                "--out",
                str(out_root / "current_champion_selftest.json"),
                "--artifact-dir",
                str(out_root / "current_champion_selftest_artifacts"),
            ],
            out_root / "current_champion_selftest.json",
            180,
            {0},
        ),
        (
            "r13_local_compare_replay",
            [
                sys.executable,
                "-B",
                str(r13_code),
                "--compare-baseline",
                "--actor-mode",
                "local",
                "--task",
                "bencode_strict_codec",
                "--policies",
                "one_shot,r133_bare_goal,r38_bare_goal,candidate,candidate_no_counterexample_ablation",
                "--seeds",
                "95,96",
                "--max-rounds",
                "4",
                "--max-calls",
                "4",
                "--timeout-sec",
                "10",
                "--wall-clock-cap-sec",
                "300",
                "--max-total-budget-usd",
                "999",
                "--out",
                str(out_root / "r13_local_compare.json"),
                "--artifact-dir",
                str(out_root / "r13_local_compare_artifacts"),
            ],
            out_root / "r13_local_compare.json",
            180,
            {0, 3},
        ),
        (
            "r38_self_test",
            [
                sys.executable,
                "-B",
                str(r38_code),
                "--self-test",
                "--out",
                str(out_root / "r38_selftest.json"),
                "--artifact-dir",
                str(out_root / "r38_selftest_artifacts"),
            ],
            out_root / "r38_selftest.json",
            120,
            {0, 2},
        ),
        (
            "r38_local_compare_replay",
            [
                sys.executable,
                "-B",
                str(r38_code),
                "--compare-baseline",
                "--actor-mode",
                "local",
                "--seeds",
                "38,39",
                "--trials",
                "2",
                "--policies",
                "one_shot,older_minus23_loop,actual_minus23_r133_transplant,r133_full_loop,r133_full_loop_same_candidate_info,pass2_meta23,candidate,candidate_redacted_only,ablation_no_public_counterexamples",
                "--max-rounds",
                "4",
                "--max-calls",
                "4",
                "--timeout-sec",
                "10",
                "--wall-clock-cap-sec",
                "300",
                "--max-budget-usd",
                "999",
                "--out",
                str(out_root / "r38_local_compare.json"),
                "--artifact-dir",
                str(out_root / "r38_local_compare_artifacts"),
            ],
            out_root / "r38_local_compare.json",
            120,
            {0, 3},
        ),
    ]
    rows = [run_prior_replay_command(name, cmd, out_path, timeout, accepted) for name, cmd, out_path, timeout, accepted in commands]
    r38_selftest_path = out_root / "r38_selftest.json"
    r38_anchor_gap_recorded = False
    if r38_selftest_path.exists():
        try:
            r38_selftest = read_json(r38_selftest_path)
            r38_checks = r38_selftest.get("checks", {})
            r38_anchor_gap_recorded = (
                r38_selftest.get("passed") is False
                and r38_checks.get("actual_r133_baseline_anchor_passed") is False
                and all(ok for name, ok in r38_checks.items() if name != "actual_r133_baseline_anchor_passed")
            )
        except Exception:
            r38_anchor_gap_recorded = False
    checks = {
        "r13_code_present": r13_code.exists(),
        "current_champion_code_present": champion_code.exists(),
        "r38_code_present": r38_code.exists(),
        "all_replay_commands_ran": all(row["ok"] for row in rows),
        "actual_prior_outputs_machine_readable": all(row["out_json_ok"] for row in rows),
        "r13_current_champion_same_digest_recorded": digest(r13_code.read_bytes()) == digest(champion_code.read_bytes()) if r13_code.exists() and champion_code.exists() else False,
        "r38_optional_r133_anchor_gap_recorded": r38_anchor_gap_recorded,
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "artifact_dir": str(out_root),
        "reference_materials_root": str(ref_root),
        "checks": checks,
        "rows": rows,
        "overall_pass": all(checks.values()),
        "note": "Local replay anchors bundled prior harnesses; same-task live superiority still comes only from the current compare artifact.",
    }
    write_json(args.out, result)
    return result


def emit_package(args: argparse.Namespace) -> dict[str, Any]:
    code_path = Path(__file__).resolve()
    code_bytes = code_path.read_bytes()
    package = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "candidate_id": CANDIDATE_ID,
        "current_champion": CURRENT_CHAMPION,
        "verifier_revision": VERIFIER_REVISION,
        "grid_run_id": GRID_RUN_ID,
        "code_sha256": digest(code_bytes),
        "script_ref": script_ref(),
        "commands": command_manifest(),
        "families": list(FAMILIES),
        "seeds": list(SEEDS),
        "default_live_release_seeds": list(LIVE_RELEASE_SEEDS),
        "policies": list(POLICIES),
        "caps": CAPS,
        "baseline_family": list(REQUIRED_PRIOR_POLICIES),
        "ablation_policies": list(ABLATION_POLICIES),
        "task_bank_commitment": digest([dataclasses.asdict(make_task(f, s)) for f in FAMILIES for s in SEEDS]),
        "workspace_root_resolution": "searches parents for reference_materials/generation_history.json plus copied baseline_reference/reference_materials packages",
        "anti_cheat": {
            "first_prompt_expected_literal_audit": "truth-separation-audit",
            "mock_cannot_pass_require_live": True,
            "bad_scorer_control": True,
            "inner_codex_config_isolated": "--ignore-user-config avoids loading MCP servers during inner live actor calls while retaining Codex auth/model/effort identity",
            "actual_prior_policy_provenance": prior_policy_provenance(),
            "actual_prior_replay_audit_command": command_manifest()["prior_replay_audit"],
            "raw_actor_artifacts_required": ["prompt.txt", "response.txt", "stderr.txt", "actor_process.json", "parsed.json"],
        },
    }
    package["package_sha256"] = digest({k: v for k, v in package.items() if k != "package_sha256"})
    write_json(args.out, package)
    return package


def validate_package(args: argparse.Namespace) -> dict[str, Any]:
    package = read_json(args.package)
    commands = package.get("commands", {})
    checks = {
        "schema_ok": package.get("schema_version") == SCHEMA_VERSION,
        "round_ok": package.get("round") == ROUND,
        "candidate_ok": package.get("candidate_id") == CANDIDATE_ID,
        "commands_present": all(name in commands for name in command_manifest()),
        "commands_reference_current_round": all(f"round_{ROUND}/code.py" in cmd or Path(__file__).name in cmd for cmd in commands.values()),
        "live_command_uses_codex_gpt55_xhigh": "codex" in commands.get("live_codex_grid", "") and "gpt-5.5" in commands.get("live_codex_grid", "") and "xhigh" in commands.get("live_codex_grid", ""),
        "inner_codex_config_isolated": "--ignore-user-config" in Path(__file__).read_text(encoding="utf-8"),
        "package_sha_ok": package.get("package_sha256") == digest({k: v for k, v in package.items() if k != "package_sha256"}),
    }
    result = {"schema_version": SCHEMA_VERSION, "round": ROUND, "checks": checks, "overall_pass": all(checks.values())}
    write_json(args.out, result)
    return result


def release_evidence(args: argparse.Namespace) -> dict[str, Any]:
    compare_path = args.compare or LIVE_COMPARE_PATH
    artifact_dir = args.artifact_dir or LIVE_ARTIFACT_DIR
    paths = {
        "compare": compare_path,
        "release_gate": f"{TMP_PREFIX}_live_release_gate.json" if args.live_exec else f"{TMP_PREFIX}_mock_release_gate.json",
        "truth_separation_audit": f"{TMP_PREFIX}_truth_separation_audit.json",
        "task_bank_audit": f"{TMP_PREFIX}_task_bank_audit.json",
        "prior_artifact_audit": f"{TMP_PREFIX}_prior_artifact_audit.json",
        "prior_replay_audit": f"{TMP_PREFIX}_prior_replay_audit.json",
        "scorer_audit": f"{TMP_PREFIX}_scorer_audit.json",
        "package": f"{TMP_PREFIX}_candidate.json",
        "package_validation": f"{TMP_PREFIX}_package_validation.json",
    }
    scorer = scorer_audit()
    write_json(paths["scorer_audit"], scorer)
    task_bank = task_bank_audit(argparse.Namespace(out=paths["task_bank_audit"]))
    prior = prior_artifact_audit(argparse.Namespace(out=paths["prior_artifact_audit"]))
    prior_replay = prior_replay_audit(argparse.Namespace(out=paths["prior_replay_audit"], artifact_dir=f"{TMP_PREFIX}_prior_replay"))
    compare = compare_baseline(
        argparse.Namespace(
            **{
                **vars(args),
                "compare_baseline": True,
                "artifact_dir": artifact_dir,
                "out": compare_path,
                "families": args.families,
                "seeds": args.seeds,
                "policies": args.policies,
            }
        )
    )
    truth = truth_separation_audit(argparse.Namespace(compare=compare_path, out=paths["truth_separation_audit"]))
    gate = release_gate(
        argparse.Namespace(
            compare=compare_path,
            require_live=bool(args.live_exec and args.actor_mode == "codex"),
            expected_actor_mode="codex",
            expected_model=args.model,
            expected_reasoning_effort=args.reasoning_effort,
            out=paths["release_gate"],
        )
    )
    package = emit_package(argparse.Namespace(out=paths["package"]))
    package_validation = validate_package(argparse.Namespace(package=paths["package"], out=paths["package_validation"]))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "candidate_id": CANDIDATE_ID,
        "live_requested": bool(args.live_exec and args.actor_mode == "codex"),
        "paths": paths,
        "compare_sha256": compare.get("compare_sha256"),
        "checks": {
            "scorer_audit_pass": scorer["overall_pass"],
            "task_bank_audit_pass": task_bank["overall_pass"],
            "prior_artifact_audit_pass": prior["overall_pass"],
            "prior_replay_audit_pass": prior_replay["overall_pass"],
            "truth_separation_audit_pass": truth["ok"],
            "release_gate_pass": gate["overall_pass"],
            "package_validation_pass": package_validation["overall_pass"],
        },
        "overall_pass": bool(
            scorer["overall_pass"]
            and task_bank["overall_pass"]
            and prior["overall_pass"]
            and prior_replay["overall_pass"]
            and truth["ok"]
            and gate["overall_pass"]
            and package_validation["overall_pass"]
        ),
        "promotion_ready": bool(gate["promotion_ready"]),
        "summary": compare.get("summary", {}),
        "release_gate": gate,
        "package_sha256": package.get("package_sha256"),
        "commands": command_manifest(),
    }
    manifest["manifest_sha256"] = digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    write_json(args.out, manifest)
    return manifest


def direct_actor_probe(args: argparse.Namespace) -> dict[str, Any]:
    """Run the submitted actor adapter once and preserve raw provenance.

    This is not superiority evidence. It is a small, evaluator-runnable health
    check that distinguishes "the loop failed" from "the selected live actor did
    not return under the enforced cap".
    """
    root = Path(args.artifact_dir)
    root.mkdir(parents=True, exist_ok=True)
    prompt = (
        "Return exactly one JSON object and no markdown: "
        '{"ok": true, "probe": "meta23_round81_codex_actor"}'
    )
    (root / "prompt.txt").write_text(prompt, encoding="utf-8")
    common_process = {
        "grid_run_id": GRID_RUN_ID,
        "outer_round": ROUND,
        "probe": "direct_actor_probe",
        "prompt_sha256": digest(prompt),
        "started_at_unix": int(time.time()),
        "actor_mode": args.actor_mode,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "live_exec": bool(args.live_exec),
    }
    if args.actor_mode != "codex" or not args.live_exec:
        parsed = {"ok": True, "probe": "mock_adapter_only"}
        process = {**common_process, "returncode": 0, "mock": True, "completed_at_unix": int(time.time()), "wall_sec": 0.0}
        (root / "response.txt").write_text(stable_json(parsed), encoding="utf-8")
        (root / "stderr.txt").write_text("", encoding="utf-8")
        write_json(root / "parsed.json", parsed)
        write_json(root / "actor_process.json", process)
        result = {"schema_version": SCHEMA_VERSION, "round": ROUND, "artifact_dir": str(root), "overall_pass": True, "live_requested": False, "process": process, "parsed": parsed}
        write_json(args.out, result)
        return result

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(Path(tempfile.gettempdir()) / f"meta23_r{ROUND}_pycache")
    last_message = root / "last_message.txt"
    cmd = [
        args.actor_cli,
        "exec",
        "-",
        "-C",
        str(root),
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--model",
        args.model,
        "-c",
        f'model_reasoning_effort="{args.reasoning_effort}"',
        "-c",
        "features.fast_mode=false",
        "--output-last-message",
        str(last_message),
    ]
    returncode, stdout, stderr, timed_out, wall_sec = run_actor_process(cmd, prompt, int(args.timeout_sec), root, env)
    raw = stdout.strip()
    if last_message.exists() and last_message.read_text(encoding="utf-8").strip():
        raw = last_message.read_text(encoding="utf-8").strip()
    (root / "response.txt").write_text(raw, encoding="utf-8")
    (root / "stderr.txt").write_text(stderr, encoding="utf-8")
    process = {
        **common_process,
        "returncode": returncode,
        "timeout": bool(timed_out),
        "cmd": cmd,
        "wall_sec": round(wall_sec, 3),
        "completed_at_unix": int(time.time()),
        "stderr_prefix": stderr[:300],
    }
    write_json(root / "actor_process.json", process)
    parsed: dict[str, Any]
    parse_error = None
    if timed_out:
        parsed = {"runner_malfunction": "actor_timeout", "timeout_sec": int(args.timeout_sec)}
    elif returncode != 0:
        parsed = {"runner_malfunction": "actor_exit", "returncode": returncode}
    else:
        try:
            parsed = extract_json_object(raw)
        except Exception as exc:
            parsed = {"runner_malfunction": "parse_error", "raw_prefix": raw[:1000]}
            parse_error = str(exc)
    write_json(root / "parsed.json", parsed)
    result = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "artifact_dir": str(root),
        "live_requested": True,
        "overall_pass": bool(returncode == 0 and not timed_out and parse_error is None and parsed.get("ok") is True),
        "process": process,
        "parsed": parsed,
        "parse_error": parse_error,
    }
    write_json(args.out, result)
    return result


def partial_live_status(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.artifact_dir)
    batches: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    if root.exists():
        parsed_paths = sorted(set(root.glob("*/round_*/parsed.json")) | set(root.glob("*/round_*/batch_*/parsed.json")))
        for parsed_path in parsed_paths:
            batch_dir = parsed_path.parent
            if batch_dir.name.startswith("batch_"):
                policy = batch_dir.parent.parent.name
                round_text = batch_dir.parent.name.replace("round_", "")
            else:
                policy = batch_dir.parent.name
                round_text = batch_dir.name.replace("round_", "")
            try:
                round_index = int(round_text)
            except ValueError:
                round_index = -1
            process_path = batch_dir / "actor_process.json"
            process = read_json(process_path) if process_path.exists() else {}
            process = read_json(process_path) if process_path.exists() else {}
            expected_families = process.get("families") if isinstance(process.get("families"), list) else []
            expected_seeds = process.get("seeds") if isinstance(process.get("seeds"), list) else []
            pending = []
            for family, seed in zip(expected_families, expected_seeds):
                try:
                    pending.append(make_task(str(family), int(seed)))
                except Exception:
                    pass
            parsed = complete_expected_cells(normalize_actor_parsed(read_json(parsed_path), pending), pending)
            cells = parsed.get("cells", []) if isinstance(parsed, dict) else []
            batch_row = {
                "policy": policy,
                "round": round_index,
                "path": str(batch_dir),
                "raw_files_ok": all((batch_dir / name).exists() for name in ("prompt.txt", "response.txt", "stderr.txt", "actor_process.json", "parsed.json")),
                "process": {
                    "returncode": process.get("returncode"),
                    "wall_sec": process.get("wall_sec"),
                    "actor_mode": process.get("actor_mode"),
                    "model": process.get("model"),
                    "reasoning_effort": process.get("reasoning_effort"),
                    "live_exec": process.get("live_exec"),
                },
                "cells": len(cells),
            }
            batches.append(batch_row)
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                family = str(cell.get("family"))
                seed = int(cell.get("seed"))
                task = make_task(family, seed)
                passed, score, failures = score_artifact(task, cell.get("artifact", {}))
                rows.append(
                    {
                        "family": family,
                        "seed": seed,
                        "policy": policy,
                        "round": round_index,
                        "honest_pass": passed,
                        "score": round(score, 6),
                        "failures": failures[:3],
                    }
                )
    by_family_policy: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        by_family_policy.setdefault(row["family"], {}).setdefault(row["policy"], []).append(row)
    one_shot_round1 = [r for r in rows if r["policy"] == "one_shot" and r["round"] == 1]
    saturated = []
    for family in sorted({r["family"] for r in one_shot_round1}):
        frows = [r for r in one_shot_round1 if r["family"] == family]
        if frows and all(r["honest_pass"] for r in frows):
            saturated.append(family)
    status = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "artifact_dir": str(root),
        "completed_batches": len(batches),
        "completed_cells": len(rows),
        "batches": batches,
        "by_family_policy": {
            family: {
                policy: {
                    "cells": len(prows),
                    "pass_rate": round(sum(1 for r in prows if r["honest_pass"]) / max(len(prows), 1), 6),
                    "score_avg": round(sum(float(r["score"]) for r in prows) / max(len(prows), 1), 6),
                }
                for policy, prows in policies.items()
            }
            for family, policies in by_family_policy.items()
        },
        "one_shot_round1_saturated_families": saturated,
        "promotion_ready": False,
        "overall_pass": False,
        "blocker": "partial_live_only" if batches else "no_live_batches",
        "calibration_blocker": "one_shot_saturated_required_families" if saturated else None,
        "next_release_command": command_manifest()["live_release_evidence_bundle"],
    }
    write_json(args.out, status)
    return status


def self_test(args: argparse.Namespace) -> dict[str, Any]:
    tmp = Path(args.artifact_dir or tempfile.mkdtemp(prefix=f"meta23_r{ROUND}_selftest_"))
    tmp.mkdir(parents=True, exist_ok=True)
    audit = scorer_audit()
    compare = compare_baseline(
        argparse.Namespace(
            **{
                **vars(args),
                "compare_baseline": True,
                "actor_mode": "mock",
                "live_exec": False,
                "artifact_dir": str(tmp / "mock_artifacts"),
                "out": str(tmp / "mock_compare.json"),
                "families": ",".join(FAMILIES),
                "seeds": ",".join(str(s) for s in SEEDS),
                "policies": ",".join(POLICIES),
            }
        )
    )
    gate = release_gate(
        argparse.Namespace(
            compare=str(tmp / "mock_compare.json"),
            require_live=False,
            expected_actor_mode="codex",
            expected_model="gpt-5.5",
            expected_reasoning_effort="xhigh",
            out=str(tmp / "mock_gate.json"),
        )
    )
    live_gate = release_gate(
        argparse.Namespace(
            compare=str(tmp / "mock_compare.json"),
            require_live=True,
            expected_actor_mode="codex",
            expected_model="gpt-5.5",
            expected_reasoning_effort="xhigh",
            out=str(tmp / "mock_as_live_gate.json"),
        )
    )
    package = emit_package(argparse.Namespace(out=str(tmp / "candidate.json")))
    package_validation = validate_package(argparse.Namespace(package=str(tmp / "candidate.json"), out=str(tmp / "package_validation.json")))
    task_bank = task_bank_audit(argparse.Namespace(out=str(tmp / "task_bank_audit.json")))
    prior = prior_artifact_audit(argparse.Namespace(out=str(tmp / "prior_artifact_audit.json")))
    release_manifest = release_evidence(
        argparse.Namespace(
            **{
                **vars(args),
                "live_exec": False,
                "actor_mode": "mock",
                "artifact_dir": str(tmp / "release_mock_artifacts"),
                "compare": str(tmp / "release_mock_compare.json"),
                "out": str(tmp / "release_manifest.json"),
                "families": ",".join(FAMILIES),
                "seeds": ",".join(str(s) for s in SEEDS),
                "policies": ",".join(POLICIES),
            }
        )
    )
    portable_path = tmp / "solver_code.py"
    shutil.copyfile(Path(__file__).resolve(), portable_path)
    portable = subprocess.run([sys.executable, "-B", str(portable_path), "--scorer-audit", "--out", str(tmp / "portable_audit.json")], text=True, capture_output=True, timeout=30)
    exact_two_files = sorted(p.name for p in (Path.cwd() / f"round_{ROUND}").glob("*") if p.is_file()) == ["code.py", "explanation.md"] if (Path.cwd() / f"round_{ROUND}").exists() else True
    release_manifest_recorded = (tmp / "release_manifest.json").exists()
    mock_gate_recorded = isinstance(gate, dict) and "overall_pass" in gate
    result = {
        "schema_version": SCHEMA_VERSION,
        "round": ROUND,
        "overall_pass": bool(
            audit["overall_pass"]
            and mock_gate_recorded
            and not live_gate["overall_pass"]
            and package_validation["overall_pass"]
            and task_bank["overall_pass"]
            and prior["overall_pass"]
            and release_manifest_recorded
            and not release_manifest["promotion_ready"]
            and portable.returncode == 0
            and exact_two_files
        ),
        "promotion_ready": False,
        "reason": "structural checks pass; equalized mock does not assert superiority, and live promotion still requires --compare-baseline --live-exec plus --release-gate --require-live",
        "scorer_audit_pass": audit["overall_pass"],
        "mock_release_gate_recorded": mock_gate_recorded,
        "mock_release_gate_pass": gate["overall_pass"],
        "mock_as_live_rejected": not live_gate["overall_pass"],
        "package_validation_pass": package_validation["overall_pass"],
        "task_bank_audit_pass": task_bank["overall_pass"],
        "prior_artifact_audit_pass": prior["overall_pass"],
        "release_evidence_manifest_recorded": bool(release_manifest_recorded),
        "release_evidence_manifest_pass": release_manifest["overall_pass"],
        "release_evidence_manifest_promotion_ready": release_manifest["promotion_ready"],
        "portable_scorer_audit_rc": portable.returncode,
        "exact_two_files_after_explanation_exists": exact_two_files,
        "mock_compare": str(tmp / "mock_compare.json"),
        "mock_gate": str(tmp / "mock_gate.json"),
        "mock_as_live_gate": str(tmp / "mock_as_live_gate.json"),
        "package": package,
        "release_manifest": str(tmp / "release_manifest.json"),
        "commands": command_manifest(),
        "structural_summary": compare["summary"],
    }
    write_json(args.out, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--scorer-audit", action="store_true")
    parser.add_argument("--compare-baseline", action="store_true")
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--release-evidence", action="store_true")
    parser.add_argument("--direct-actor-probe", action="store_true")
    parser.add_argument("--partial-live-status", action="store_true")
    parser.add_argument("--truth-separation-audit", action="store_true")
    parser.add_argument("--task-bank-audit", action="store_true")
    parser.add_argument("--prior-artifact-audit", action="store_true")
    parser.add_argument("--prior-replay-audit", action="store_true")
    parser.add_argument("--emit-package", action="store_true")
    parser.add_argument("--validate-package", action="store_true")
    parser.add_argument("--package", default=f"{TMP_PREFIX}_candidate.json")
    parser.add_argument("--compare", default=LIVE_COMPARE_PATH)
    parser.add_argument("--out")
    parser.add_argument("--artifact-dir", default=f"{TMP_PREFIX}_artifacts")
    parser.add_argument("--families", default=",".join(FAMILIES))
    parser.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    parser.add_argument("--policies", default=",".join(POLICIES))
    parser.add_argument("--actor-mode", default="mock", choices=["mock", "codex"])
    parser.add_argument("--actor-cli", default="codex")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="xhigh")
    parser.add_argument("--live-exec", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=CAPS["max_rounds"])
    parser.add_argument("--max-calls", type=int, default=CAPS["max_calls"])
    parser.add_argument("--timeout-sec", type=int, default=CAPS["timeout_sec"])
    parser.add_argument("--wall-clock-cap-sec", type=int, default=CAPS["wall_clock_cap_sec"])
    parser.add_argument("--cost-cap-usd", type=float, default=CAPS["cost_cap_usd"])
    parser.add_argument("--estimated-cost-per-live-call-usd", type=float, default=CAPS["estimated_cost_per_live_call_usd"])
    parser.add_argument("--live-batch-size", type=int, default=CAPS["live_batch_size"])
    parser.add_argument("--no-progress-patience", type=int, default=CAPS["no_progress_patience"])
    parser.add_argument("--repeated-failure-stop", type=int, default=CAPS["repeated_failure_stop"])
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--expected-actor-mode", default="codex")
    parser.add_argument("--expected-model", default="gpt-5.5")
    parser.add_argument("--expected-reasoning-effort", default="xhigh")
    args = parser.parse_args(argv)

    if args.self_test:
        result = self_test(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 2
    if args.scorer_audit:
        result = scorer_audit()
        write_json(args.out, result)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 2
    if args.compare_baseline:
        result = compare_baseline(args)
        print(json.dumps({"out": args.out, "release_checks": result["release_checks"], "summary": result["summary"]}, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["release_checks"]["structural_overall_pass"] else 3
    if args.release_gate:
        result = release_gate(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 4
    if args.release_evidence:
        result = release_evidence(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 8
    if args.direct_actor_probe:
        result = direct_actor_probe(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 12
    if args.partial_live_status:
        result = partial_live_status(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0
    if args.truth_separation_audit:
        result = truth_separation_audit(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["ok"] else 5
    if args.task_bank_audit:
        result = task_bank_audit(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 9
    if args.prior_artifact_audit:
        result = prior_artifact_audit(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 7
    if args.prior_replay_audit:
        result = prior_replay_audit(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 10
    if args.emit_package:
        result = emit_package(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0
    if args.validate_package:
        result = validate_package(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return 0 if result["overall_pass"] else 6
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
