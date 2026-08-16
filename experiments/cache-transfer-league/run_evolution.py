#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import run_bootstrap as base


CAMPAIGN_DIR = base.CAMPAIGN_DIR
ROOT = base.ROOT
WORKSPACE = base.WORKSPACE
MODEL_CALLS = base.MODEL_CALLS
TASK = WORKSPACE / "source-snapshots" / "TASK.md"
LEGACY_CONTINUATION_CONTRACT_PATH = CAMPAIGN_DIR / "EVOLUTION-R2-R5-CONTRACT.json"
R6_CONTINUATION_CONTRACT_PATH = CAMPAIGN_DIR / "EVOLUTION-R6-R11-CONTRACT.json"
R100_AMENDMENT_PATH = CAMPAIGN_DIR / "EVOLUTION-R9-R100-AMENDMENT.json"
STOP_AFTER_R96_AMENDMENT_PATH = CAMPAIGN_DIR / "STOP-AFTER-R96-AMENDMENT.json"
FAST_EXECUTOR_EPOCH_CONTRACT_PATH = CAMPAIGN_DIR / "LUNA-FAST-EXECUTOR-EPOCH.json"
FAST_EXECUTOR_EPOCH_ID = "luna-fast-priority-e1"
PRE_FAST_QUARANTINE = WORKSPACE / "quarantine" / "aborted-pre-luna-fast-policy" / "R6"
PRE_FAST_QUARANTINE_MANIFEST = PRE_FAST_QUARANTINE / "quarantine-manifest.json"
CONTINUATION = json.loads(LEGACY_CONTINUATION_CONTRACT_PATH.read_text(encoding="utf-8"))
R6_CONTINUATION = json.loads(R6_CONTINUATION_CONTRACT_PATH.read_text(encoding="utf-8"))
R100_AMENDMENT = json.loads(R100_AMENDMENT_PATH.read_text(encoding="utf-8"))
R100_RANGE = R100_AMENDMENT["authorized_display_round_range"]
PRE_STOP_AUTHORIZED_ROUNDS = tuple(sorted(set(CONTINUATION["authorized_display_rounds"] + R6_CONTINUATION["authorized_display_rounds"] + list(range(int(R100_RANGE["start"]), int(R100_RANGE["end"]) + 1)))))
ACTIVE_STOP_ROUND = int(json.loads(STOP_AFTER_R96_AMENDMENT_PATH.read_text(encoding="utf-8"))["stop_after_display_round"])
AUTHORIZED_ROUNDS = tuple(number for number in PRE_STOP_AUTHORIZED_ROUNDS if number <= ACTIVE_STOP_ROUND)
EXTERNAL_INPUTS = (
    "task",
    "anchor_policy",
    "anchor_contract",
    "task_constraints",
    "candidate_hypothesis",
    "loop_structure",
)
FORBIDDEN_CODE_MARKERS = (
    "class policy",
    "def access",
    "def __init__",
    "```python",
    "```py",
    "policy_source",
    "import collections",
    "from collections",
)
FORBIDDEN_BENCHMARK_MARKERS = (
    CONTINUATION["benchmark"]["fixture_sha256"].casefold(),
    str(CONTINUATION["benchmark"]["seed"]),
    "tiny_hotset",
    "scan_pollution",
    "phase_shift",
    "byte_pressure",
    "cache_policy_loop.py",
    "benchmark_fields_v3",
)
R1_ATOMIC_SHA = CONTINUATION["authoritative_start"]["atomic_state_sha256"]
R1_POLICY_SHA = CONTINUATION["authoritative_start"]["champion_policy_sha256"]
R1_STRUCTURE_SHA = CONTINUATION["authoritative_start"]["champion_structure_sha256"]


def rel(path: Path) -> str:
    return str(path.relative_to(CAMPAIGN_DIR))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise base.CampaignError(f"missing {label}: {path}")
    actual = base.sha256_file(path)
    if actual != expected:
        raise base.CampaignError(f"{label} hash mismatch: {actual} != {expected}")


def analysis_output_contract_violations(parsed: Any) -> list[str]:
    violations: list[str] = []
    if not isinstance(parsed, dict) or parsed.get("artifact_kind") != "analysis_only":
        violations.append("analysis_role_missing_analysis_only_certificate")
    serialized = json.dumps(parsed, sort_keys=True, ensure_ascii=False).casefold()
    if any(marker in serialized for marker in ("class policy", "def access", "```python", "policy_source")):
        violations.append("analysis_role_emitted_policy_code")
    return violations


def load_fast_executor_epoch() -> dict[str, Any]:
    if not FAST_EXECUTOR_EPOCH_CONTRACT_PATH.is_file():
        raise base.CampaignError("Luna Fast executor epoch contract is missing")
    contract = read_json(FAST_EXECUTOR_EPOCH_CONTRACT_PATH)
    if contract.get("executor_epoch_id") != FAST_EXECUTOR_EPOCH_ID:
        raise base.CampaignError("unexpected Luna executor epoch id")
    if contract.get("authorized_display_rounds") != [6, 7, 8, 9, 10, 11]:
        raise base.CampaignError("Luna Fast executor epoch round scope differs")
    boundary = contract.get("effective_inner_model_boundary", {})
    if (
        boundary.get("model"),
        boundary.get("reasoning_effort"),
        boundary.get("service_tier"),
        boundary.get("request_tier"),
        boundary.get("direct_model_substitution"),
    ) != ("gpt-5.6-luna", "high", "fast", "priority", False):
        raise base.CampaignError("Luna Fast executor epoch model boundary differs")
    require_hash(
        R6_CONTINUATION_CONTRACT_PATH,
        contract["superseded_contract_binding"]["sha256"],
        "pre-epoch R6-R11 continuation contract",
    )
    return contract


def load_r100_amendment() -> dict[str, Any]:
    contract = read_json(R100_AMENDMENT_PATH)
    if contract.get("amendment_id") != "cache-display-r100-extension-from-atomic-r8":
        raise base.CampaignError("unexpected R100 amendment id")
    if contract.get("authorized_display_round_range") != {"start": 9, "end": 100}:
        raise base.CampaignError("R100 amendment range differs")
    if contract.get("stop_after_display_round") != 100 or contract.get("cache_r101_permitted") is not False:
        raise base.CampaignError("R100 stop guard differs")
    preserved = {row["path"]: row["sha256"] for row in contract["preserved_immutable_contracts"]}
    require_hash(R6_CONTINUATION_CONTRACT_PATH, preserved[R6_CONTINUATION_CONTRACT_PATH.name], "immutable R6-R11 contract")
    require_hash(FAST_EXECUTOR_EPOCH_CONTRACT_PATH, preserved[FAST_EXECUTOR_EPOCH_CONTRACT_PATH.name], "immutable Luna Fast executor epoch")
    boundary = contract["effective_inner_model_boundary"]
    if (boundary.get("model"), boundary.get("reasoning_effort"), boundary.get("service_tier"), boundary.get("request_tier"), boundary.get("direct_model_substitution")) != (
        "gpt-5.6-luna",
        "high",
        "fast",
        "priority",
        False,
    ):
        raise base.CampaignError("R100 amendment inner model boundary differs")
    return contract


def load_stop_after_r96_amendment() -> dict[str, Any]:
    contract = read_json(STOP_AFTER_R96_AMENDMENT_PATH)
    if contract.get("amendment_id") != "cache-stop-after-active-display-r96":
        raise base.CampaignError("unexpected stop-after-R96 amendment id")
    if contract.get("stop_after_display_round") != 96 or contract.get("cache_r97_permitted") is not False:
        raise base.CampaignError("stop-after-R96 guard differs")
    start = contract["authoritative_start"]
    require_hash(CAMPAIGN_DIR / start["atomic_state_path"], start["atomic_state_sha256"], "stop amendment R95 atomic")
    require_hash(CAMPAIGN_DIR / start["state_path"], start["state_sha256"], "stop amendment R95 state")
    require_hash(CAMPAIGN_DIR / start["champion_policy_path"], start["champion_policy_sha256"], "stop amendment R95 policy")
    require_hash(CAMPAIGN_DIR / start["champion_structure_path"], start["champion_structure_sha256"], "stop amendment R95 structure")
    require_hash(CAMPAIGN_DIR / start["selection_receipt_path"], start["selection_receipt_sha256"], "stop amendment R95 selection")
    preserved = {row["path"]: row["sha256"] for row in contract["preserved_immutable_contracts"]}
    require_hash(R100_AMENDMENT_PATH, preserved[R100_AMENDMENT_PATH.name], "preserved R100 continuation")
    require_hash(FAST_EXECUTOR_EPOCH_CONTRACT_PATH, preserved[FAST_EXECUTOR_EPOCH_CONTRACT_PATH.name], "preserved Fast executor epoch")
    boundary = contract["effective_model_boundary"]
    if (
        boundary["structure_architect"].get("model"),
        boundary["structure_architect"].get("reasoning_effort"),
        boundary["structure_architect"].get("service_tier"),
        boundary["structure_architect"].get("request_tier"),
        boundary["all_inner_roles"].get("model"),
        boundary["all_inner_roles"].get("reasoning_effort"),
        boundary["all_inner_roles"].get("service_tier"),
        boundary["all_inner_roles"].get("request_tier"),
    ) != ("gpt-5.6-sol", "max", "fast", "priority", "gpt-5.6-luna", "high", "fast", "priority"):
        raise base.CampaignError("stop amendment model boundary differs")
    return contract


def effective_model_boundary(contract: dict[str, Any], round_number: int) -> dict[str, Any]:
    models = json.loads(json.dumps(contract["model_boundary"]))
    models["all_inner_roles"] = (
        load_r100_amendment()["effective_inner_model_boundary"]
        if round_number >= 9
        else load_fast_executor_epoch()["effective_inner_model_boundary"]
    )
    return models


def tree_inventory(root: Path) -> tuple[list[dict[str, Any]], str]:
    rows = [
        {
            "path": str(path.relative_to(root)),
            "sha256": base.sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return rows, base.sha256_bytes(base.canonical_bytes(rows))


def quarantine_pre_fast_r6() -> dict[str, Any]:
    if PRE_FAST_QUARANTINE_MANIFEST.is_file():
        manifest = read_json(PRE_FAST_QUARANTINE_MANIFEST)
        rows, aggregate = tree_inventory(PRE_FAST_QUARANTINE)
        rows_without_manifest = [row for row in rows if row["path"] != "quarantine-manifest.json"]
        if base.sha256_bytes(base.canonical_bytes(rows_without_manifest)) != manifest["payload_aggregate_sha256"]:
            raise base.CampaignError("pre-Fast quarantine payload changed")
        return manifest
    if PRE_FAST_QUARANTINE.exists():
        raise base.CampaignError("partial pre-Fast quarantine exists without its manifest")

    call_dirs = sorted(path for path in MODEL_CALLS.glob("R6-pair*") if path.is_dir())
    if not call_dirs:
        raise base.CampaignError("no pre-Fast R6 Luna attempts found to quarantine")
    receipts: list[dict[str, Any]] = []
    interrupted: list[str] = []
    for call_dir in call_dirs:
        receipt_path = call_dir / "final-receipt.json"
        if receipt_path.is_file():
            receipt = read_json(receipt_path)
            if (receipt.get("model"), receipt.get("reasoning_effort"), receipt.get("service_tier"), receipt.get("request_tier")) != (
                "gpt-5.6-luna",
                "high",
                "default",
                "default",
            ):
                raise base.CampaignError("pre-Fast quarantine contains a non-default completed receipt")
            receipts.append(receipt)
        else:
            interrupted.append(call_dir.name)

    pairs_dir = WORKSPACE / "rounds" / "R6" / "pairs"
    generated_manifests = sorted(pairs_dir.rglob("generation-manifest.json")) if pairs_dir.is_dir() else []
    actor_root = WORKSPACE / "actors"
    actor_dirs = sorted(path for path in actor_root.glob("R6-pair*") if path.is_dir())
    PRE_FAST_QUARANTINE.mkdir(parents=True)
    quarantined_calls = PRE_FAST_QUARANTINE / "model-calls"
    quarantined_calls.mkdir()
    for source in call_dirs:
        source.rename(quarantined_calls / source.name)
    if pairs_dir.is_dir():
        pairs_dir.rename(PRE_FAST_QUARANTINE / "pairs")
    if actor_dirs:
        quarantined_actors = PRE_FAST_QUARANTINE / "actors"
        quarantined_actors.mkdir()
        for source in actor_dirs:
            source.rename(quarantined_actors / source.name)

    rows, _ = tree_inventory(PRE_FAST_QUARANTINE)
    payload_aggregate = base.sha256_bytes(base.canonical_bytes(rows))
    manifest = {
        "schema_version": 1,
        "display_round": 6,
        "status": "aborted-pre-luna-fast-policy",
        "executor_epoch": "discarded-default-tier-predecessor",
        "quarantined_at": base.utc_now(),
        "selection_eligibility": False,
        "seal_eligibility": False,
        "score_eligibility": False,
        "reason": "user-mandated Luna Fast/priority executor epoch change",
        "not_best_of_n": True,
        "attempted_call_ids": [path.name for path in call_dirs],
        "completed_default_tier_receipts": len(receipts),
        "interrupted_without_final_receipt": interrupted,
        "generated_arm_artifacts": len(generated_manifests),
        "discarded_completed_usage": base.sum_usage(receipts),
        "payload_file_count": len(rows),
        "payload_aggregate_sha256": payload_aggregate,
        "restart_contract": {
            "reuse_single_sol_proposal": True,
            "sol_retry_permitted": False,
            "same_anchor_hypothesis_prompts_and_structures": True,
            "restart_all_six_arms": True,
            "official_luna_calls": 9,
            "model": "gpt-5.6-luna",
            "reasoning_effort": "high",
            "service_tier": "fast",
            "request_tier": "priority",
        },
    }
    base.write_json_new(PRE_FAST_QUARANTINE_MANIFEST, manifest)
    return manifest


def benchmark_identity() -> dict[str, Any]:
    return {
        "field": CONTINUATION["benchmark"]["field"],
        "seed": CONTINUATION["benchmark"]["seed"],
        "scale": CONTINUATION["benchmark"]["scale"],
        "trace_count": CONTINUATION["benchmark"]["trace_count"],
        "fixture_sha256": CONTINUATION["benchmark"]["fixture_sha256"],
    }


def structure_calls(structure: dict[str, Any]) -> list[dict[str, Any]]:
    return [call for stage in structure["stages"] for call in stage["calls"]]


def topology_fingerprint(structure: dict[str, Any]) -> str:
    calls = structure_calls(structure)
    call_positions = {call["id"]: index for index, call in enumerate(calls)}
    rows: list[dict[str, Any]] = []
    cursor = 0
    for stage in structure["stages"]:
        stage_rows = []
        for call in stage["calls"]:
            dependencies = []
            for name in call["inputs"]:
                if name in EXTERNAL_INPUTS:
                    dependencies.append(f"external:{name}")
                elif name in call_positions:
                    dependencies.append(f"prior_offset:{cursor - call_positions[name]}")
                else:
                    dependencies.append("unknown")
            stage_rows.append({"output_type": call["output_type"], "inputs": dependencies})
            cursor += 1
        rows.append({"mode": stage["mode"], "calls": stage_rows})
    payload = {"stages": rows, "final_position": call_positions.get(structure.get("final_call_id"))}
    return base.sha256_bytes(base.canonical_bytes(payload))


def semantic_topology_fingerprint(response: dict[str, Any]) -> str:
    """Fingerprint graph semantics that the coarse call-shape hash cannot express."""
    structure = response["candidate_structure"]
    mutation = response["structural_mutation"]
    payload = {
        "coarse_topology_fingerprint": topology_fingerprint(structure),
        "factor": mutation["factor"].strip().casefold(),
        "before": mutation["before"].strip().casefold(),
        "after": mutation["after"].strip().casefold(),
        "why_structural": mutation["why_structural"].strip().casefold(),
        "organization": str(structure.get("organization", "")).strip().casefold(),
        "information_flow": str(structure.get("information_flow", "")).strip().casefold(),
        "calls": [
            {
                "role": str(call.get("role", "")).strip().casefold(),
                "objective": str(call.get("objective", "")).strip().casefold(),
                "output_type": call.get("output_type"),
            }
            for call in structure_calls(structure)
        ],
    }
    return base.sha256_bytes(base.canonical_bytes(payload))


def prior_semantic_topology_fingerprints(round_number: int) -> set[str]:
    values: set[str] = set()
    for prior in range(1, round_number):
        proposal_path = WORKSPACE / "rounds" / f"R{prior}" / "architect" / "proposal.json"
        if not proposal_path.is_file():
            continue
        proposal = read_json(proposal_path)
        response = proposal.get("architect_response")
        if isinstance(response, dict) and isinstance(response.get("candidate_structure"), dict) and isinstance(response.get("structural_mutation"), dict):
            values.add(semantic_topology_fingerprint(response))
    return values


def official_score_strings(max_round: int) -> set[str]:
    values: set[str] = set()

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif key in {"score", "median_score", "incumbent_median", "candidate_median"} and isinstance(value, (int, float)):
            values.add(str(value).casefold())

    r1_report = WORKSPACE / "rounds" / "R1" / "R1-ROUND-REPORT.json"
    if r1_report.is_file():
        walk(read_json(r1_report))
    for number in range(2, max_round + 1):
        path = WORKSPACE / "rounds" / f"R{number}" / f"R{number}-ROUND-REPORT.json"
        if path.is_file():
            walk(read_json(path))
    return values


def validate_model_receipt(path: Path, *, architect: bool) -> dict[str, Any]:
    receipt = read_json(path)
    if architect:
        expected = (
            "gpt-5.6-sol",
            "max",
            "fast",
            "priority",
            [],
        )
    else:
        expected = (
            "gpt-5.6-luna",
            "high",
            "fast",
            "priority",
            [],
        )
    actual = (
        receipt.get("model"),
        receipt.get("reasoning_effort"),
        receipt.get("service_tier"),
        receipt.get("request_tier"),
        receipt.get("tools_used"),
    )
    if actual != expected:
        kind = "architect" if architect else "inner"
        raise base.CampaignError(f"{kind} receipt violates strict model boundary: {receipt.get('call_id')}")
    return receipt


def search_before(round_number: int) -> dict[str, Any]:
    if round_number == 2:
        return {
            "proposal_mode": "local_refinement",
            "local_refinement_count": 1,
            "local_refinement_attempt": 2,
            "emergent_failure_count": 0,
            "derived_from": "immutable R1 nonpromotion plus user-established schedule",
        }
    previous_state = read_json(WORKSPACE / "rounds" / f"R{round_number - 1}" / "state.json")
    if previous_state.get("display_round") != round_number - 1:
        raise base.CampaignError("previous state display round mismatch")
    after = previous_state["search_control_after"]
    mode = after["next_proposal_mode"]
    return {
        "proposal_mode": mode,
        "local_refinement_count": int(after["local_refinement_count"]),
        "local_refinement_attempt": (
            int(after["local_refinement_count"]) + 1 if mode == "local_refinement" else None
        ),
        "emergent_failure_count": int(after["emergent_failure_count"]),
        "derived_from": rel(WORKSPACE / "rounds" / f"R{round_number - 1}" / "state.json"),
    }


def search_after(before: dict[str, Any], promoted: bool) -> dict[str, Any]:
    if promoted:
        return {
            "completed_mode": before["proposal_mode"],
            "promoted": True,
            "local_refinement_count": 0,
            "emergent_failure_count": 0,
            "next_proposal_mode": "local_refinement",
            "next_local_refinement_attempt": 1,
            "transition": "promotion-reset",
        }
    mode = before["proposal_mode"]
    local_count = int(before["local_refinement_count"])
    emergent_count = int(before["emergent_failure_count"])
    if mode == "local_refinement":
        local_count += 1
        next_mode = "emergent_exploration" if local_count >= 2 else "local_refinement"
        transition = "local-limit-to-emergent" if next_mode == "emergent_exploration" else "next-local-refinement"
    elif mode == "emergent_exploration":
        emergent_count += 1
        next_mode = "counter_hypothesis" if emergent_count >= 2 else "emergent_exploration"
        transition = "emergent-failure-limit-to-counter" if next_mode == "counter_hypothesis" else "next-emergent-exploration"
    elif mode == "counter_hypothesis":
        next_mode = "counter_hypothesis"
        transition = "counter-persists-until-promotion"
    else:
        raise base.CampaignError(f"unsupported proposal mode: {mode}")
    return {
        "completed_mode": mode,
        "promoted": False,
        "local_refinement_count": local_count,
        "emergent_failure_count": emergent_count,
        "next_proposal_mode": next_mode,
        "next_local_refinement_attempt": local_count + 1 if next_mode == "local_refinement" else None,
        "transition": transition,
    }


def qualitative_relation(batch: dict[str, Any]) -> str:
    inc = batch["aggregate"].get("incumbent_median")
    cand = batch["aggregate"].get("candidate_median")
    if inc is None or cand is None:
        return "aggregate_order_unavailable"
    if cand > inc:
        return "candidate_median_higher"
    if cand < inc:
        return "incumbent_median_higher"
    return "medians_equal"


def qualitative_verdict(value: str) -> str:
    return {
        "candidate_win": "candidate_better",
        "incumbent_win": "incumbent_better",
        "tie": "equal",
        "invalid_pair": "invalid",
    }[value]


def build_error_notebook(round_number: int) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    frontier: list[dict[str, Any]] = []
    for prior in range(1, round_number):
        if prior == 1:
            report_path = WORKSPACE / "rounds" / "R1" / "R1-ROUND-REPORT.json"
            proposal_path = WORKSPACE / "rounds" / "R1" / "architect" / "proposal.json"
        else:
            report_path = WORKSPACE / "rounds" / f"R{prior}" / f"R{prior}-ROUND-REPORT.json"
            proposal_path = WORKSPACE / "rounds" / f"R{prior}" / "architect" / "proposal.json"
        if not report_path.is_file() or not proposal_path.is_file():
            continue
        report = read_json(report_path)
        batch = (
            {"pairs": report["pairs"], "aggregate": report["aggregate"]}
            if prior == 1
            else {"pairs": report["pairs"], "aggregate": report["aggregate"]}
        )
        proposal = read_json(proposal_path)
        response = proposal.get("architect_response", proposal)
        mutation = response.get("structural_mutation", response.get("mutation", {}))
        promoted = bool(
            report.get("promotion", {}).get("contract_passed", False)
            if prior == 1
            else report.get("promotion", {}).get("contract_passed", False)
        )
        outcomes.append(
            {
                "display_round": prior,
                "proposal_mode": (
                    "local_refinement" if prior == 1 else report["search_control_before"]["proposal_mode"]
                ),
                "structural_factor": mutation.get("factor", "unknown"),
                "promotion_outcome": "promoted" if promoted else "not_promoted",
                "validity": (
                    "all_arms_valid_and_deterministic"
                    if report["aggregate"].get("all_six_valid_and_deterministic")
                    else "one_or_more_arms_invalid_or_nondeterministic"
                ),
                "paired_pattern": [qualitative_verdict(row["verdict"]) for row in batch["pairs"]],
                "aggregate_relation": qualitative_relation(batch),
                "bounded_lesson": (
                    "Some sealed outputs violated authoritative operation validity. The analysis-only handoff plausibly deprived final materialization of a directly executable policy lineage; preserve executable lineage visibility without exposing cases, traces, or scores."
                    if not report["aggregate"].get("all_six_valid_and_deterministic")
                    else "The tested factor did not satisfy the full matched promotion contract; do not merely rename, split, or repeat it."
                    if not promoted
                    else "The tested factor satisfied the promotion contract and is now part of the champion structure; mutate a different factor."
                ),
            }
        )
        structure_path = (
            WORKSPACE / "rounds" / "R1" / "architect" / "proposed-structure.json"
            if prior == 1
            else WORKSPACE / "rounds" / f"R{prior}" / "architect" / "proposed-structure.json"
        )
        if structure_path.is_file():
            response = proposal.get("architect_response")
            semantic_fingerprint = (
                semantic_topology_fingerprint(response)
                if isinstance(response, dict)
                and isinstance(response.get("candidate_structure"), dict)
                and isinstance(response.get("structural_mutation"), dict)
                and all(key in response["structural_mutation"] for key in ("factor", "before", "after", "why_structural"))
                else None
            )
            frontier.append(
                {
                    "display_round": prior,
                    "factor": mutation.get("factor", "unknown"),
                    "topology_fingerprint": topology_fingerprint(read_json(structure_path)),
                    "semantic_topology_fingerprint": semantic_fingerprint,
                    "status": "supported" if promoted else "not_supported_in_tested_conditions",
                }
            )
    return {
        "schema_version": 1,
        "for_display_round": round_number,
        "evidence_scope": "bounded qualitative outcomes only",
        "official_numeric_scores_included": False,
        "trace_contents_included": False,
        "recent_outcomes": outcomes[-3:],
        "factor_frontier": frontier[-6:],
        "explicitly_forbidden_repetition": [
            "serial terminal-call role fission",
            "mere producer-reviewer-finalizer split or role rename",
            "best-of-N, voting, replicated candidates, or parameter sweep",
        ],
    }


def validate_structure(structure: Any) -> list[dict[str, Any]]:
    if not isinstance(structure, dict) or not isinstance(structure.get("stages"), list) or not structure["stages"]:
        raise base.CampaignError("candidate structure is missing stages")
    calls: list[dict[str, Any]] = []
    stage_ids: set[str] = set()
    for stage in structure["stages"]:
        if not isinstance(stage, dict) or stage.get("mode") != "sequential":
            raise base.CampaignError("candidate stages must be sequential")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", stage_id) or stage_id in stage_ids:
            raise base.CampaignError("candidate stage id is invalid or duplicated")
        stage_ids.add(stage_id)
        if not isinstance(stage.get("calls"), list) or not stage["calls"]:
            raise base.CampaignError("candidate stage has no calls")
        calls.extend(stage["calls"])
    if not 2 <= len(calls) <= 4:
        raise base.CampaignError("candidate topology must have two to four calls")
    ids: list[str] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise base.CampaignError("candidate call is not an object")
        call_id = call.get("id")
        if not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", call_id) or call_id in ids:
            raise base.CampaignError("candidate call id is invalid or duplicated")
        ids.append(call_id)
        if not isinstance(call.get("role"), str) or not call["role"].strip():
            raise base.CampaignError("candidate role is missing")
        if not isinstance(call.get("objective"), str) or not call["objective"].strip():
            raise base.CampaignError("candidate objective is missing")
        if call.get("output_type") not in {"analysis", "policy", "policy_capsule", "executable_policy_state", "executable_policy_closure"}:
            raise base.CampaignError("candidate output type is invalid")
        inputs = call.get("inputs")
        if not isinstance(inputs, list) or any(not isinstance(item, str) for item in inputs) or len(inputs) != len(set(inputs)):
            raise base.CampaignError("candidate inputs are invalid")
        if index == 0:
            if inputs != list(EXTERNAL_INPUTS):
                raise base.CampaignError("candidate first call must receive the six common inputs in order")
        else:
            predecessor = ids[index - 1]
            if predecessor not in inputs:
                raise base.CampaignError("candidate call does not consume its immediate predecessor")
            if set(ids[:-2]).intersection(inputs):
                raise base.CampaignError("candidate call bypasses the single lineage")
            if any(name not in EXTERNAL_INPUTS and name != predecessor for name in inputs):
                raise base.CampaignError("candidate call has an unresolvable dependency")
    if structure.get("final_call_id") != ids[-1] or calls[-1]["output_type"] != "policy":
        raise base.CampaignError("candidate final call must be the last policy producer")
    return calls


class RoundRunner:
    def __init__(self, round_number: int):
        if round_number not in AUTHORIZED_ROUNDS:
            raise base.CampaignError("only explicitly contracted Cache display rounds are authorized")
        self.n = round_number
        self.tag = f"R{round_number}"
        self.continuation_path = (
            LEGACY_CONTINUATION_CONTRACT_PATH
            if round_number <= 5
            else R6_CONTINUATION_CONTRACT_PATH
            if round_number <= 8
            else R100_AMENDMENT_PATH
        )
        self.continuation = CONTINUATION if round_number <= 5 else R6_CONTINUATION
        self.stop_round = 5 if round_number <= 5 else 11 if round_number <= 8 else 96 if round_number == 96 else 100
        self.guard_round = self.stop_round + 1
        self.guard_key = f"cache_r{self.guard_round}_opened"
        self.continuation_start = 2 if round_number <= 5 else 6
        self.round = WORKSPACE / "rounds" / self.tag
        self.architect_dir = self.round / "architect"
        self.pairs = self.round / "pairs"
        self.evaluation = self.round / "evaluation"
        self.source_manifest = self.round / "source-manifest.json"
        self.round_contract = self.round / "round-contract.json"
        self.notebook = self.round / "qualitative-error-notebook.json"
        self.proposal = self.architect_dir / "proposal.json"
        self.proposed_structure = self.architect_dir / "proposed-structure.json"
        self.hypothesis = self.architect_dir / "hypothesis.json"
        self.global_seal = self.round / "pre-evaluation-seal.json"
        self.batch = self.evaluation / "evaluation-batch.json"
        self.token_accounting = self.round / "token-accounting.json"
        self.decision = self.round / "round-decision.json"
        self.state = self.round / "state.json"
        self.test_receipt = self.round / "test-receipt.json"
        self.verification = self.round / "verification-receipt.json"
        self.report_json = self.round / f"{self.tag}-ROUND-REPORT.json"
        self.report_md = CAMPAIGN_DIR / f"{self.tag}-ROUND-REPORT.md"
        self.atomic = self.round / f"{self.tag}-ATOMIC-COMMIT.json"
        self.executor_epoch_binding = self.round / "executor-epoch-binding.json"
        self.stop_after_current_binding = self.round / "stop-after-current-binding.json"
        self.previous_champion = WORKSPACE / f"champion-r{round_number - 1}"
        self.champion = WORKSPACE / f"champion-r{round_number}"
        self.previous_round = WORKSPACE / "rounds" / f"R{round_number - 1}"

    def previous_atomic(self) -> Path:
        if self.n == 2:
            return self.previous_round / "R1-ATOMIC-COMMIT.json"
        return self.previous_round / f"R{self.n - 1}-ATOMIC-COMMIT.json"

    def prepare(self) -> None:
        if self.n == 96:
            load_stop_after_r96_amendment()
        if (WORKSPACE / "rounds" / f"R{self.guard_round}").exists() or (WORKSPACE / f"champion-r{self.guard_round}").exists():
            raise base.CampaignError(f"Cache R{self.guard_round} is open despite the stop contract")
        if self.n == 2:
            require_hash(self.previous_atomic(), R1_ATOMIC_SHA, "R1 atomic state")
            require_hash(self.previous_champion / "policy.py", R1_POLICY_SHA, "R1 champion policy")
            require_hash(self.previous_champion / "structure.json", R1_STRUCTURE_SHA, "R1 champion structure")
        else:
            if not self.previous_atomic().is_file():
                raise base.CampaignError(f"{self.tag} cannot open before prior atomic commit")
            previous_marker = read_json(self.previous_atomic())
            if previous_marker.get("display_round") != self.n - 1:
                raise base.CampaignError("prior atomic marker display mismatch")
            previous_state = read_json(self.previous_round / "state.json")
            require_hash(
                self.previous_champion / "policy.py",
                previous_state["champion_artifact_sha256"],
                "prior champion policy",
            )
            require_hash(
                self.previous_champion / "structure.json",
                previous_state["champion_structure_sha256"],
                "prior champion structure",
            )
        if self.n == 6:
            start = R6_CONTINUATION["authoritative_start"]
            require_hash(self.previous_atomic(), start["atomic_state_sha256"], "contracted R5 atomic state")
            require_hash(self.previous_round / "state.json", start["state_sha256"], "contracted R5 state")
            require_hash(self.previous_champion / "policy.py", start["champion_policy_sha256"], "contracted R5 policy")
            require_hash(self.previous_champion / "structure.json", start["champion_structure_sha256"], "contracted R5 structure")
            require_hash(self.previous_champion / "selection-receipt.json", start["selection_receipt_sha256"], "contracted R5 selection")
        if self.n == 9:
            start = load_r100_amendment()["authoritative_start"]
            require_hash(self.previous_atomic(), start["atomic_state_sha256"], "contracted R8 atomic state")
            require_hash(self.previous_round / "state.json", start["state_sha256"], "contracted R8 state")
            require_hash(self.previous_champion / "policy.py", start["champion_policy_sha256"], "contracted R8 policy")
            require_hash(self.previous_champion / "structure.json", start["champion_structure_sha256"], "contracted R8 structure")
            require_hash(self.previous_champion / "selection-receipt.json", start["selection_receipt_sha256"], "contracted R8 selection")
        if not (self.previous_champion / "selection-receipt.json").is_file():
            raise base.CampaignError("prior champion selection receipt is missing")
        root_manifest = read_json(WORKSPACE / "source-manifest.json")
        require_hash(base.RUNNER_SOURCE, root_manifest["frozen_runner"]["sha256"], "frozen runner")
        require_hash(TASK, root_manifest["task"]["sha256"], "task snapshot")
        before = search_before(self.n)
        if self.n == 2 and (before["proposal_mode"], before["local_refinement_attempt"]) != ("local_refinement", 2):
            raise base.CampaignError("R2 schedule is not local refinement attempt 2")
        if self.notebook.is_file():
            notebook = read_json(self.notebook)
            if notebook.get("for_display_round") != self.n:
                raise base.CampaignError("cached qualitative notebook display round differs")
        else:
            notebook = build_error_notebook(self.n)
            base.write_json_new(self.notebook, notebook)
        current_structure = read_json(self.previous_champion / "structure.json")
        contract = {
            "schema_version": 1,
            "display_round": self.n,
            "stop_after_display_round": self.stop_round,
            "proposal_mode": before["proposal_mode"],
            "local_refinement_attempt": before["local_refinement_attempt"],
            "search_control_before": before,
            "current_champion": {
                "policy_path": rel(self.previous_champion / "policy.py"),
                "policy_sha256": base.sha256_file(self.previous_champion / "policy.py"),
                "structure_path": rel(self.previous_champion / "structure.json"),
                "structure_sha256": base.sha256_file(self.previous_champion / "structure.json"),
                "topology_fingerprint": topology_fingerprint(current_structure),
                "selection_receipt_path": rel(self.previous_champion / "selection-receipt.json"),
                "selection_receipt_sha256": base.sha256_file(self.previous_champion / "selection-receipt.json"),
            },
            "models": effective_model_boundary(self.continuation, self.n) if self.n >= 6 else self.continuation["model_boundary"],
            "duel": self.continuation["duel"],
            "benchmark": self.continuation["benchmark"],
            "promotion": self.continuation["promotion"],
            "close_confirmation": self.continuation["close_confirmation"],
            "architect_evidence": self.continuation["architect_evidence"],
            self.guard_key: False,
        }
        if self.n == 6 and self.round_contract.is_file():
            pre_epoch_contract = read_json(self.round_contract)
            if pre_epoch_contract.get("models", {}).get("all_inner_roles", {}).get("service_tier") != "default":
                raise base.CampaignError("R6 pre-epoch round contract provenance differs")
        elif self.n == 96 and self.round_contract.is_file():
            pre_stop_contract = read_json(self.round_contract)
            if (
                pre_stop_contract.get("display_round") != 96
                or pre_stop_contract.get("stop_after_display_round") != 100
                or pre_stop_contract.get("cache_r101_opened") is not False
            ):
                raise base.CampaignError("R96 pre-stop round contract provenance differs")
        else:
            base.write_json_new(self.round_contract, contract)
        manifest = {
            "schema_version": 1,
            "display_round": self.n,
            "continuation_contract": {"path": rel(self.continuation_path), "sha256": base.sha256_file(self.continuation_path)},
            "prior_atomic": {"path": rel(self.previous_atomic()), "sha256": base.sha256_file(self.previous_atomic())},
            "prior_champion": contract["current_champion"],
            "round_contract": {"path": rel(self.round_contract), "sha256": base.sha256_file(self.round_contract)},
            "qualitative_notebook": {"path": rel(self.notebook), "sha256": base.sha256_file(self.notebook)},
            "task": {"path": rel(TASK), "sha256": base.sha256_file(TASK)},
            "frozen_runner": {"authority_path": str(base.RUNNER_SOURCE), "sha256": base.sha256_file(base.RUNNER_SOURCE)},
            "benchmark": benchmark_identity(),
            "generation_visibility": {
                "official_numeric_scores": False,
                "trace_contents": False,
                "fixture_identity_in_prompts": False,
                "qualitative_notebook_only": True,
            },
            self.guard_key: False,
        }
        if self.n >= 7:
            epoch = load_fast_executor_epoch()
            manifest["executor_epoch_contract"] = {
                "path": rel(FAST_EXECUTOR_EPOCH_CONTRACT_PATH),
                "sha256": base.sha256_file(FAST_EXECUTOR_EPOCH_CONTRACT_PATH),
                "executor_epoch_id": epoch["executor_epoch_id"],
            }
        if self.n >= 9:
            extension = load_r100_amendment()
            manifest["r100_extension_amendment"] = {
                "path": rel(R100_AMENDMENT_PATH),
                "sha256": base.sha256_file(R100_AMENDMENT_PATH),
                "amendment_id": extension["amendment_id"],
            }
        if self.n == 6 and self.source_manifest.is_file():
            existing = read_json(self.source_manifest)
            if existing.get("display_round") != 6:
                raise base.CampaignError("R6 pre-epoch source manifest provenance differs")
        elif self.n == 96 and self.source_manifest.is_file():
            existing = read_json(self.source_manifest)
            if existing.get("display_round") != 96 or existing.get("cache_r101_opened") is not False:
                raise base.CampaignError("R96 pre-stop source manifest provenance differs")
        else:
            base.write_json_new(self.source_manifest, manifest)
        if self.n == 96:
            self.bind_stop_after_current()
        print(json.dumps({"phase": "prepare", "round": self.n, "mode": before["proposal_mode"], "local_attempt": before["local_refinement_attempt"]}))

    def bind_stop_after_current(self) -> dict[str, Any]:
        if self.n != 96:
            return {}
        amendment = load_stop_after_r96_amendment()
        binding = {
            "schema_version": 1,
            "display_round": 96,
            "status": "stop-after-active-round-bound",
            "amendment": {
                "path": rel(STOP_AFTER_R96_AMENDMENT_PATH),
                "sha256": base.sha256_file(STOP_AFTER_R96_AMENDMENT_PATH),
                "amendment_id": amendment["amendment_id"],
            },
            "authoritative_start": amendment["authoritative_start"],
            "pre_stop_round_contract": {
                "path": rel(self.round_contract),
                "sha256": base.sha256_file(self.round_contract),
                "superseded_stop_after_display_round": 100,
            },
            "pre_stop_source_manifest": {
                "path": rel(self.source_manifest),
                "sha256": base.sha256_file(self.source_manifest),
            },
            "effective_stop_after_display_round": 96,
            "next_round_permitted": False,
            "cache_r97_opened": False,
            "round_r97_absent_at_binding": not (WORKSPACE / "rounds" / "R97").exists(),
            "champion_r97_absent_at_binding": not (WORKSPACE / "champion-r97").exists(),
            "git_commit_created": False,
        }
        if not binding["round_r97_absent_at_binding"] or not binding["champion_r97_absent_at_binding"]:
            raise base.CampaignError("R97 opened before stop amendment binding")
        base.write_json_new(self.stop_after_current_binding, binding)
        return binding

    def bind_fast_executor_epoch(self) -> dict[str, Any]:
        if self.n < 6:
            return {}
        epoch = load_fast_executor_epoch()
        extension = load_r100_amendment() if self.n >= 9 else None
        if self.n == 6:
            quarantine_ref = epoch["r6_restart_binding"]["quarantine_manifest"]
            require_hash(PRE_FAST_QUARANTINE_MANIFEST, quarantine_ref["sha256"], "R6 pre-Fast quarantine manifest")
            proposal_ref = epoch["r6_restart_binding"]["single_sol_proposal"]
            require_hash(self.proposal, proposal_ref["sha256"], "R6 single Sol proposal")
            architect_ref = epoch["r6_restart_binding"]["single_sol_receipt"]
            require_hash(MODEL_CALLS / "R6-structure-architect" / "final-receipt.json", architect_ref["sha256"], "R6 single Sol receipt")
            require_hash(self.hypothesis, epoch["r6_restart_binding"]["hypothesis"]["sha256"], "R6 fixed hypothesis")
            require_hash(self.proposed_structure, epoch["r6_restart_binding"]["proposed_structure"]["sha256"], "R6 fixed proposed structure")
            require_hash(self.source_manifest, epoch["r6_restart_binding"]["pre_epoch_source_manifest"]["sha256"], "R6 pre-epoch source manifest")
            require_hash(self.round_contract, epoch["r6_restart_binding"]["pre_epoch_round_contract"]["sha256"], "R6 pre-epoch round contract")
        binding = {
            "schema_version": 1,
            "display_round": self.n,
            "executor_epoch_id": epoch["executor_epoch_id"],
            "executor_epoch_contract": {
                "path": rel(FAST_EXECUTOR_EPOCH_CONTRACT_PATH),
                "sha256": base.sha256_file(FAST_EXECUTOR_EPOCH_CONTRACT_PATH),
            },
            "source_manifest": {"path": rel(self.source_manifest), "sha256": base.sha256_file(self.source_manifest)},
            "round_contract": {"path": rel(self.round_contract), "sha256": base.sha256_file(self.round_contract)},
            "single_sol_proposal": {"path": rel(self.proposal), "sha256": base.sha256_file(self.proposal)},
            "single_sol_receipt": {
                "path": rel(MODEL_CALLS / f"{self.tag}-structure-architect" / "final-receipt.json"),
                "sha256": base.sha256_file(MODEL_CALLS / f"{self.tag}-structure-architect" / "final-receipt.json"),
            },
            "effective_inner_model_boundary": epoch["effective_inner_model_boundary"],
            "r100_extension_amendment": (
                {"path": rel(R100_AMENDMENT_PATH), "sha256": base.sha256_file(R100_AMENDMENT_PATH)}
                if extension
                else None
            ),
            "pre_fast_quarantine": (
                {"path": rel(PRE_FAST_QUARANTINE_MANIFEST), "sha256": base.sha256_file(PRE_FAST_QUARANTINE_MANIFEST)}
                if self.n == 6
                else None
            ),
        }
        base.write_json_new(self.executor_epoch_binding, binding)
        return binding

    def architect_prompt(self) -> str:
        task_text = TASK.read_text(encoding="utf-8")
        incumbent = read_json(self.previous_champion / "structure.json")
        notebook = read_json(self.notebook)
        before = search_before(self.n)
        mode = before["proposal_mode"]
        if mode == "local_refinement":
            mode_instructions = """
Make one narrow but graph-real structural refinement of the current topology.
The factor must change evidence timing, visibility, causal action, or control
flow. It must not be a producer/reviewer role split, terminal role fission,
renaming, extra checklist, generic reviewer, gate, or repeat of any fingerprint
in the notebook. mode_certificate must contain nonempty `scope_boundary` and
`why_not_repeat_role_fission` strings.
""".strip()
            certificate_example = '{"scope_boundary":"...","why_not_repeat_role_fission":"..."}'
        elif mode == "emergent_exploration":
            mode_instructions = """
Propose one genuinely new task-general capability family absent from the
champion and tested frontier. It must introduce one concrete evidence-triggered
state transition or causal control behavior, not a local refinement, extra
reviewer, certificate, gate, field, role split, or rename. mode_certificate
must contain nonempty `capability_family`, `champion_limitation`, `trigger`,
`state_transition`, `observable_effect`, and `not_local_refinement` strings.
""".strip()
            certificate_example = '{"capability_family":"...","champion_limitation":"...","trigger":"...","state_transition":"...","observable_effect":"...","not_local_refinement":"..."}'
        elif mode == "counter_hypothesis":
            mode_instructions = """
Propose an independent counter-hypothesis that rejects the active structure
family rather than extending it. It must name rejected assumptions, forbid one
inherited mechanism, replace it with one independent principle, and change at
least two behavioral dimensions as consequences of the single structural
factor. This mode persists until promotion. mode_certificate must contain
`rejected_assumptions` (nonempty list), `forbidden_inherited_mechanism`,
`independent_replacement_principle`, `changed_behavioral_dimensions` (at least
two distinct strings), and `counter_until_promotion`: true.
""".strip()
            certificate_example = '{"rejected_assumptions":["..."],"forbidden_inherited_mechanism":"...","independent_replacement_principle":"...","changed_behavioral_dimensions":["...","..."],"counter_until_promotion":true}'
        else:
            raise base.CampaignError("unsupported architect mode")
        return f"""
You are the sole STRUCTURE ARCHITECT for Cache display {self.tag}, operating in
`{mode}` mode. Design exactly one structural mutation from the current champion
topology. Output only one qualitative score-blind hypothesis, one structural
factor, topology roles/visibility, a causal falsifier, and the required mode
certificate. Never output policy code, pseudocode, cache-algorithm instructions,
implementation parameters, official scores, trace contents, benchmark-specific
constants, variants, hardcoding, sampling, voting, or best-of-N. Do not use
tools or inspect files; everything allowed is inline.

{mode_instructions}

Return exactly one candidate. It must have two to four calls in one sequential,
nonbranching lineage. The first call receives the six common inputs below in
their exact order. Each later call consumes the immediately preceding call and
may also receive common external inputs. The final call is last and emits one
policy. Every nonfinal output is consumed by the next call. The structural
factor must differ from the incumbent and every tested factor in the notebook.
Prefer a new topology graph shape. A previously tested coarse call shape is
permissible only when the single mutation changes concrete edge authority,
control, visibility, evidence timing, or state-transition semantics; mere role
renaming/fission remains forbidden. Objectives describe role evidence/action
only and must not prescribe a cache algorithm.
Every output_type must be exactly one of `analysis`, `policy`,
`policy_capsule`, `executable_policy_state`, or `executable_policy_closure`.
The latter three policy-bearing kinds must carry one complete executable policy
artifact on the single lineage; only `analysis` is non-policy.

Common external inputs:
{json.dumps(list(EXTERNAL_INPUTS))}

Return one strict JSON object and no prose:
{{
  "architect_scope": "one-{self.tag}-structural-factor-only",
  "proposal_mode": "{mode}",
  "qualitative_hypothesis": {{
    "observed_bottleneck": "...",
    "causal_change": "...",
    "expected_effect": "...",
    "falsifier": "all-valid matched majority and strict-median contract, with no score"
  }},
  "structural_mutation": {{
    "change_count": 1,
    "factor": "one factor only",
    "before": "...",
    "after": "...",
    "why_structural": "..."
  }},
  "mode_certificate": {certificate_example},
  "candidate_structure": {{
    "name": "...",
    "organization": "...",
    "information_flow": "...",
    "stages": [{{"id":"...","mode":"sequential","calls":[
      {{"id":"...","role":"...","objective":"...","inputs":{json.dumps(list(EXTERNAL_INPUTS))},"output_type":"analysis"}},
      {{"id":"...","role":"...","objective":"...","inputs":["previous_call_id"],"output_type":"policy"}}
    ]}}],
    "final_call_id": "..."
  }},
  "compliance": {{
    "one_structural_factor_only": true,
    "score_or_trace_content_used": false,
    "policy_code_emitted": false,
    "variants_sampling_or_best_of_n_emitted": false,
    "hardcoding_emitted": false
  }}
}}

Generic Cache Policy objective and interface:
---
{task_text}
---

Bounded qualitative error notebook; it deliberately contains no numeric score:
{json.dumps(notebook, indent=2, ensure_ascii=False)}

Current champion topology; no outcome data:
{json.dumps(incumbent, indent=2, ensure_ascii=False)}
""".strip()

    def validate_architect_response(self, parsed: Any, prompt: str, receipt: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(parsed, dict) or parsed.get("architect_scope") != f"one-{self.tag}-structural-factor-only":
            raise base.CampaignError("architect scope certificate is invalid")
        before = search_before(self.n)
        mode = before["proposal_mode"]
        if parsed.get("proposal_mode") != mode:
            raise base.CampaignError("architect response mode differs from committed state")
        hypothesis = parsed.get("qualitative_hypothesis")
        if not isinstance(hypothesis, dict) or any(not isinstance(hypothesis.get(key), str) or not hypothesis[key].strip() for key in ("observed_bottleneck", "causal_change", "expected_effect", "falsifier")):
            raise base.CampaignError("architect hypothesis is incomplete")
        mutation = parsed.get("structural_mutation")
        if not isinstance(mutation, dict) or mutation.get("change_count") != 1:
            raise base.CampaignError("architect did not certify one structural factor")
        for key in ("factor", "before", "after", "why_structural"):
            if not isinstance(mutation.get(key), str) or not mutation[key].strip():
                raise base.CampaignError(f"architect mutation field missing: {key}")
        factor_lower = mutation["factor"].casefold()
        if "role fission" in factor_lower or "terminal-call" in factor_lower or "terminal call" in factor_lower:
            raise base.CampaignError("architect repeated the R1 role-fission factor")
        compliance = parsed.get("compliance")
        expected_compliance = {
            "one_structural_factor_only": True,
            "score_or_trace_content_used": False,
            "policy_code_emitted": False,
            "variants_sampling_or_best_of_n_emitted": False,
            "hardcoding_emitted": False,
        }
        if compliance != expected_compliance:
            raise base.CampaignError("architect compliance certificate is invalid")
        certificate = parsed.get("mode_certificate")
        if not isinstance(certificate, dict):
            raise base.CampaignError("architect mode certificate is missing")
        if mode == "local_refinement":
            for key in ("scope_boundary", "why_not_repeat_role_fission"):
                if not isinstance(certificate.get(key), str) or not certificate[key].strip():
                    raise base.CampaignError("local-refinement certificate is incomplete")
        elif mode == "emergent_exploration":
            for key in ("capability_family", "champion_limitation", "trigger", "state_transition", "observable_effect", "not_local_refinement"):
                if not isinstance(certificate.get(key), str) or not certificate[key].strip():
                    raise base.CampaignError("emergent capability certificate is incomplete")
        else:
            if not isinstance(certificate.get("rejected_assumptions"), list) or not certificate["rejected_assumptions"]:
                raise base.CampaignError("counter-hypothesis rejected assumptions are missing")
            if not isinstance(certificate.get("changed_behavioral_dimensions"), list) or len(set(certificate["changed_behavioral_dimensions"])) < 2:
                raise base.CampaignError("counter-hypothesis needs two behavioral dimensions")
            for key in ("forbidden_inherited_mechanism", "independent_replacement_principle"):
                if not isinstance(certificate.get(key), str) or not certificate[key].strip():
                    raise base.CampaignError("counter-hypothesis certificate is incomplete")
            if certificate.get("counter_until_promotion") is not True:
                raise base.CampaignError("counter-hypothesis persistence certificate is false")
        raw_structure = parsed.get("candidate_structure")
        if not isinstance(raw_structure, dict):
            raise base.CampaignError("architect candidate structure is missing")
        candidate_structure = json.loads(json.dumps(raw_structure))
        policy_bearing_semantics = {
            "policy_capsule": "complete policy artifact plus obligation evidence on the same single lineage",
            "executable_policy_state": "complete executable policy artifact serving as the sole constructive lineage state",
            "executable_policy_closure": "self-contained executable policy artifact crossing a provenance-blind closure edge",
        }
        policy_bearing_output_kinds = [
            {
                "call_id": str(call.get("id")),
                "output_type": str(call.get("output_type")),
                "executor_semantics": policy_bearing_semantics[str(call.get("output_type"))],
            }
            for call in structure_calls(candidate_structure)
            if call.get("output_type") in policy_bearing_semantics
        ]
        calls = validate_structure(candidate_structure)
        candidate_fp = topology_fingerprint(candidate_structure)
        semantic_fp = semantic_topology_fingerprint(parsed)
        incumbent_fp = topology_fingerprint(read_json(self.previous_champion / "structure.json"))
        frontier = read_json(self.notebook)["factor_frontier"]
        tested = {row["topology_fingerprint"] for row in frontier}
        coarse_collision_override = None
        matches_incumbent_coarse_shape = candidate_fp == incumbent_fp
        if matches_incumbent_coarse_shape or candidate_fp in tested:
            tested_factors = {str(row.get("factor", "")).strip().casefold() for row in frontier}
            mechanism_text = " ".join(
                str(value).casefold()
                for value in (
                    mutation["factor"],
                    mutation["after"],
                    mutation["why_structural"],
                    candidate_structure.get("information_flow", ""),
                )
            )
            mechanism_markers = ("edge", "authority", "lineage", "visibility", "control", "state transition", "evidence timing", "dependency", "branch")
            if factor_lower in tested_factors:
                raise base.CampaignError("architect repeated a tested structural factor")
            if not any(marker in mechanism_text for marker in mechanism_markers):
                raise base.CampaignError("coarse topology collision lacks a concrete semantic edge/control change")
            if semantic_fp in prior_semantic_topology_fingerprints(self.n):
                raise base.CampaignError("architect repeated a tested semantic topology fingerprint")
            coarse_collision_override = {
                "coarse_topology_fingerprint": candidate_fp,
                "reason": "coarse call shape reused with a novel certified edge/control semantic factor",
                "matches_incumbent_coarse_shape": matches_incumbent_coarse_shape,
                "mere_role_fission_or_rename": False,
            }
        serialized = json.dumps(parsed, sort_keys=True, ensure_ascii=False).casefold()
        prompt_lower = prompt.casefold()
        for marker in FORBIDDEN_CODE_MARKERS:
            if marker in serialized:
                raise base.CampaignError(f"architect emitted policy-code marker: {marker}")
        for marker in FORBIDDEN_BENCHMARK_MARKERS:
            if marker in serialized or marker in prompt_lower:
                raise base.CampaignError(f"architect visibility contains benchmark marker: {marker}")
        for score in official_score_strings(self.n - 1):
            if score and (score in serialized or score in prompt_lower):
                raise base.CampaignError("architect visibility contains an official numeric score")
        expected_receipt = validate_model_receipt(MODEL_CALLS / f"{self.tag}-structure-architect" / "final-receipt.json", architect=True)
        if expected_receipt != receipt:
            raise base.CampaignError("architect receipt object differs from immutable receipt")
        return {
            "candidate_call_count": len(calls),
            "topology_fingerprint": candidate_fp,
            "semantic_topology_fingerprint": semantic_fp,
            "coarse_topology_collision_override": coarse_collision_override,
            "factor": mutation["factor"],
            "output_type_normalizations": [],
            "policy_bearing_output_kinds": policy_bearing_output_kinds,
            "normalized_candidate_structure": candidate_structure,
        }

    def architect(self) -> None:
        self.prepare()
        call_id = f"{self.tag}-structure-architect"
        if self.proposal.is_file():
            proposal = read_json(self.proposal)
            receipt = read_json(MODEL_CALLS / call_id / "final-receipt.json")
            prompt = (MODEL_CALLS / call_id / "prompt.txt").read_text(encoding="utf-8")
            self.validate_architect_response(proposal["architect_response"], prompt, receipt)
            print(json.dumps({"phase": "architect", "round": self.n, "cached": True, "proposal_sha256": base.sha256_file(self.proposal)}))
            return
        prompt = self.architect_prompt()
        prompt_lower = prompt.casefold()
        for marker in FORBIDDEN_BENCHMARK_MARKERS:
            if marker in prompt_lower:
                raise base.CampaignError(f"architect prompt contains benchmark marker: {marker}")
        for score in official_score_strings(self.n - 1):
            if score and score in prompt_lower:
                raise base.CampaignError("architect prompt contains an official numeric score")
        parsed, receipt = base.run_codex(
            call_id=call_id,
            role=f"score-blind {self.tag} {search_before(self.n)['proposal_mode']} structure architect; never policy code",
            prompt=prompt,
            model="gpt-5.6-sol",
            effort="max",
            home_slot=0,
            service_tier="fast",
            timeout_seconds=1800,
        )
        audit = self.validate_architect_response(parsed, prompt, receipt)
        normalized_candidate_structure = audit.pop("normalized_candidate_structure")
        receipt_path = MODEL_CALLS / call_id / "final-receipt.json"
        proposal = {
            "schema_version": 1,
            "display_round": self.n,
            "proposal_mode": search_before(self.n)["proposal_mode"],
            "architect_response": parsed,
            "architect_receipt": {"path": rel(receipt_path), "sha256": base.sha256_file(receipt_path)},
            "source_manifest": {"path": rel(self.source_manifest), "sha256": base.sha256_file(self.source_manifest)},
            "qualitative_notebook": {"path": rel(self.notebook), "sha256": base.sha256_file(self.notebook)},
            "incumbent_structure_sha256": base.sha256_file(self.previous_champion / "structure.json"),
            "task_sha256": base.sha256_file(TASK),
            "score_blind": True,
            "official_numeric_scores_visible": False,
            "benchmark_fixtures_visible": False,
            "validation": audit,
        }
        base.write_json_new(self.proposal, proposal)
        base.write_json_new(self.proposed_structure, normalized_candidate_structure)
        base.write_json_new(self.hypothesis, parsed["qualitative_hypothesis"])
        print(json.dumps({"phase": "architect", "round": self.n, "mode": proposal["proposal_mode"], "factor": audit["factor"], "candidate_calls": audit["candidate_call_count"], "proposal_sha256": base.sha256_file(self.proposal)}))

    def visible_value(
        self,
        name: str,
        *,
        task_text: str,
        anchor_source: str,
        anchor_sha: str,
        hypothesis: dict[str, Any],
        structure: dict[str, Any],
        prior_outputs: dict[str, Any],
    ) -> Any:
        if name == "task":
            return task_text
        if name == "anchor_policy":
            return {"artifact": "policy.py", "sha256": anchor_sha, "policy_source": anchor_source}
        if name == "anchor_contract":
            return {
                "artifact_kind": f"immutable display-R{self.n - 1} champion policy anchor",
                "artifact_sha256": anchor_sha,
                "score_information": "withheld",
                "required_comparison": "preserve interface legality, capacity safety, and online-only visibility",
            }
        if name == "task_constraints":
            return {
                "standard_library_only": True,
                "online_one_access_at_a_time": True,
                "must_return_only_currently_cached_unique_integer_keys": True,
                "must_never_exceed_capacity": True,
                "no_benchmark_paths_trace_hardcoding_or_oracle_adaptation": True,
                "no_scores_available": True,
                "one_final_policy_only": True,
            }
        if name == "candidate_hypothesis":
            return hypothesis
        if name == "loop_structure":
            return structure
        if name in prior_outputs:
            return prior_outputs[name]
        raise base.CampaignError(f"unresolvable role input: {name}")

    def role_prompt(
        self,
        *,
        pair: int,
        arm: str,
        call: dict[str, Any],
        visible_inputs: dict[str, Any],
    ) -> str:
        if call["output_type"] in {"policy", "policy_capsule", "executable_policy_state", "executable_policy_closure"}:
            output_contract = """
Return one strict JSON object and no prose:
{"policy_source":"complete contents of policy.py","artifact_kind":"single_policy"}
The source must be complete, deterministic, online-only, standard-library-only,
and define class Policy with __init__(capacity_bytes) and access(key, size, now).
Return the one policy lineage only: no diff, variants, benchmark data, evaluator
constants, trace recognition, tuning sweep, voting, or ranked selection.
""".strip()
        elif call["output_type"] == "analysis":
            output_contract = """
Return one strict JSON object and no prose:
{"analysis_packet":{"certificate":"...","witnesses":[],"obligations":[],"exact_actions":[]},"artifact_kind":"analysis_only"}
Do not output Python, policy source, a patch, a diff, alternative policies, or
a ranked selection. Analyze or transform evidence only for the one lineage.
""".strip()
        else:
            raise base.CampaignError("unsupported role output type")
        return f"""
Execute exactly one gpt-5.6-luna high inner-loop role in Cache display {self.tag},
matched pair {pair}, {arm} arm. This pipeline is independent: no other arm,
pair, artifact, evaluator result, benchmark content, or official score is
visible. Use only the inline inputs. Do not use tools, inspect files, search,
sample, branch, vote, run best-of-N, retry a policy design, or ask another agent.

Both arms are bound to the same immutable current champion anchor, task, generic
constraints, and score-blind improvement hypothesis. Execute this arm's topology
exactly; do not redesign it or substitute a model or artifact.

Role id: {call['id']}
Role: {call['role']}
Objective: {call['objective']}
Output kind: {call['output_type']}

{output_contract}

Visible inputs fixed by this topology:
{json.dumps(visible_inputs, indent=2, ensure_ascii=False)}
""".strip()

    def arm_dir(self, pair: int, arm: str) -> Path:
        return self.pairs / f"pair-{pair:02d}" / arm

    def arm_label(self, pair: int, arm: str) -> str:
        return f"pair-{pair:02d}-{arm}"

    def routing_slot(self, pair: int, arm: str) -> int:
        row = CONTINUATION["duel"]["routing"][f"pair_{pair}"]
        return int(row[f"{arm}_home_slot"])

    def generate_arm(
        self,
        *,
        pair: int,
        arm: str,
        home_slot: int,
        task_text: str,
        anchor_source: str,
        anchor_sha: str,
        hypothesis: dict[str, Any],
        structure: dict[str, Any],
        structure_path: Path,
    ) -> dict[str, Any]:
        target_dir = self.arm_dir(pair, arm)
        manifest_path = target_dir / "generation-manifest.json"
        if manifest_path.is_file():
            return read_json(manifest_path)
        calls = structure_calls(structure)
        prior_outputs: dict[str, Any] = {}
        call_receipts: list[dict[str, Any]] = []
        semantic_contract_violations: list[dict[str, str]] = []
        for call_index, call in enumerate(calls, start=1):
            visible = {
                name: self.visible_value(
                    name,
                    task_text=task_text,
                    anchor_source=anchor_source,
                    anchor_sha=anchor_sha,
                    hypothesis=hypothesis,
                    structure=structure,
                    prior_outputs=prior_outputs,
                )
                for name in call["inputs"]
            }
            safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", call["id"])
            call_id = f"{self.tag}-pair{pair:02d}-{arm}-call{call_index:02d}-{safe_id}"
            parsed, receipt = base.run_codex(
                call_id=call_id,
                role=f"{self.tag} {arm} topology role {call['role']}",
                prompt=self.role_prompt(pair=pair, arm=arm, call=call, visible_inputs=visible),
                model="gpt-5.6-luna",
                effort="high",
                home_slot=home_slot,
                service_tier="fast",
                timeout_seconds=1200,
            )
            immutable_receipt = MODEL_CALLS / call_id / "final-receipt.json"
            receipt_check = validate_model_receipt(immutable_receipt, architect=False)
            if receipt_check != receipt:
                raise base.CampaignError("inner receipt differs from immutable receipt")
            if receipt.get("requested_home_slot") != home_slot or receipt.get("home_slot") != home_slot:
                raise base.CampaignError(f"{call_id} crossed-home routing failed; no direct substitution allowed")
            transport_resume = None
            if receipt.get("transport_retry"):
                resume_value = receipt.get("transport_resume_manifest")
                failure_value = receipt.get("prior_transport_failure_receipt")
                if not isinstance(resume_value, str) or not isinstance(failure_value, str):
                    raise base.CampaignError(f"{call_id} transport retry lacks immutable provenance")
                resume_path = CAMPAIGN_DIR / resume_value
                failure_path = CAMPAIGN_DIR / failure_value
                resume_manifest = read_json(resume_path)
                failure_receipt = read_json(failure_path)
                raw_path = CAMPAIGN_DIR / resume_manifest["attempt_01"]["raw_events_path"]
                if (
                    resume_manifest.get("call_id") != call_id
                    or resume_manifest.get("same_call_id") is not True
                    or resume_manifest.get("same_prompt") is not True
                    or resume_manifest.get("retry_attempt") != 2
                    or resume_manifest.get("bounded_max_attempts") != 2
                    or resume_manifest.get("direct_substitution") is not False
                    or resume_manifest.get("semantic_failure") is not False
                    or failure_receipt.get("failure_kind") != "transport"
                ):
                    raise base.CampaignError(f"{call_id} transport resume contract failed")
                require_hash(failure_path, resume_manifest["attempt_01"]["failure_receipt_sha256"], f"{call_id} failed attempt receipt")
                require_hash(raw_path, resume_manifest["attempt_01"]["raw_events_sha256"], f"{call_id} failed raw stream")
                transport_resume = {
                    "call_id": call_id,
                    "manifest_path": rel(resume_path),
                    "manifest_sha256": base.sha256_file(resume_path),
                    "failure_receipt_path": rel(failure_path),
                    "failure_receipt_sha256": base.sha256_file(failure_path),
                    "attempt_01_raw_events_path": rel(raw_path),
                    "attempt_01_raw_events_sha256": base.sha256_file(raw_path),
                    "discarded_attempt_usage": failure_receipt.get("usage", {}),
                }
            call_violations: list[str] = []
            if call["output_type"] in {"policy", "policy_capsule", "executable_policy_state", "executable_policy_closure"}:
                has_policy_source = isinstance(parsed, dict) and isinstance(parsed.get("policy_source"), str)
                if not has_policy_source:
                    call_violations.append("policy_role_missing_policy_source")
                if isinstance(parsed, dict) and parsed.get("artifact_kind") not in (None, "single_policy"):
                    call_violations.append("policy_role_conflicting_artifact_kind")
                response_warnings = []
                if isinstance(parsed, dict) and parsed.get("artifact_kind") is None:
                    response_warnings.append("artifact_kind_certificate_missing")
                if has_policy_source:
                    source = base.extract_policy_source(parsed, call_id=call_id)
                    output: Any = {
                        "artifact_kind": "policy",
                        "policy_source": source,
                        "sha256": base.sha256_bytes(source.encode("utf-8")),
                    }
                else:
                    output = parsed
            else:
                call_violations.extend(analysis_output_contract_violations(parsed))
                response_warnings = []
                output = parsed
            response_warnings.extend(call_violations)
            semantic_contract_violations.extend(
                {"call_id": call_id, "role_id": str(call["id"]), "reason": reason}
                for reason in call_violations
            )
            prior_outputs[str(call["id"])] = output
            call_receipts.append(
                {
                    "call_id": call_id,
                    "role_id": call["id"],
                    "output_type": call["output_type"],
                    "path": rel(immutable_receipt),
                    "sha256": base.sha256_file(immutable_receipt),
                    "usage": receipt["usage"],
                    "requested_home_slot": home_slot,
                    "actual_home_slot": receipt["home_slot"],
                    "response_contract_warnings": response_warnings,
                    "transport_resume": transport_resume,
                }
            )
        final = prior_outputs.get(structure["final_call_id"])
        if not isinstance(final, dict) or final.get("artifact_kind") != "policy" or not isinstance(final.get("policy_source"), str):
            semantic_contract_violations.append(
                {
                    "call_id": f"{self.tag}-pair{pair:02d}-{arm}-final-artifact",
                    "role_id": str(structure["final_call_id"]),
                    "reason": "final_call_missing_complete_policy",
                }
            )
            final_source = ""
        else:
            final_source = final["policy_source"]
        artifact_path = target_dir / "artifact" / "policy.py"
        base.write_text_new(artifact_path, final_source)
        manifest = {
            "schema_version": 1,
            "display_round": self.n,
            "pair": pair,
            "arm": arm,
            "independent": True,
            "other_arm_visible": False,
            "other_pairs_visible": False,
            "official_numeric_scores_visible": False,
            "benchmark_fixtures_visible": False,
            "model": "gpt-5.6-luna",
            "reasoning_effort": "high",
            "service_tier": "fast",
            "request_tier": "priority",
            "executor_epoch_id": FAST_EXECUTOR_EPOCH_ID,
            "executor_epoch_contract_sha256": base.sha256_file(FAST_EXECUTOR_EPOCH_CONTRACT_PATH),
            "r100_extension_amendment_sha256": base.sha256_file(R100_AMENDMENT_PATH) if self.n >= 9 else None,
            "requested_home_slot": home_slot,
            "anchor_sha256": anchor_sha,
            "task_sha256": base.sha256_file(TASK),
            "hypothesis_sha256": base.sha256_file(self.hypothesis),
            "structure_path": rel(structure_path),
            "structure_sha256": base.sha256_file(structure_path),
            "topology_fingerprint": topology_fingerprint(structure),
            "artifact_path": rel(artifact_path),
            "artifact_sha256": base.sha256_file(artifact_path),
            "call_receipts": call_receipts,
            "semantic_contract_valid": not semantic_contract_violations,
            "semantic_contract_violations": semantic_contract_violations,
            "semantic_violation_handling": "raw_output_preserved_no_retry_no_substitution",
            "direct_substitution": False,
            "transport_retry_for_semantic_violation": False,
            "transport_resumes": [item["transport_resume"] for item in call_receipts if item.get("transport_resume")],
        }
        base.write_json_new(manifest_path, manifest)
        print(json.dumps({"generated": self.arm_label(pair, arm), "round": self.n, "calls": len(calls), "artifact_sha256": manifest["artifact_sha256"], "home_slot": home_slot}), flush=True)
        return manifest

    def generate(self) -> None:
        self.architect()
        self.bind_fast_executor_epoch()
        task_text = TASK.read_text(encoding="utf-8")
        anchor_path = self.previous_champion / "policy.py"
        anchor_source = anchor_path.read_text(encoding="utf-8")
        anchor_sha = base.sha256_file(anchor_path)
        hypothesis = read_json(self.hypothesis)
        structures = {
            "incumbent": read_json(self.previous_champion / "structure.json"),
            "candidate": read_json(self.proposed_structure),
        }
        structure_paths = {
            "incumbent": self.previous_champion / "structure.json",
            "candidate": self.proposed_structure,
        }
        jobs = [(pair, arm, self.routing_slot(pair, arm)) for pair in range(1, 4) for arm in ("incumbent", "candidate")]
        queues = {slot: [job for job in jobs if job[2] == slot] for slot in sorted({job[2] for job in jobs})}
        if set(queues) != {0, 2}:
            raise base.CampaignError("crossed routing must use home slots 0 and 2")

        def run_queue(queue: list[tuple[int, str, int]]) -> list[dict[str, Any]]:
            return [
                self.generate_arm(
                    pair=pair,
                    arm=arm,
                    home_slot=slot,
                    task_text=task_text,
                    anchor_source=anchor_source,
                    anchor_sha=anchor_sha,
                    hypothesis=hypothesis,
                    structure=structures[arm],
                    structure_path=structure_paths[arm],
                )
                for pair, arm, slot in queue
            ]

        manifests: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"cache-{self.tag}-home") as pool:
            futures = [pool.submit(run_queue, queue) for queue in queues.values()]
            for future in as_completed(futures):
                manifests.extend(future.result())
        if len(manifests) != 6:
            raise base.CampaignError("generation did not produce six arms")
        if {row["anchor_sha256"] for row in manifests} != {anchor_sha}:
            raise base.CampaignError("arms do not share the current champion anchor")
        if len({row["hypothesis_sha256"] for row in manifests}) != 1:
            raise base.CampaignError("arms do not share one hypothesis")
        print(json.dumps({"phase": "generate", "round": self.n, "arms": 6, "shared_anchor_sha256": anchor_sha}))

    def seal(self) -> None:
        self.generate()
        if self.global_seal.is_file():
            seal = read_json(self.global_seal)
            for entry in seal["entries"]:
                require_hash(CAMPAIGN_DIR / entry["artifact_path"], entry["artifact_sha256"], entry["label"])
                require_hash(CAMPAIGN_DIR / entry["seal_path"], entry["seal_sha256"], f"{entry['label']} seal")
            for resume in seal.get("transport_resumes", []):
                require_hash(CAMPAIGN_DIR / resume["manifest_path"], resume["manifest_sha256"], f"{resume['call_id']} transport resume")
                require_hash(CAMPAIGN_DIR / resume["failure_receipt_path"], resume["failure_receipt_sha256"], f"{resume['call_id']} transport failure")
                require_hash(CAMPAIGN_DIR / resume["attempt_01_raw_events_path"], resume["attempt_01_raw_events_sha256"], f"{resume['call_id']} failed raw stream")
            print(json.dumps({"phase": "seal", "round": self.n, "cached": True, "arms": 6}))
            return
        if self.evaluation.exists() and any(self.evaluation.rglob("replay-*.json")):
            raise base.CampaignError("frozen evaluation exists before the six-arm global seal")
        architect_receipt_path = MODEL_CALLS / f"{self.tag}-structure-architect" / "final-receipt.json"
        architect_receipt = validate_model_receipt(architect_receipt_path, architect=True)
        architect_prompt = (MODEL_CALLS / f"{self.tag}-structure-architect" / "prompt.txt").read_text(encoding="utf-8")
        self.validate_architect_response(read_json(self.proposal)["architect_response"], architect_prompt, architect_receipt)
        structures = {
            "incumbent": read_json(self.previous_champion / "structure.json"),
            "candidate": read_json(self.proposed_structure),
        }
        entries: list[dict[str, Any]] = []
        inner_call_count = 0
        common_anchor: set[str] = set()
        common_task: set[str] = set()
        common_hypothesis: set[str] = set()
        transport_resumes: list[dict[str, Any]] = []
        for pair in range(1, 4):
            for arm in ("incumbent", "candidate"):
                target = self.arm_dir(pair, arm)
                manifest_path = target / "generation-manifest.json"
                artifact_path = target / "artifact" / "policy.py"
                manifest = read_json(manifest_path)
                expected_calls = len(structure_calls(structures[arm]))
                if len(manifest["call_receipts"]) != expected_calls:
                    raise base.CampaignError("arm receipt count differs from topology")
                if manifest["requested_home_slot"] != self.routing_slot(pair, arm):
                    raise base.CampaignError("arm routing differs from contract")
                for item in manifest["call_receipts"]:
                    receipt_path = CAMPAIGN_DIR / item["path"]
                    receipt = validate_model_receipt(receipt_path, architect=False)
                    if receipt.get("requested_home_slot") != self.routing_slot(pair, arm) or receipt.get("home_slot") != self.routing_slot(pair, arm):
                        raise base.CampaignError("inner role was directly substituted across homes")
                    require_hash(receipt_path, item["sha256"], item["call_id"])
                    resume = item.get("transport_resume")
                    if resume:
                        require_hash(CAMPAIGN_DIR / resume["manifest_path"], resume["manifest_sha256"], f"{item['call_id']} transport resume")
                        require_hash(CAMPAIGN_DIR / resume["failure_receipt_path"], resume["failure_receipt_sha256"], f"{item['call_id']} transport failure")
                        require_hash(CAMPAIGN_DIR / resume["attempt_01_raw_events_path"], resume["attempt_01_raw_events_sha256"], f"{item['call_id']} failed raw stream")
                        transport_resumes.append(resume)
                    inner_call_count += 1
                common_anchor.add(manifest["anchor_sha256"])
                common_task.add(manifest["task_sha256"])
                common_hypothesis.add(manifest["hypothesis_sha256"])
                validation = base.generic_validate_policy(artifact_path)
                semantic_contract_valid = bool(manifest.get("semantic_contract_valid", True))
                semantic_contract_violations = list(manifest.get("semantic_contract_violations", []))
                arm_seal_path = target / "seal.json"
                arm_seal = {
                    "schema_version": 1,
                    "display_round": self.n,
                    "label": self.arm_label(pair, arm),
                    "pair": pair,
                    "arm": arm,
                    "sealed_at": base.utc_now(),
                    "artifact_path": rel(artifact_path),
                    "artifact_sha256": base.sha256_file(artifact_path),
                    "artifact_bytes": artifact_path.stat().st_size,
                    "generation_manifest_path": rel(manifest_path),
                    "generation_manifest_sha256": base.sha256_file(manifest_path),
                    "model_receipts": [{"path": item["path"], "sha256": item["sha256"]} for item in manifest["call_receipts"]],
                    "transport_resumes": list(manifest.get("transport_resumes", [])),
                    "preseal_generic_validity": validation,
                    "generation_contract": {
                        "valid": semantic_contract_valid,
                        "violations": semantic_contract_violations,
                        "handling": manifest.get("semantic_violation_handling", "none"),
                        "direct_substitution": bool(manifest.get("direct_substitution", False)),
                        "transport_retry_for_semantic_violation": bool(manifest.get("transport_retry_for_semantic_violation", False)),
                    },
                    "official_score_known_at_seal": False,
                    "frozen_evaluation_known_at_seal": False,
                }
                base.write_json_new(arm_seal_path, arm_seal)
                entries.append(
                    {
                        "label": arm_seal["label"],
                        "pair": pair,
                        "arm": arm,
                        "artifact_path": arm_seal["artifact_path"],
                        "artifact_sha256": arm_seal["artifact_sha256"],
                        "seal_path": rel(arm_seal_path),
                        "seal_sha256": base.sha256_file(arm_seal_path),
                        "generic_valid": validation["valid"],
                        "generation_contract_valid": semantic_contract_valid,
                        "generation_contract_violations": semantic_contract_violations,
                    }
                )
        expected_inner = 3 * (len(structure_calls(structures["incumbent"])) + len(structure_calls(structures["candidate"])))
        if inner_call_count != expected_inner:
            raise base.CampaignError("dynamic inner call count is incorrect")
        if len(entries) != 6 or len(common_anchor) != 1 or len(common_task) != 1 or len(common_hypothesis) != 1:
            raise base.CampaignError("six-arm common-input invariant failed")
        selection_contract = {
            "promotion": CONTINUATION["promotion"],
            "close_confirmation": CONTINUATION["close_confirmation"],
            "pair_ties": "exact equality is a tie and never a candidate win",
            "predeclared_before_score_reveal": True,
        }
        global_seal = {
            "schema_version": 1,
            "display_round": self.n,
            "proposal_mode": search_before(self.n)["proposal_mode"],
            "sealed_at": base.utc_now(),
            "sealed_before_any_frozen_evaluation": True,
            "score_blind_generation": True,
            "pair_count": 3,
            "arm_count": 6,
            "architect": {
                "calls": 1,
                "receipt_path": rel(architect_receipt_path),
                "receipt_sha256": base.sha256_file(architect_receipt_path),
                "proposal_path": rel(self.proposal),
                "proposal_sha256": base.sha256_file(self.proposal),
                "model": "gpt-5.6-sol",
                "reasoning_effort": "max",
                "service_tier": "fast",
                "request_tier": "priority",
                "policy_code_emitted": False,
            },
            "inner_roles": {"calls": inner_call_count, "model": "gpt-5.6-luna", "reasoning_effort": "high", "service_tier": "fast", "request_tier": "priority", "executor_epoch_id": FAST_EXECUTOR_EPOCH_ID, "direct_substitution": False},
            "executor_epoch_binding": {"path": rel(self.executor_epoch_binding), "sha256": base.sha256_file(self.executor_epoch_binding)},
            "discarded_pre_fast_executor_epoch": (
                {"path": rel(PRE_FAST_QUARANTINE_MANIFEST), "sha256": base.sha256_file(PRE_FAST_QUARANTINE_MANIFEST), "selection_eligibility": False}
                if self.n == 6
                else None
            ),
            "common_inputs": {"anchor_policy_sha256": next(iter(common_anchor)), "task_sha256": next(iter(common_task)), "hypothesis_sha256": next(iter(common_hypothesis))},
            "structures": {
                "incumbent": {"path": rel(self.previous_champion / "structure.json"), "sha256": base.sha256_file(self.previous_champion / "structure.json"), "call_count": len(structure_calls(structures["incumbent"])), "topology_fingerprint": topology_fingerprint(structures["incumbent"])},
                "candidate": {"path": rel(self.proposed_structure), "sha256": base.sha256_file(self.proposed_structure), "call_count": len(structure_calls(structures["candidate"])), "topology_fingerprint": topology_fingerprint(structures["candidate"])},
            },
            "entries": entries,
            "transport_resumes": sorted(transport_resumes, key=lambda row: row["call_id"]),
            "aggregate_sha256": base.sha256_bytes(base.canonical_bytes(entries)),
            "benchmark_identity": benchmark_identity(),
            "selection_contract": selection_contract,
            "selection_contract_sha256": base.sha256_bytes(base.canonical_bytes(selection_contract)),
            self.guard_key: False,
        }
        base.write_json_new(self.global_seal, global_seal)
        print(json.dumps({"phase": "seal", "round": self.n, "arms": 6, "generic_valid": sum(bool(row["generic_valid"]) for row in entries), "inner_calls": inner_call_count, "aggregate_sha256": global_seal["aggregate_sha256"]}))

    def evaluation_dir(self, pair: int, arm: str) -> Path:
        return self.evaluation / f"pair-{pair:02d}" / arm

    def run_replay(
        self,
        *,
        pair: int,
        arm: str,
        entry: dict[str, Any],
        replay: int,
        runner: Any,
        traces: list[Any],
    ) -> dict[str, Any]:
        target = self.evaluation_dir(pair, arm) / f"replay-{replay:02d}.json"
        if target.is_file():
            existing = read_json(target)
            if existing.get("artifact_sha256") != entry["artifact_sha256"]:
                raise base.CampaignError("existing replay artifact differs from seal")
            return existing
        artifact = CAMPAIGN_DIR / entry["artifact_path"]
        require_hash(artifact, entry["artifact_sha256"], entry["label"])
        started_at = base.utc_now()
        started = time.monotonic()
        result = runner.evaluate_candidate(artifact, traces=traces, timeout_s=60.0)
        normalized = base.normalized_evaluation_result(result)
        official_policy_valid = base.official_result_valid(result)
        generation_contract_valid = bool(entry.get("generation_contract_valid", True))
        record = {
            "schema_version": 1,
            "display_round": self.n,
            "pair": pair,
            "arm": arm,
            "label": entry["label"],
            "replay": replay,
            "artifact_path": entry["artifact_path"],
            "artifact_sha256": entry["artifact_sha256"],
            "benchmark": benchmark_identity() | {"runner_sha256": base.sha256_file(base.RUNNER_SOURCE)},
            "started_at": started_at,
            "finished_at": base.utc_now(),
            "duration_seconds": round(time.monotonic() - started, 6),
            "result": result,
            "normalized_result_sha256": base.sha256_bytes(base.canonical_bytes(normalized)),
            "official_policy_valid": official_policy_valid,
            "generation_contract_valid": generation_contract_valid,
            "generation_contract_violations": list(entry.get("generation_contract_violations", [])),
            "valid": official_policy_valid and generation_contract_valid,
        }
        base.write_json_new(target, record)
        print(json.dumps({"evaluated": entry["label"], "round": self.n, "replay": replay, "score": result.get("score"), "valid": record["valid"]}), flush=True)
        return record

    def arm_summary(self, pair: int, arm: str, required_replays: int = 2) -> dict[str, Any]:
        records = [read_json(self.evaluation_dir(pair, arm) / f"replay-{index:02d}.json") for index in range(1, required_replays + 1)]
        hashes = {row["normalized_result_sha256"] for row in records}
        valid = all(bool(row["valid"]) for row in records) and len(hashes) == 1
        value = records[0]["result"].get("score")
        score = float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None
        reasons: list[str] = []
        if any(not row.get("official_policy_valid", row["valid"]) for row in records):
            reasons.append("official_replay_invalid")
        if any(not row.get("generation_contract_valid", True) for row in records):
            reasons.append("generation_contract_invalid")
        if len(hashes) != 1:
            reasons.append("replay_nondeterministic")
        if score is None:
            reasons.append("nonfinite_or_missing_score")
            valid = False
        return {
            "pair": pair,
            "arm": arm,
            "artifact_sha256": records[0]["artifact_sha256"],
            "score": score,
            "valid": valid,
            "replay_deterministic": len(hashes) == 1,
            "normalized_result_sha256": records[0]["normalized_result_sha256"],
            "invalid_reasons": reasons,
            "replay_paths": [rel(self.evaluation_dir(pair, arm) / f"replay-{index:02d}.json") for index in range(1, required_replays + 1)],
        }

    def duel_summaries(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        pairs: list[dict[str, Any]] = []
        for pair in range(1, 4):
            incumbent = self.arm_summary(pair, "incumbent")
            candidate = self.arm_summary(pair, "candidate")
            if not incumbent["valid"] or not candidate["valid"]:
                verdict = "invalid_pair"
            elif candidate["score"] > incumbent["score"]:
                verdict = "candidate_win"
            elif incumbent["score"] > candidate["score"]:
                verdict = "incumbent_win"
            else:
                verdict = "tie"
            gap = float(candidate["score"] - incumbent["score"]) if candidate["score"] is not None and incumbent["score"] is not None else None
            pairs.append({"pair": pair, "incumbent": incumbent, "candidate": candidate, "candidate_minus_incumbent": gap, "verdict": verdict})
        incumbent_scores = [row["incumbent"]["score"] for row in pairs]
        candidate_scores = [row["candidate"]["score"] for row in pairs]
        finite = all(value is not None for value in incumbent_scores + candidate_scores)
        incumbent_median = float(statistics.median(incumbent_scores)) if finite else None
        candidate_median = float(statistics.median(candidate_scores)) if finite else None
        candidate_wins = sum(row["verdict"] == "candidate_win" for row in pairs)
        incumbent_wins = sum(row["verdict"] == "incumbent_win" for row in pairs)
        ties = sum(row["verdict"] == "tie" for row in pairs)
        invalid_pairs = sum(row["verdict"] == "invalid_pair" for row in pairs)
        all_valid = all(row[arm]["valid"] for row in pairs for arm in ("incumbent", "candidate"))
        aggregate = {
            "all_six_valid_and_deterministic": all_valid,
            "incumbent_scores": incumbent_scores,
            "candidate_scores": candidate_scores,
            "incumbent_median": incumbent_median,
            "candidate_median": candidate_median,
            "candidate_wins": candidate_wins,
            "incumbent_wins": incumbent_wins,
            "ties": ties,
            "invalid_pairs": invalid_pairs,
            "candidate_pairwise_majority": candidate_wins >= 2 and candidate_wins > incumbent_wins,
            "candidate_strict_median_win": candidate_median is not None and incumbent_median is not None and candidate_median > incumbent_median,
        }
        return pairs, aggregate

    def evaluate(self) -> None:
        if os.environ.get("CACHE_SCORER_CHESS_GO") != "GO":
            raise base.CampaignError("fresh chess GO required: set CACHE_SCORER_CHESS_GO=GO")
        self.seal()
        if self.batch.is_file():
            print(json.dumps({"phase": "evaluate", "round": self.n, "cached": True, "batch_sha256": base.sha256_file(self.batch)}))
            return
        seal = read_json(self.global_seal)
        if len(seal.get("entries", [])) != 6:
            raise base.CampaignError("global seal is incomplete")
        for entry in seal["entries"]:
            require_hash(CAMPAIGN_DIR / entry["artifact_path"], entry["artifact_sha256"], entry["label"])
            require_hash(CAMPAIGN_DIR / entry["seal_path"], entry["seal_sha256"], f"{entry['label']} seal")
        root_manifest = read_json(WORKSPACE / "source-manifest.json")
        require_hash(base.RUNNER_SOURCE, root_manifest["frozen_runner"]["sha256"], "frozen runner")
        runner = base.load_module(f"_cache_transfer_{self.tag}_frozen", base.RUNNER_SOURCE)
        traces = runner.generate_trace_suite(CONTINUATION["benchmark"]["seed"], CONTINUATION["benchmark"]["scale"])
        rows = [
            {
                "name": trace.name,
                "capacity_bytes": trace.capacity_bytes,
                "accesses": [{"now": access.now, "key": access.key, "size": access.size} for access in trace.accesses],
            }
            for trace in traces
        ]
        if len(traces) != CONTINUATION["benchmark"]["trace_count"] or base.sha256_bytes(base.canonical_bytes(rows)) != CONTINUATION["benchmark"]["fixture_sha256"]:
            raise base.CampaignError("frozen fixture identity changed")
        entries = {(int(row["pair"]), str(row["arm"])): row for row in seal["entries"]}
        with base.HeavyEvaluationLock(base.HEAVY_LOCK):
            for pair in range(1, 4):
                for arm in ("incumbent", "candidate"):
                    for replay in (1, 2):
                        self.run_replay(pair=pair, arm=arm, entry=entries[(pair, arm)], replay=replay, runner=runner, traces=traces)
            pairs, aggregate = self.duel_summaries()
            threshold = float(CONTINUATION["close_confirmation"]["absolute_threshold"])
            median_close = aggregate["candidate_median"] is not None and aggregate["incumbent_median"] is not None and abs(aggregate["candidate_median"] - aggregate["incumbent_median"]) <= threshold
            pair_close = any(
                row["verdict"] in {"candidate_win", "incumbent_win"}
                and row["candidate_minus_incumbent"] is not None
                and abs(row["candidate_minus_incumbent"]) <= threshold
                for row in pairs
            )
            close_triggered = bool(median_close or pair_close)
            if close_triggered:
                for pair in range(1, 4):
                    for arm in ("incumbent", "candidate"):
                        self.run_replay(pair=pair, arm=arm, entry=entries[(pair, arm)], replay=3, runner=runner, traces=traces)
        confirmations: list[dict[str, Any]] = []
        if close_triggered:
            for pair in range(1, 4):
                for arm in ("incumbent", "candidate"):
                    records = [read_json(self.evaluation_dir(pair, arm) / f"replay-{index:02d}.json") for index in (1, 2, 3)]
                    confirmations.append(
                        {
                            "label": self.arm_label(pair, arm),
                            "normalized_result_sha256": records[0]["normalized_result_sha256"],
                            "confirmed": len({row["normalized_result_sha256"] for row in records}) == 1,
                        }
                    )
        confirmation_passed = all(row["confirmed"] for row in confirmations)
        promoted = bool(
            aggregate["all_six_valid_and_deterministic"]
            and aggregate["candidate_pairwise_majority"]
            and aggregate["candidate_strict_median_win"]
            and confirmation_passed
        )
        batch = {
            "schema_version": 1,
            "display_round": self.n,
            "completed_at": base.utc_now(),
            "pre_evaluation_seal_path": rel(self.global_seal),
            "pre_evaluation_seal_sha256": base.sha256_file(self.global_seal),
            "benchmark": benchmark_identity() | {"runner_sha256": base.sha256_file(base.RUNNER_SOURCE)},
            "replay_count": 2,
            "pairs": pairs,
            "aggregate": aggregate,
            "close_threshold": threshold,
            "close_confirmation_triggered": close_triggered,
            "confirmations": confirmations,
            "confirmation_passed": confirmation_passed,
            "promotion_contract_passed": promoted,
        }
        base.write_json_new(self.batch, batch)
        print(json.dumps({"phase": "evaluate", "round": self.n, "candidate_wins": aggregate["candidate_wins"], "incumbent_wins": aggregate["incumbent_wins"], "incumbent_median": aggregate["incumbent_median"], "candidate_median": aggregate["candidate_median"], "close_triggered": close_triggered, "promoted": promoted}))

    def round_receipts(self) -> tuple[list[Path], list[dict[str, Any]]]:
        if not self.global_seal.is_file():
            raise base.CampaignError("round receipts require the immutable six-arm seal")
        paths = [MODEL_CALLS / f"{self.tag}-structure-architect" / "final-receipt.json"]
        for entry in read_json(self.global_seal)["entries"]:
            arm_seal = read_json(CAMPAIGN_DIR / entry["seal_path"])
            paths.extend(CAMPAIGN_DIR / item["path"] for item in arm_seal["model_receipts"])
        paths = sorted(set(paths))
        return paths, [read_json(path) for path in paths]

    def accounting(self) -> dict[str, Any]:
        paths, receipts = self.round_receipts()
        architects = [row for row in receipts if row["call_id"] == f"{self.tag}-structure-architect"]
        inner = [row for row in receipts if row["call_id"].startswith(f"{self.tag}-pair")]
        expected_inner = int(read_json(self.global_seal)["inner_roles"]["calls"])
        if len(architects) != 1 or len(inner) != expected_inner or len(receipts) != 1 + expected_inner:
            raise base.CampaignError("round token-accounting cardinality failed")
        failures: list[dict[str, Any]] = []
        official_call_ids = {row["call_id"] for row in receipts}
        official_inner_prefix = f"{self.tag}-pair"
        for path in sorted(MODEL_CALLS.rglob("failure-receipt.json")):
            call_root = path
            while call_root.parent != MODEL_CALLS and call_root.parent != call_root:
                call_root = call_root.parent
            if call_root.name not in official_call_ids and not call_root.name.startswith(official_inner_prefix):
                continue
            row = read_json(path)
            row["path"] = rel(path)
            raw = path.parent / "raw-events.jsonl"
            row["raw_events_sha256"] = base.sha256_file(raw) if raw.is_file() else None
            failures.append(row)
        failure_usage_rows = [
            {
                "usage": row.get(
                    "usage",
                    {
                        "input_tokens": 0,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_output_tokens": 0,
                    },
                )
            }
            for row in failures
        ]
        discarded_epoch = read_json(PRE_FAST_QUARANTINE_MANIFEST) if self.n == 6 else None
        return {
            "schema_version": 1,
            "display_round": self.n,
            "rule": {
                "total_tokens": "input_tokens + output_tokens",
                "effective_tokens": "input_tokens - cached_input_tokens + output_tokens",
                "reasoning_output_tokens": "subset of output tokens",
            },
            "architect": base.sum_usage(architects),
            "topology_inner_roles": base.sum_usage(inner),
            "round_model_calls": base.sum_usage(receipts),
            "completed_model_calls": len(receipts),
            "transport_attempts": len(receipts) + len(failures),
            "failed_transport_attempts": len(failures),
            "transport_failures": failures,
            "discarded_transport_failure_usage": base.sum_usage(failure_usage_rows),
            "discarded_executor_epoch": (
                {
                    "status": discarded_epoch["status"],
                    "manifest_path": rel(PRE_FAST_QUARANTINE_MANIFEST),
                    "manifest_sha256": base.sha256_file(PRE_FAST_QUARANTINE_MANIFEST),
                    "completed_calls": discarded_epoch["completed_default_tier_receipts"],
                    "interrupted_calls": len(discarded_epoch["interrupted_without_final_receipt"]),
                    "usage": discarded_epoch["discarded_completed_usage"],
                    "included_in_official_round_totals": False,
                }
                if discarded_epoch
                else None
            ),
            "spend": {"billing_mode": "ChatGPT subscription via Codex login", "paid_api_spend_usd": 0.0, "estimated_api_spend_usd": None, "paid_api_used": False},
            "receipt_paths": [
                {"call_id": row["call_id"], "path": rel(path), "sha256": base.sha256_file(path)}
                for path, row in sorted(zip(paths, receipts), key=lambda item: item[1]["call_id"])
            ],
        }

    def candidate_representative(self, batch: dict[str, Any]) -> dict[str, Any]:
        median = batch["aggregate"]["candidate_median"]
        candidates = [row["candidate"] for row in batch["pairs"] if row["candidate"]["valid"] and row["candidate"]["score"] == median]
        if not candidates:
            raise base.CampaignError("candidate median representative unavailable")
        return min(candidates, key=lambda row: row["artifact_sha256"])

    def finalize(self) -> None:
        if not self.batch.is_file():
            raise base.CampaignError("evaluate must complete before finalize")
        if self.decision.is_file():
            print(json.dumps({"phase": "finalize", "round": self.n, "cached": True, "decision_sha256": base.sha256_file(self.decision)}))
            return
        batch = read_json(self.batch)
        if batch.get("pre_evaluation_seal_sha256") != base.sha256_file(self.global_seal):
            raise base.CampaignError("batch does not bind the pre-evaluation seal")
        promoted = bool(batch["promotion_contract_passed"])
        if promoted:
            representative = self.candidate_representative(batch)
            pair = int(representative["pair"])
            source_policy = self.arm_dir(pair, "candidate") / "artifact" / "policy.py"
            source_structure = self.proposed_structure
            source_seal: Path | None = self.arm_dir(pair, "candidate") / "seal.json"
            champion_source = "promoted-candidate"
        else:
            pair = None
            source_policy = self.previous_champion / "policy.py"
            source_structure = self.previous_champion / "structure.json"
            source_seal = None
            champion_source = f"retained-r{self.n - 1}"
        base.write_bytes_new(self.champion / "policy.py", source_policy.read_bytes())
        base.write_bytes_new(self.champion / "structure.json", source_structure.read_bytes())
        accounting = self.accounting()
        base.write_json_new(self.token_accounting, accounting)
        before = search_before(self.n)
        after = search_after(before, promoted)
        stop_binding_ref = None
        if self.n == 96:
            self.bind_stop_after_current()
            stop_binding_ref = {
                "path": rel(self.stop_after_current_binding),
                "sha256": base.sha256_file(self.stop_after_current_binding),
                "amendment_path": rel(STOP_AFTER_R96_AMENDMENT_PATH),
                "amendment_sha256": base.sha256_file(STOP_AFTER_R96_AMENDMENT_PATH),
            }
        selection = {
            "schema_version": 1,
            "display_round": self.n,
            "selected_at": base.utc_now(),
            "promoted": promoted,
            "champion_source": champion_source,
            "representative_pair": pair,
            "artifact_path": rel(self.champion / "policy.py"),
            "artifact_sha256": base.sha256_file(self.champion / "policy.py"),
            "structure_path": rel(self.champion / "structure.json"),
            "structure_sha256": base.sha256_file(self.champion / "structure.json"),
            "source_artifact_path": rel(source_policy),
            "source_artifact_sha256": base.sha256_file(source_policy),
            "source_seal_path": rel(source_seal) if source_seal else None,
            "source_seal_sha256": base.sha256_file(source_seal) if source_seal else None,
            "starting_policy_sha256": base.sha256_file(self.previous_champion / "policy.py"),
            "starting_structure_sha256": base.sha256_file(self.previous_champion / "structure.json"),
            "evaluation_batch_path": rel(self.batch),
            "evaluation_batch_sha256": base.sha256_file(self.batch),
            "promotion_contract": CONTINUATION["promotion"],
            "promotion_contract_passed": promoted,
            "decision_basis": {
                "all_six_valid_and_deterministic": batch["aggregate"]["all_six_valid_and_deterministic"],
                "candidate_wins": batch["aggregate"]["candidate_wins"],
                "incumbent_wins": batch["aggregate"]["incumbent_wins"],
                "candidate_pairwise_majority": batch["aggregate"]["candidate_pairwise_majority"],
                "incumbent_median": batch["aggregate"]["incumbent_median"],
                "candidate_median": batch["aggregate"]["candidate_median"],
                "candidate_strict_median_win": batch["aggregate"]["candidate_strict_median_win"],
                "close_confirmation_triggered": batch["close_confirmation_triggered"],
                "close_confirmation_passed": batch["confirmation_passed"],
            },
            "search_control_before": before,
            "search_control_after": after,
            "stop_after_current_binding": stop_binding_ref,
            self.guard_key: False,
        }
        base.write_json_new(self.champion / "selection-receipt.json", selection)
        decision = {
            "schema_version": 1,
            "display_round": self.n,
            "status": "round-complete",
            "proposal_mode": before["proposal_mode"],
            "promoted": promoted,
            "selection_receipt_path": rel(self.champion / "selection-receipt.json"),
            "selection_receipt_sha256": base.sha256_file(self.champion / "selection-receipt.json"),
            "champion_policy_sha256": selection["artifact_sha256"],
            "champion_structure_sha256": selection["structure_sha256"],
            "evaluation_batch_sha256": base.sha256_file(self.batch),
            "token_accounting_sha256": base.sha256_file(self.token_accounting),
            "search_control_after": after,
            "stop_after_current_binding": stop_binding_ref,
            self.guard_key: False,
        }
        base.write_json_new(self.decision, decision)
        state = {
            "schema_version": 1,
            "campaign_id": CONTINUATION["campaign_id"],
            "display_round": self.n,
            "status": f"stopped-after-display-r{self.stop_round}" if self.n == self.stop_round else f"atomic-r{self.n}-ready-for-authorized-r{self.n + 1}",
            "round_decision_path": rel(self.decision),
            "round_decision_sha256": base.sha256_file(self.decision),
            "champion_selection_receipt": rel(self.champion / "selection-receipt.json"),
            "champion_artifact_sha256": selection["artifact_sha256"],
            "champion_structure_sha256": selection["structure_sha256"],
            "promoted": promoted,
            "search_control_before": before,
            "search_control_after": after,
            "next_round_permitted": self.n < self.stop_round,
            "stop_after_display_round": self.stop_round,
            "stop_after_current_binding": stop_binding_ref,
            self.guard_key: False,
            "git_commit_created": False,
        }
        base.write_json_new(self.state, state)
        print(json.dumps({"phase": "finalize", "round": self.n, "mode": before["proposal_mode"], "promoted": promoted, "next_mode": after["next_proposal_mode"], "champion_artifact_sha256": selection["artifact_sha256"], self.guard_key: False}))

    def audit(self) -> list[str]:
        checks: list[str] = []
        source = read_json(self.source_manifest)
        require_hash(self.previous_atomic(), source["prior_atomic"]["sha256"], "prior atomic marker")
        require_hash(self.previous_champion / "policy.py", source["prior_champion"]["policy_sha256"], "prior champion policy")
        require_hash(self.previous_champion / "structure.json", source["prior_champion"]["structure_sha256"], "prior champion structure")
        checks.append("prior-atomic-champion-chain-unchanged")
        prompt = (MODEL_CALLS / f"{self.tag}-structure-architect" / "prompt.txt").read_text(encoding="utf-8")
        receipt = validate_model_receipt(MODEL_CALLS / f"{self.tag}-structure-architect" / "final-receipt.json", architect=True)
        self.validate_architect_response(read_json(self.proposal)["architect_response"], prompt, receipt)
        for score in official_score_strings(self.n - 1):
            if score and score in prompt.casefold():
                raise base.CampaignError("audit found official numeric score in architect prompt")
        checks.append("one-score-blind-sol-max-fast-architect")
        seal = read_json(self.global_seal)
        if len(seal["entries"]) != 6:
            raise base.CampaignError("audit found incomplete six-arm seal")
        inner_count = 0
        for entry in seal["entries"]:
            require_hash(CAMPAIGN_DIR / entry["artifact_path"], entry["artifact_sha256"], entry["label"])
            require_hash(CAMPAIGN_DIR / entry["seal_path"], entry["seal_sha256"], f"{entry['label']} seal")
            arm_seal = read_json(CAMPAIGN_DIR / entry["seal_path"])
            for item in arm_seal["model_receipts"]:
                validate_model_receipt(CAMPAIGN_DIR / item["path"], architect=False)
                require_hash(CAMPAIGN_DIR / item["path"], item["sha256"], "inner receipt")
                inner_count += 1
        if inner_count != seal["inner_roles"]["calls"]:
            raise base.CampaignError("audit inner receipt count differs")
        for resume in seal.get("transport_resumes", []):
            require_hash(CAMPAIGN_DIR / resume["manifest_path"], resume["manifest_sha256"], f"{resume['call_id']} transport resume")
            require_hash(CAMPAIGN_DIR / resume["failure_receipt_path"], resume["failure_receipt_sha256"], f"{resume['call_id']} transport failure")
            require_hash(CAMPAIGN_DIR / resume["attempt_01_raw_events_path"], resume["attempt_01_raw_events_sha256"], f"{resume['call_id']} failed raw stream")
        checks.append("all-six-sealed-with-luna-high-only")
        if self.n >= 6:
            binding = read_json(self.executor_epoch_binding)
            require_hash(FAST_EXECUTOR_EPOCH_CONTRACT_PATH, binding["executor_epoch_contract"]["sha256"], "Luna Fast executor epoch contract")
            if seal["inner_roles"].get("service_tier") != "fast" or seal["inner_roles"].get("request_tier") != "priority":
                raise base.CampaignError("audit found non-Fast Luna inner boundary")
            if self.n == 6:
                require_hash(PRE_FAST_QUARANTINE_MANIFEST, binding["pre_fast_quarantine"]["sha256"], "discarded pre-Fast executor epoch")
            if self.n >= 9:
                require_hash(R100_AMENDMENT_PATH, binding["r100_extension_amendment"]["sha256"], "R100 extension amendment")
            checks.append("luna-high-fast-priority-executor-epoch-bound")
        batch = read_json(self.batch)
        pairs, aggregate = self.duel_summaries()
        for key in (
            "all_six_valid_and_deterministic",
            "incumbent_median",
            "candidate_median",
            "candidate_wins",
            "incumbent_wins",
            "candidate_pairwise_majority",
            "candidate_strict_median_win",
        ):
            if aggregate[key] != batch["aggregate"][key]:
                raise base.CampaignError(f"audit recomputation differs: {key}")
        if [row["verdict"] for row in pairs] != [row["verdict"] for row in batch["pairs"]]:
            raise base.CampaignError("audit pair verdict recomputation differs")
        promoted = bool(
            aggregate["all_six_valid_and_deterministic"]
            and aggregate["candidate_pairwise_majority"]
            and aggregate["candidate_strict_median_win"]
            and batch["confirmation_passed"]
        )
        if promoted != batch["promotion_contract_passed"]:
            raise base.CampaignError("audit promotion recomputation differs")
        checks.append("frozen-replay2-close-and-promotion-recomputed")
        selection = read_json(self.champion / "selection-receipt.json")
        if selection["promoted"] != promoted:
            raise base.CampaignError("champion decision differs from promotion result")
        require_hash(self.champion / "policy.py", selection["artifact_sha256"], "round champion policy")
        require_hash(self.champion / "structure.json", selection["structure_sha256"], "round champion structure")
        if not promoted:
            if selection["artifact_sha256"] != base.sha256_file(self.previous_champion / "policy.py") or selection["structure_sha256"] != base.sha256_file(self.previous_champion / "structure.json"):
                raise base.CampaignError("nonpromotion did not retain champion exactly")
        checks.append("champion-policy-and-structure-bound-to-decision")
        state = read_json(self.state)
        expected_after = search_after(state["search_control_before"], promoted)
        if state["search_control_after"] != expected_after:
            raise base.CampaignError("state-machine transition differs from contract")
        if self.n == self.stop_round:
            if state["next_round_permitted"] is not False or state[self.guard_key] is not False:
                raise base.CampaignError(f"R{self.stop_round} stop state permits R{self.guard_round}")
            if self.n == 96:
                amendment = load_stop_after_r96_amendment()
                binding = read_json(self.stop_after_current_binding)
                require_hash(STOP_AFTER_R96_AMENDMENT_PATH, binding["amendment"]["sha256"], "R96 stop amendment")
                if (
                    binding.get("effective_stop_after_display_round") != 96
                    or binding.get("next_round_permitted") is not False
                    or binding.get("cache_r97_opened") is not False
                    or amendment["required_terminal_state"]["next_round_permitted"] is not False
                ):
                    raise base.CampaignError("R96 stop amendment binding differs")
        checks.append("state-machine-transition-and-stop-contract")
        if (WORKSPACE / "rounds" / f"R{self.guard_round}").exists() or (WORKSPACE / f"champion-r{self.guard_round}").exists():
            raise base.CampaignError(f"Cache R{self.guard_round} was opened")
        checks.append(f"cache-r{self.guard_round}-unopened")
        return checks

    def write_reports(self, test_receipt: dict[str, Any], verification: dict[str, Any]) -> None:
        batch = read_json(self.batch)
        selection = read_json(self.champion / "selection-receipt.json")
        accounting = read_json(self.token_accounting)
        proposal = read_json(self.proposal)["architect_response"]
        report = {
            "schema_version": 1,
            "campaign_id": CONTINUATION["campaign_id"],
            "display_round": self.n,
            "status": "atomic-state-ready",
            "completed_at": base.utc_now(),
            "search_control_before": search_before(self.n),
            "search_control_after": selection["search_control_after"],
            "starting_champion": read_json(self.source_manifest)["prior_champion"],
            "architect": {
                "proposal_mode": proposal["proposal_mode"],
                "structural_mutation": proposal["structural_mutation"],
                "mode_certificate": proposal["mode_certificate"],
                "proposal_path": rel(self.proposal),
                "proposal_sha256": base.sha256_file(self.proposal),
                "candidate_structure_path": rel(self.proposed_structure),
                "candidate_structure_sha256": base.sha256_file(self.proposed_structure),
                "candidate_topology_fingerprint": topology_fingerprint(read_json(self.proposed_structure)),
            },
            "benchmark": batch["benchmark"],
            "validity_semantics": {
                "preseal_generic_validity": "diagnostic only",
                "promotion_gate": "official replay validity AND generation-contract validity for all six arms, deterministic replay2, candidate pairwise majority, strict candidate median, and any triggered close confirmation",
            },
            "pairs": batch["pairs"],
            "aggregate": batch["aggregate"],
            "close_confirmation": {
                "threshold": batch["close_threshold"],
                "triggered": batch["close_confirmation_triggered"],
                "confirmations": batch["confirmations"],
                "passed": batch["confirmation_passed"],
            },
            "promotion": {"contract_passed": batch["promotion_contract_passed"], "selection": selection},
            "invalids": [
                {"pair": row["pair"], "arm": arm, "reasons": row[arm]["invalid_reasons"]}
                for row in batch["pairs"]
                for arm in ("incumbent", "candidate")
                if row[arm]["invalid_reasons"]
            ],
            "token_accounting": accounting,
            "tests": test_receipt,
            "final_audit": verification,
            "sealed_before_frozen_evaluation": True,
            "git_commit_created": False,
            "stop_after_current_binding": (
                {"path": rel(self.stop_after_current_binding), "sha256": base.sha256_file(self.stop_after_current_binding)}
                if self.n == 96
                else None
            ),
            self.guard_key: False,
        }
        base.write_json_new(self.report_json, report)
        lines = [
            f"# Cache Transfer League — display {self.tag}",
            "",
            f"Proposal mode: `{proposal['proposal_mode']}`. Structural factor: `{proposal['structural_mutation']['factor']}`.",
            "",
            "| Pair | Incumbent | Candidate | Delta | Verdict | Valid |",
            "|---:|---:|---:|---:|---|:---:|",
        ]
        for row in batch["pairs"]:
            inc = row["incumbent"]["score"]
            cand = row["candidate"]["score"]
            gap = row["candidate_minus_incumbent"]
            valid = row["incumbent"]["valid"] and row["candidate"]["valid"]
            lines.append(
                f"| {row['pair']} | {f'{inc:.4f}' if inc is not None else 'invalid'} | {f'{cand:.4f}' if cand is not None else 'invalid'} | {f'{gap:+.4f}' if gap is not None else 'n/a'} | {row['verdict']} | {'yes' if valid else 'no'} |"
            )
        agg = batch["aggregate"]
        lines.extend(
            [
                "",
                f"Medians: incumbent `{agg['incumbent_median']}`, candidate `{agg['candidate_median']}`. Wins: candidate `{agg['candidate_wins']}`, incumbent `{agg['incumbent_wins']}`, ties `{agg['ties']}`.",
                "",
                f"Close confirmation: triggered `{batch['close_confirmation_triggered']}`, passed `{batch['confirmation_passed']}`.",
                "",
                f"Promotion: `{selection['promoted']}`; champion policy `{selection['artifact_sha256']}`; structure `{selection['structure_sha256']}`.",
                "",
                f"State transition: `{selection['search_control_after']['transition']}` → `{selection['search_control_after']['next_proposal_mode']}`.",
                "",
                f"Tests: `{test_receipt['passed']}` ({test_receipt['summary']}); audit `{verification['passed']}`.",
                "",
                f"Calls `{accounting['completed_model_calls']}`, effective tokens `{accounting['round_model_calls']['effective_tokens']}`, paid API `$0.00`.",
                "",
                "Preseal generic validity is diagnostic only; promotion validity comes from official replay validity plus generation-contract validity.",
                "",
                (f"Stopped after display R{self.stop_round}. Cache R{self.guard_round} was not opened. No Git commit was created." if self.n == self.stop_round else f"Display {self.tag} committed; only authorized display R{self.n + 1} may open next."),
                "",
            ]
        )
        base.write_text_new(self.report_md, "\n".join(lines))
        if self.n == self.stop_round:
            reports = [read_json(WORKSPACE / "rounds" / f"R{number}" / f"R{number}-ROUND-REPORT.json") for number in range(self.continuation_start, self.stop_round + 1)]
            final_rows = [
                {
                    "display_round": row["display_round"],
                    "proposal_mode": row["architect"]["proposal_mode"],
                    "structural_factor": row["architect"]["structural_mutation"]["factor"],
                    "promoted": row["promotion"]["contract_passed"],
                    "candidate_wins": row["aggregate"]["candidate_wins"],
                    "incumbent_wins": row["aggregate"]["incumbent_wins"],
                    "ties": row["aggregate"]["ties"],
                    "incumbent_median": row["aggregate"]["incumbent_median"],
                    "candidate_median": row["aggregate"]["candidate_median"],
                    "champion_policy_sha256": row["promotion"]["selection"]["artifact_sha256"],
                    "champion_structure_sha256": row["promotion"]["selection"]["structure_sha256"],
                    "next_mode": row["search_control_after"]["next_proposal_mode"],
                }
                for row in reports
            ]
            final = {
                "schema_version": 1,
                "campaign_id": CONTINUATION["campaign_id"],
                "completed_display_rounds": list(range(self.continuation_start, self.stop_round + 1)),
                "rounds": final_rows,
                "final_champion": {
                    "policy_path": rel(self.champion / "policy.py"),
                    "policy_sha256": base.sha256_file(self.champion / "policy.py"),
                    "structure_path": rel(self.champion / "structure.json"),
                    "structure_sha256": base.sha256_file(self.champion / "structure.json"),
                    "selection_receipt_path": rel(self.champion / "selection-receipt.json"),
                },
                "status": f"stopped-after-display-r{self.stop_round}",
                "validity_semantics": {
                    "preseal_generic_validity": "diagnostic only",
                    "promotion_gate": "official replay validity AND generation-contract validity for all six arms, deterministic replay2, candidate pairwise majority, strict candidate median, and any triggered close confirmation",
                },
                "stop_after_current_amendment": (
                    {"path": rel(STOP_AFTER_R96_AMENDMENT_PATH), "sha256": base.sha256_file(STOP_AFTER_R96_AMENDMENT_PATH)}
                    if self.n == 96
                    else None
                ),
                "stop_after_current_binding": (
                    {"path": rel(self.stop_after_current_binding), "sha256": base.sha256_file(self.stop_after_current_binding)}
                    if self.n == 96
                    else None
                ),
                self.guard_key: False,
                "git_commit_created": False,
            }
            final_json = CAMPAIGN_DIR / f"R{self.continuation_start}-R{self.stop_round}-FINAL-REPORT.json"
            final_md = CAMPAIGN_DIR / f"R{self.continuation_start}-R{self.stop_round}-FINAL-REPORT.md"
            base.write_json_new(final_json, final)
            final_lines = [
                f"# Cache Transfer League — R{self.continuation_start} through R{self.stop_round} final report",
                "",
                "| Round | Mode | Promoted | Candidate W-L-T | Inc median | Cand median |",
                "|---:|---|:---:|---:|---:|---:|",
            ]
            for row in final_rows:
                final_lines.append(f"| R{row['display_round']} | {row['proposal_mode']} | {'yes' if row['promoted'] else 'no'} | {row['candidate_wins']}-{row['incumbent_wins']}-{row['ties']} | {row['incumbent_median']} | {row['candidate_median']} |")
            final_lines.extend(
                [
                    "",
                    f"Final policy: `{final['final_champion']['policy_sha256']}`.",
                    "",
                    f"Final structure: `{final['final_champion']['structure_sha256']}`.",
                    "",
                    "Preseal generic validity is diagnostic only; official replay validity plus generation-contract validity governs promotion eligibility.",
                    "",
                    f"Stopped after display R{self.stop_round} with `{self.guard_key}=false`. No Git commit was created.",
                    "",
                ]
            )
            base.write_text_new(final_md, "\n".join(final_lines))

    def verify(self) -> None:
        if not self.decision.is_file():
            raise base.CampaignError("finalize must complete before verify")
        if self.atomic.is_file():
            print(json.dumps({"phase": "verify", "round": self.n, "cached": True, "atomic_sha256": base.sha256_file(self.atomic)}))
            return
        started = base.utc_now()
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(CAMPAIGN_DIR / "test_evolution_contract.py")],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=180,
            check=False,
        )
        test_receipt = {
            "schema_version": 1,
            "display_round": self.n,
            "started_at": started,
            "finished_at": base.utc_now(),
            "returncode": proc.returncode,
            "passed": proc.returncode == 0,
            "summary": (proc.stdout + proc.stderr).strip(),
            "stdout_sha256": base.sha256_bytes(proc.stdout.encode("utf-8")),
            "stderr_sha256": base.sha256_bytes(proc.stderr.encode("utf-8")),
        }
        base.write_json_new(self.test_receipt, test_receipt)
        if proc.returncode != 0:
            raise base.CampaignError(f"evolution tests failed: {test_receipt['summary']}")
        checks = self.audit()
        verification = {
            "schema_version": 1,
            "display_round": self.n,
            "verified_at": base.utc_now(),
            "passed": True,
            "checks": checks,
            "test_receipt_path": rel(self.test_receipt),
            "test_receipt_sha256": base.sha256_file(self.test_receipt),
            "strict_model_split_passed": True,
            "all_six_sealed_before_score": True,
            "frozen_replay2_recomputed": True,
            "state_machine_recomputed": True,
            self.guard_key: False,
            "git_commit_created": False,
        }
        base.write_json_new(self.verification, verification)
        self.write_reports(test_receipt, verification)
        components: dict[str, Path] = {
            "continuation_contract": self.continuation_path,
            "round_contract": self.round_contract,
            "source_manifest": self.source_manifest,
            "qualitative_notebook": self.notebook,
            "proposal": self.proposal,
            "proposed_structure": self.proposed_structure,
            "hypothesis": self.hypothesis,
            "pre_evaluation_seal": self.global_seal,
            "evaluation_batch": self.batch,
            "token_accounting": self.token_accounting,
            "selection_receipt": self.champion / "selection-receipt.json",
            "champion_policy": self.champion / "policy.py",
            "champion_structure": self.champion / "structure.json",
            "round_decision": self.decision,
            "state": self.state,
            "test_receipt": self.test_receipt,
            "verification_receipt": self.verification,
            "round_report_json": self.report_json,
            "round_report_md": self.report_md,
        }
        if self.n == 96:
            components["stop_after_current_amendment"] = STOP_AFTER_R96_AMENDMENT_PATH
            components["stop_after_current_binding"] = self.stop_after_current_binding
        if self.n == self.stop_round:
            components["final_report_json"] = CAMPAIGN_DIR / f"R{self.continuation_start}-R{self.stop_round}-FINAL-REPORT.json"
            components["final_report_md"] = CAMPAIGN_DIR / f"R{self.continuation_start}-R{self.stop_round}-FINAL-REPORT.md"
        rows = {name: {"path": rel(path), "sha256": base.sha256_file(path)} for name, path in components.items()}
        marker = {
            "schema_version": 1,
            "campaign_id": CONTINUATION["campaign_id"],
            "display_round": self.n,
            "status": f"atomically-committed-stopped-after-r{self.stop_round}" if self.n == self.stop_round else "atomically-committed-round",
            "committed_at": base.utc_now(),
            "prior_atomic_path": rel(self.previous_atomic()),
            "prior_atomic_sha256": base.sha256_file(self.previous_atomic()),
            "components": rows,
            "aggregate_sha256": base.sha256_bytes(base.canonical_bytes(rows)),
            "champion_artifact_sha256": base.sha256_file(self.champion / "policy.py"),
            "champion_structure_sha256": base.sha256_file(self.champion / "structure.json"),
            "promoted": read_json(self.decision)["promoted"],
            "next_round_permitted": self.n < self.stop_round,
            "stop_after_display_round": self.stop_round,
            self.guard_key: False,
            "git_commit_created": False,
        }
        base.write_json_new(self.atomic, marker)
        print(json.dumps({"phase": "verify", "round": self.n, "tests": test_receipt["summary"], "audit_checks": len(checks), "atomic_sha256": base.sha256_file(self.atomic), self.guard_key: False}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache Transfer League contracted evolution runner")
    parser.add_argument("round", type=int, choices=AUTHORIZED_ROUNDS)
    parser.add_argument("phase", choices=("prepare", "architect", "quarantine-pre-fast", "generate", "seal", "evaluate", "finalize", "verify", "pre-eval", "all"))
    args = parser.parse_args()
    runner = RoundRunner(args.round)
    if args.phase == "prepare":
        runner.prepare()
    elif args.phase == "architect":
        runner.architect()
    elif args.phase == "quarantine-pre-fast":
        if args.round != 6:
            raise base.CampaignError("pre-Fast quarantine is only defined for R6")
        manifest = quarantine_pre_fast_r6()
        print(json.dumps({"phase": "quarantine-pre-fast", "round": 6, "completed": manifest["completed_default_tier_receipts"], "interrupted": len(manifest["interrupted_without_final_receipt"]), "generated_arms": manifest["generated_arm_artifacts"], "payload_aggregate_sha256": manifest["payload_aggregate_sha256"]}))
    elif args.phase == "generate":
        runner.generate()
    elif args.phase == "seal":
        runner.seal()
    elif args.phase == "evaluate":
        runner.evaluate()
    elif args.phase == "finalize":
        runner.finalize()
    elif args.phase == "verify":
        runner.verify()
    elif args.phase == "pre-eval":
        runner.prepare()
        runner.architect()
        runner.generate()
        runner.seal()
    else:
        runner.prepare()
        runner.architect()
        runner.generate()
        runner.seal()
        runner.evaluate()
        runner.finalize()
        runner.verify()


if __name__ == "__main__":
    main()
