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
R1_CONTRACT_PATH = CAMPAIGN_DIR / "R1-CONTRACT.json"
R1_CONTRACT = json.loads(R1_CONTRACT_PATH.read_text(encoding="utf-8"))
ROUND = WORKSPACE / "rounds" / "R1"
ARCHITECT = ROUND / "architect"
PAIRS = ROUND / "pairs"
EVALUATION = ROUND / "evaluation"
CHAMPION_R0 = WORKSPACE / "champion-r0"
CHAMPION_R1 = WORKSPACE / "champion-r1"
R0_POLICY = CHAMPION_R0 / "policy.py"
R0_STRUCTURE = CHAMPION_R0 / "structure.json"
R0_SELECTION = CHAMPION_R0 / "selection-receipt.json"
R0_ATOMIC = WORKSPACE / "R0-ATOMIC-COMMIT.json"
TASK_SNAPSHOT = WORKSPACE / "source-snapshots" / "TASK.md"
R0_REPORT = WORKSPACE / "R0-ROUND-REPORT.json"
SOURCE_MANIFEST = ROUND / "source-manifest.json"
PROPOSAL = ARCHITECT / "proposal.json"
PROPOSED_STRUCTURE = ARCHITECT / "proposed-structure.json"
HYPOTHESIS = ARCHITECT / "hypothesis.json"
GLOBAL_SEAL = ROUND / "pre-evaluation-seal.json"
EVALUATION_BATCH = EVALUATION / "evaluation-batch.json"
DECISION = ROUND / "round-decision.json"
TOKEN_ACCOUNTING = ROUND / "token-accounting.json"
STATE = ROUND / "state.json"
TEST_RECEIPT = ROUND / "test-receipt.json"
VERIFICATION = ROUND / "verification-receipt.json"
REPORT_JSON = ROUND / "R1-ROUND-REPORT.json"
REPORT_MD = CAMPAIGN_DIR / "R1-ROUND-REPORT.md"
ATOMIC_COMMIT = ROUND / "R1-ATOMIC-COMMIT.json"

EXPECTED_R0_POLICY_SHA = R1_CONTRACT["starting_champion"]["policy_sha256"]
EXPECTED_R0_STRUCTURE_SHA = R1_CONTRACT["starting_champion"]["structure_file_sha256"]
EXPECTED_R0_SELECTION_SHA = R1_CONTRACT["starting_champion"]["selection_receipt_sha256"]
EXPECTED_R0_ATOMIC_SHA = R1_CONTRACT["starting_champion"]["r0_atomic_commit_sha256"]
EXTERNAL_INPUTS = (
    "task",
    "anchor_policy",
    "anchor_contract",
    "task_constraints",
    "candidate_hypothesis",
    "loop_structure",
)
FORBIDDEN_ARCHITECT_CODE_MARKERS = (
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
    R1_CONTRACT["benchmark"]["fixture_sha256"].casefold(),
    str(R1_CONTRACT["benchmark"]["seed"]),
    "tiny_hotset",
    "scan_pollution",
    "phase_shift",
    "byte_pressure",
    "cache_policy_loop.py",
    "benchmark_fields_v3",
)


def rel(path: Path) -> str:
    return str(path.relative_to(CAMPAIGN_DIR))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require_file_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise base.CampaignError(f"missing {label}: {path}")
    actual = base.sha256_file(path)
    if actual != expected:
        raise base.CampaignError(f"{label} hash mismatch: {actual} != {expected}")


def expected_benchmark() -> dict[str, Any]:
    return {
        "field": R1_CONTRACT["benchmark"]["field"],
        "seed": R1_CONTRACT["benchmark"]["seed"],
        "scale": R1_CONTRACT["benchmark"]["scale"],
        "trace_count": R1_CONTRACT["benchmark"]["trace_count"],
        "fixture_sha256": R1_CONTRACT["benchmark"]["fixture_sha256"],
    }


def prepare() -> None:
    if R1_CONTRACT["display_round"] != 1 or R1_CONTRACT["cache_r2_permitted"] is not False:
        raise base.CampaignError("R1 contract does not stop before R2")
    if (WORKSPACE / "rounds" / "R2").exists() or (WORKSPACE / "champion-r2").exists():
        raise base.CampaignError("Cache R2 is already open")
    require_file_hash(R0_POLICY, EXPECTED_R0_POLICY_SHA, "R0 policy")
    require_file_hash(R0_STRUCTURE, EXPECTED_R0_STRUCTURE_SHA, "R0 structure")
    require_file_hash(R0_SELECTION, EXPECTED_R0_SELECTION_SHA, "R0 selection receipt")
    require_file_hash(R0_ATOMIC, EXPECTED_R0_ATOMIC_SHA, "R0 atomic state")
    selection = read_json(R0_SELECTION)
    if selection.get("display_source_round") != 20 or selection.get("display_round") != 0:
        raise base.CampaignError("authoritative R0 is not the fixed R20 topology champion")
    if selection.get("artifact_sha256") != EXPECTED_R0_POLICY_SHA:
        raise base.CampaignError("R0 selection does not bind the champion policy")
    r0_atomic = read_json(R0_ATOMIC)
    if r0_atomic.get("display_round") != 0:
        raise base.CampaignError("R0 atomic state has the wrong display round")
    root_manifest = read_json(WORKSPACE / "source-manifest.json")
    root_fixture = root_manifest["fixture"]
    if (
        root_fixture.get("seed") != R1_CONTRACT["benchmark"]["seed"]
        or root_fixture.get("scale") != R1_CONTRACT["benchmark"]["scale"]
        or root_fixture.get("trace_count") != R1_CONTRACT["benchmark"]["trace_count"]
        or root_fixture.get("canonical_sha256") != R1_CONTRACT["benchmark"]["fixture_sha256"]
    ):
        raise base.CampaignError("R0 source manifest benchmark differs from R1 contract")
    require_file_hash(
        base.RUNNER_SOURCE,
        root_manifest["frozen_runner"]["sha256"],
        "authoritative frozen runner",
    )
    require_file_hash(
        TASK_SNAPSHOT,
        root_manifest["task"]["sha256"],
        "authoritative task snapshot",
    )
    payload = {
        "schema_version": 1,
        "campaign_id": R1_CONTRACT["campaign_id"],
        "display_round": 1,
        "prepared_at": base.utc_now(),
        "r1_contract": {"path": rel(R1_CONTRACT_PATH), "sha256": base.sha256_file(R1_CONTRACT_PATH)},
        "starting_champion": {
            "display_round": 0,
            "source_topology": "R20",
            "policy": {"path": rel(R0_POLICY), "sha256": base.sha256_file(R0_POLICY)},
            "structure": {"path": rel(R0_STRUCTURE), "sha256": base.sha256_file(R0_STRUCTURE)},
            "selection_receipt": {"path": rel(R0_SELECTION), "sha256": base.sha256_file(R0_SELECTION)},
            "atomic_state": {"path": rel(R0_ATOMIC), "sha256": base.sha256_file(R0_ATOMIC)},
        },
        "task": {"path": rel(TASK_SNAPSHOT), "sha256": base.sha256_file(TASK_SNAPSHOT)},
        "frozen_runner": {
            "authority_path": str(base.RUNNER_SOURCE),
            "sha256": base.sha256_file(base.RUNNER_SOURCE),
        },
        "benchmark": expected_benchmark(),
        "generation_visibility": {
            "official_scores": False,
            "benchmark_trace_contents": False,
            "benchmark_fixture_identity_in_model_prompts": False,
            "prior_cache_round_artifacts_other_than_authoritative_r0": False,
        },
        "cache_r2_opened": False,
    }
    if SOURCE_MANIFEST.is_file():
        existing = read_json(SOURCE_MANIFEST)
        comparable = dict(existing)
        comparable["prepared_at"] = payload["prepared_at"]
        if comparable != payload:
            raise base.CampaignError("existing R1 source manifest differs")
    else:
        base.write_json_new(SOURCE_MANIFEST, payload)
    print(json.dumps({"phase": "prepare-r1", "r0_policy_sha256": EXPECTED_R0_POLICY_SHA}))


def architect_prompt(task_text: str, r0_structure: dict[str, Any]) -> str:
    qualitative_evidence = {
        "bounded_observation": (
            "The current champion uses one self-contained terminal producer. The same call owns "
            "diagnosis, implementation, causal acceptance/compression, and final emission."
        ),
        "contract_observation": (
            "The bootstrap lineage was contract-valid, while an independently visible post-build "
            "falsification boundary is absent from the topology."
        ),
        "evidence_limit": (
            "No numeric outcome, workload case, fixture content, hidden trace, or benchmark error is available."
        ),
    }
    return f"""
You are the sole STRUCTURE ARCHITECT for Cache display R1. Design exactly one
structural mutation from the incumbent R0 topology. You may output only one
qualitative, score-blind hypothesis plus roles, topology, visibility, and a
causal falsifier. Never output policy code, pseudocode, an algorithm listing,
implementation parameters, benchmark-specific constants, variants, or final
policy source. Do not use tools or inspect the filesystem; all permissible
information is inline below.

This is one hypothesis, not a search. Return exactly one candidate topology.
No alternatives, best-of-N, branches, voting, parallel sampling, parameter
sweeps, or repair retries are permitted. The mutation must name one structural
factor and must not bundle a second factor. It must change the one-call R0 graph
into one non-branching sequential lineage of two or three calls. The first
candidate call must retain the incumbent call's six external inputs in the same
order. Each later call must consume the immediately preceding call id and may
also consume any of those same external inputs. Every nonfinal output must be
consumed by the next call. The final call must be last and output one policy.
Intermediate calls may output either analysis or a provisional policy. Keep
objectives about role separation, evidence flow, falsification, and finalization;
do not prescribe a cache algorithm.

Permitted external input names, and no others:
{json.dumps(list(EXTERNAL_INPUTS), ensure_ascii=False)}

Return one strict JSON object and no prose:
{{
  "architect_scope": "one-r1-structural-mutation-only",
  "qualitative_hypothesis": {{
    "observed_bottleneck": "score-free structural claim",
    "causal_change": "the one topology change",
    "expected_effect": "score-free expected effect",
    "falsifier": "matched-pair all-valid majority and strict-median contract"
  }},
  "mutation": {{
    "change_count": 1,
    "factor": "one concise topology factor",
    "before": "one self-contained terminal producer",
    "after": "one non-branching sequential lineage",
    "why_structural": "graph or role-visibility explanation"
  }},
  "candidate_structure": {{
    "name": "...",
    "organization": "...",
    "information_flow": "...",
    "stages": [
      {{"id": "...", "mode": "sequential", "calls": [
        {{"id": "...", "role": "...", "objective": "...", "inputs": {json.dumps(list(EXTERNAL_INPUTS))}, "output_type": "analysis"}},
        {{"id": "...", "role": "...", "objective": "...", "inputs": ["previous_call_id"], "output_type": "policy"}}
      ]}}
    ],
    "final_call_id": "..."
  }},
  "compliance": {{
    "one_mutation_only": true,
    "score_or_trace_content_used": false,
    "policy_code_emitted": false,
    "variants_or_sampling_emitted": false
  }}
}}

Generic Cache Policy objective and interface:
---
{task_text}
---

Bounded qualitative R0 evidence:
{json.dumps(qualitative_evidence, indent=2, ensure_ascii=False)}

Incumbent R0 topology, with no outcome data:
{json.dumps(r0_structure, indent=2, ensure_ascii=False)}
""".strip()


def known_r0_score_strings() -> set[str]:
    report = read_json(R0_REPORT)
    values: set[str] = set()

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif key in {"score", "median_score", "minimum_score", "mean_score"} and isinstance(value, (int, float)):
            values.add(str(value).casefold())

    walk(report)
    return values


def validate_structure(structure: Any) -> list[dict[str, Any]]:
    if not isinstance(structure, dict):
        raise base.CampaignError("architect candidate_structure is not an object")
    stages = structure.get("stages")
    if not isinstance(stages, list) or not stages:
        raise base.CampaignError("candidate topology needs stages")
    calls: list[dict[str, Any]] = []
    stage_ids: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("mode") != "sequential":
            raise base.CampaignError("candidate topology must be entirely sequential")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", stage_id):
            raise base.CampaignError("candidate stage id is invalid")
        if stage_id in stage_ids:
            raise base.CampaignError("candidate stage ids are not unique")
        stage_ids.add(stage_id)
        stage_calls = stage.get("calls")
        if not isinstance(stage_calls, list) or not stage_calls:
            raise base.CampaignError("candidate stage has no calls")
        calls.extend(stage_calls)
    if not 2 <= len(calls) <= 3:
        raise base.CampaignError("candidate mutation must contain two or three calls")
    ids: list[str] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise base.CampaignError("candidate call is not an object")
        call_id = call.get("id")
        if not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", call_id):
            raise base.CampaignError("candidate call id is invalid")
        if call_id in ids:
            raise base.CampaignError("candidate call ids are not unique")
        ids.append(call_id)
        if not isinstance(call.get("role"), str) or not call["role"].strip():
            raise base.CampaignError("candidate call role is missing")
        if not isinstance(call.get("objective"), str) or not call["objective"].strip():
            raise base.CampaignError("candidate call objective is missing")
        if call.get("output_type") not in {"analysis", "policy"}:
            raise base.CampaignError("candidate output_type is invalid")
        inputs = call.get("inputs")
        if not isinstance(inputs, list) or any(not isinstance(item, str) for item in inputs):
            raise base.CampaignError("candidate call inputs are invalid")
        if len(inputs) != len(set(inputs)):
            raise base.CampaignError("candidate call inputs contain duplicates")
        if index == 0:
            if inputs != list(EXTERNAL_INPUTS):
                raise base.CampaignError("candidate first call did not retain common inputs")
        else:
            prior_id = ids[index - 1]
            if prior_id not in inputs:
                raise base.CampaignError("candidate lineage does not consume its immediate predecessor")
            forbidden_dependencies = set(ids[:-2])
            if forbidden_dependencies.intersection(inputs):
                raise base.CampaignError("candidate topology bypasses the non-branching lineage")
            if any(item not in EXTERNAL_INPUTS and item != prior_id for item in inputs):
                raise base.CampaignError("candidate call has an unresolvable input")
    if structure.get("final_call_id") != ids[-1] or calls[-1].get("output_type") != "policy":
        raise base.CampaignError("candidate final call is not the last policy producer")
    for index, call in enumerate(calls[:-1]):
        if call["id"] not in calls[index + 1]["inputs"]:
            raise base.CampaignError("candidate nonfinal output is not consumed by the next call")
    return calls


def validate_architect_response(parsed: Any, prompt: str, receipt: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise base.CampaignError("architect response is not an object")
    if parsed.get("architect_scope") != "one-r1-structural-mutation-only":
        raise base.CampaignError("architect scope is invalid")
    mutation = parsed.get("mutation")
    if not isinstance(mutation, dict) or mutation.get("change_count") != 1:
        raise base.CampaignError("architect did not certify exactly one mutation")
    for key in ("factor", "before", "after", "why_structural"):
        if not isinstance(mutation.get(key), str) or not mutation[key].strip():
            raise base.CampaignError(f"architect mutation field is missing: {key}")
    hypothesis = parsed.get("qualitative_hypothesis")
    if not isinstance(hypothesis, dict):
        raise base.CampaignError("architect hypothesis is missing")
    for key in ("observed_bottleneck", "causal_change", "expected_effect", "falsifier"):
        if not isinstance(hypothesis.get(key), str) or not hypothesis[key].strip():
            raise base.CampaignError(f"architect hypothesis field is missing: {key}")
    compliance = parsed.get("compliance")
    expected_compliance = {
        "one_mutation_only": True,
        "score_or_trace_content_used": False,
        "policy_code_emitted": False,
        "variants_or_sampling_emitted": False,
    }
    if compliance != expected_compliance:
        raise base.CampaignError("architect compliance certificate is invalid")
    calls = validate_structure(parsed.get("candidate_structure"))
    if base.canonical_bytes(parsed["candidate_structure"]) == base.canonical_bytes(read_json(R0_STRUCTURE)):
        raise base.CampaignError("architect candidate equals the incumbent structure")
    serialized = json.dumps(parsed, sort_keys=True, ensure_ascii=False).casefold()
    prompt_lower = prompt.casefold()
    for marker in FORBIDDEN_ARCHITECT_CODE_MARKERS:
        if marker in serialized:
            raise base.CampaignError(f"architect emitted forbidden policy-code marker: {marker}")
    for marker in FORBIDDEN_BENCHMARK_MARKERS:
        if marker in serialized or marker in prompt_lower:
            raise base.CampaignError(f"architect visibility contains benchmark marker: {marker}")
    for score in known_r0_score_strings():
        if score and (score in serialized or score in prompt_lower):
            raise base.CampaignError("architect visibility contains an official R0 score")
    if (
        receipt.get("model") != "gpt-5.6-sol"
        or receipt.get("reasoning_effort") != "max"
        or receipt.get("service_tier") != "fast"
        or receipt.get("request_tier") != "priority"
        or receipt.get("tools_used") != []
    ):
        raise base.CampaignError("architect receipt violates Sol/max/Fast priority boundary")
    return {"candidate_call_count": len(calls), "mutation_factor": mutation["factor"]}


def architect() -> None:
    prepare()
    if PROPOSAL.is_file():
        proposal = read_json(PROPOSAL)
        receipt = read_json(MODEL_CALLS / "R1-structural-mutation-architect" / "final-receipt.json")
        prompt = (MODEL_CALLS / "R1-structural-mutation-architect" / "prompt.txt").read_text(encoding="utf-8")
        validate_architect_response(proposal["architect_response"], prompt, receipt)
        print(json.dumps({"phase": "architect-r1", "cached": True, "proposal_sha256": base.sha256_file(PROPOSAL)}))
        return
    task_text = TASK_SNAPSHOT.read_text(encoding="utf-8")
    r0_structure = read_json(R0_STRUCTURE)
    prompt = architect_prompt(task_text, r0_structure)
    # Fail before transport if the inline architect prompt accidentally exposes frozen data.
    prompt_lower = prompt.casefold()
    for marker in FORBIDDEN_BENCHMARK_MARKERS:
        if marker in prompt_lower:
            raise base.CampaignError(f"architect prompt contains forbidden benchmark marker: {marker}")
    for score in known_r0_score_strings():
        if score and score in prompt_lower:
            raise base.CampaignError("architect prompt contains an official R0 score")
    parsed, receipt = base.run_codex(
        call_id="R1-structural-mutation-architect",
        role="score-blind Cache R1 structure architect; topology only, never policy code",
        prompt=prompt,
        model="gpt-5.6-sol",
        effort="max",
        home_slot=0,
        service_tier="fast",
        timeout_seconds=1800,
    )
    audit = validate_architect_response(parsed, prompt, receipt)
    receipt_path = MODEL_CALLS / "R1-structural-mutation-architect" / "final-receipt.json"
    proposal = {
        "schema_version": 1,
        "display_round": 1,
        "architect_response": parsed,
        "architect_receipt": {"path": rel(receipt_path), "sha256": base.sha256_file(receipt_path)},
        "source_manifest": {"path": rel(SOURCE_MANIFEST), "sha256": base.sha256_file(SOURCE_MANIFEST)},
        "r0_structure_sha256": base.sha256_file(R0_STRUCTURE),
        "task_sha256": base.sha256_file(TASK_SNAPSHOT),
        "score_blind": True,
        "official_scores_visible": False,
        "benchmark_fixtures_visible": False,
        "validation": audit,
    }
    base.write_json_new(PROPOSAL, proposal)
    base.write_json_new(PROPOSED_STRUCTURE, parsed["candidate_structure"])
    base.write_json_new(HYPOTHESIS, parsed["qualitative_hypothesis"])
    print(
        json.dumps(
            {
                "phase": "architect-r1",
                "proposal_sha256": base.sha256_file(PROPOSAL),
                "candidate_calls": audit["candidate_call_count"],
                "mutation_factor": audit["mutation_factor"],
            }
        )
    )


def visible_value(
    name: str,
    *,
    task_text: str,
    anchor_source: str,
    anchor_sha256: str,
    hypothesis: dict[str, Any],
    structure: dict[str, Any],
    prior_outputs: dict[str, Any],
) -> Any:
    if name == "task":
        return task_text
    if name == "anchor_policy":
        return {"artifact": "policy.py", "sha256": anchor_sha256, "policy_source": anchor_source}
    if name == "anchor_contract":
        return {
            "artifact_kind": "immutable display-R0 champion policy anchor",
            "artifact_sha256": anchor_sha256,
            "structure_source": "fixed R20 topology champion",
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


def arm_role_prompt(
    *,
    pair: int,
    arm: str,
    call: dict[str, Any],
    visible_inputs: dict[str, Any],
) -> str:
    if call["output_type"] == "policy":
        output_contract = """
Return one strict JSON object and no prose:
{"policy_source":"complete contents of policy.py","artifact_kind":"single_policy"}
The source must be complete, deterministic, online-only, standard-library-only,
and define class Policy with __init__(capacity_bytes) and access(key, size, now).
Return one policy lineage only: no diff, variants, benchmark data, evaluator
constants, trace recognition, parameter sweep, or ranked selection.
""".strip()
    elif call["output_type"] == "analysis":
        output_contract = """
Return one strict JSON object and no prose:
{"analysis_packet":{"certificate":"...","witnesses":[],"obligations":[],"exact_actions":[]},"artifact_kind":"analysis_only"}
Do not output Python, policy source, a patch, a diff, alternative policies, or
a ranked selection. Analyze and falsify only the one visible lineage.
""".strip()
    else:
        raise base.CampaignError("unsupported topology output type")
    return f"""
Execute exactly one Luna-high inner-loop role in Cache display R1 matched pair
{pair}, {arm} arm. This pipeline is independent: no other arm, pair, artifact,
evaluation, benchmark result, or official score is visible. Use only the inline
inputs below. Do not use tools, inspect files, search, sample, branch, retry a
policy design, or ask another agent.

Both arms in this pair are bound to the same immutable R0 champion anchor, task,
task constraints, and score-blind improvement hypothesis. Execute the role and
visibility graph exactly as supplied; do not redesign the topology.

Role id: {call['id']}
Role: {call['role']}
Objective: {call['objective']}
Output kind: {call['output_type']}

{output_contract}

Visible inputs fixed by this arm's topology:
{json.dumps(visible_inputs, indent=2, ensure_ascii=False)}
""".strip()


def arm_dir(pair: int, arm: str) -> Path:
    return PAIRS / f"pair-{pair:02d}" / arm


def arm_label(pair: int, arm: str) -> str:
    return f"pair-{pair:02d}-{arm}"


def generate_arm(
    *,
    pair: int,
    arm: str,
    requested_home_slot: int,
    task_text: str,
    anchor_source: str,
    anchor_sha256: str,
    hypothesis: dict[str, Any],
    structure: dict[str, Any],
    structure_path: Path,
) -> dict[str, Any]:
    target_dir = arm_dir(pair, arm)
    manifest_path = target_dir / "generation-manifest.json"
    if manifest_path.is_file():
        return read_json(manifest_path)
    calls = base.flattened_calls(structure)
    prior_outputs: dict[str, Any] = {}
    call_receipts: list[dict[str, Any]] = []
    for call_index, call in enumerate(calls, start=1):
        visible_inputs = {
            name: visible_value(
                name,
                task_text=task_text,
                anchor_source=anchor_source,
                anchor_sha256=anchor_sha256,
                hypothesis=hypothesis,
                structure=structure,
                prior_outputs=prior_outputs,
            )
            for name in call["inputs"]
        }
        safe_role_id = re.sub(r"[^A-Za-z0-9_-]", "_", call["id"])
        call_id = f"R1-pair{pair:02d}-{arm}-call{call_index:02d}-{safe_role_id}"
        parsed, receipt = base.run_codex(
            call_id=call_id,
            role=f"R1 {arm} topology role {call['role']}",
            prompt=arm_role_prompt(pair=pair, arm=arm, call=call, visible_inputs=visible_inputs),
            model="gpt-5.6-luna",
            effort="high",
            home_slot=requested_home_slot,
            service_tier=None,
            timeout_seconds=1200,
        )
        if (
            receipt.get("model") != "gpt-5.6-luna"
            or receipt.get("reasoning_effort") != "high"
            or receipt.get("service_tier") != "default"
            or receipt.get("request_tier") != "default"
            or receipt.get("requested_home_slot") != requested_home_slot
            or receipt.get("home_slot") != requested_home_slot
            or receipt.get("tools_used") != []
        ):
            raise base.CampaignError(f"{call_id} receipt violates Luna-high independent routing")
        if call["output_type"] == "policy":
            source = base.extract_policy_source(parsed, call_id=call_id)
            output: dict[str, Any] = {
                "artifact_kind": "policy",
                "policy_source": source,
                "sha256": base.sha256_bytes(source.encode("utf-8")),
            }
        else:
            if not isinstance(parsed, dict) or parsed.get("artifact_kind") != "analysis_only":
                raise base.CampaignError(f"{call_id} did not return analysis_only")
            serialized = json.dumps(parsed, sort_keys=True, ensure_ascii=False).casefold()
            if any(marker in serialized for marker in ("class policy", "def access", "```python", "policy_source")):
                raise base.CampaignError(f"{call_id} emitted policy code from analysis role")
            output = parsed
        prior_outputs[str(call["id"])] = output
        receipt_path = MODEL_CALLS / call_id / "final-receipt.json"
        call_receipts.append(
            {
                "call_id": call_id,
                "role_id": call["id"],
                "output_type": call["output_type"],
                "path": rel(receipt_path),
                "sha256": base.sha256_file(receipt_path),
                "usage": receipt["usage"],
                "requested_home_slot": requested_home_slot,
                "actual_home_slot": receipt["home_slot"],
            }
        )
    final = prior_outputs.get(structure["final_call_id"])
    if not isinstance(final, dict) or final.get("artifact_kind") != "policy":
        raise base.CampaignError(f"{arm_label(pair, arm)} final call did not emit policy")
    artifact_path = target_dir / "artifact" / "policy.py"
    base.write_text_new(artifact_path, final["policy_source"])
    manifest = {
        "schema_version": 1,
        "display_round": 1,
        "pair": pair,
        "arm": arm,
        "independent": True,
        "other_arm_visible": False,
        "other_pairs_visible": False,
        "official_scores_visible": False,
        "benchmark_fixtures_visible": False,
        "model": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "requested_home_slot": requested_home_slot,
        "anchor_sha256": anchor_sha256,
        "task_sha256": base.sha256_file(TASK_SNAPSHOT),
        "hypothesis_sha256": base.sha256_file(HYPOTHESIS),
        "structure_path": rel(structure_path),
        "structure_sha256": base.sha256_file(structure_path),
        "artifact_path": rel(artifact_path),
        "artifact_sha256": base.sha256_file(artifact_path),
        "call_receipts": call_receipts,
    }
    base.write_json_new(manifest_path, manifest)
    print(
        json.dumps(
            {
                "generated": arm_label(pair, arm),
                "calls": len(calls),
                "artifact_sha256": manifest["artifact_sha256"],
                "home_slot": requested_home_slot,
            }
        ),
        flush=True,
    )
    return manifest


def routing_slot(pair: int, arm: str) -> int:
    row = R1_CONTRACT["duel"]["routing"][f"pair_{pair}"]
    return int(row[f"{arm}_home_slot"])


def generate() -> None:
    architect()
    task_text = TASK_SNAPSHOT.read_text(encoding="utf-8")
    anchor_source = R0_POLICY.read_text(encoding="utf-8")
    anchor_sha = base.sha256_file(R0_POLICY)
    hypothesis = read_json(HYPOTHESIS)
    structures = {"incumbent": read_json(R0_STRUCTURE), "candidate": read_json(PROPOSED_STRUCTURE)}
    structure_paths = {"incumbent": R0_STRUCTURE, "candidate": PROPOSED_STRUCTURE}
    jobs = [(pair, arm, routing_slot(pair, arm)) for pair in range(1, 4) for arm in ("incumbent", "candidate")]
    queues = {
        slot: [job for job in jobs if job[2] == slot]
        for slot in sorted({job[2] for job in jobs})
    }
    if set(queues) != {0, 2}:
        raise base.CampaignError("R1 crossed routing must use home slots 0 and 2")

    def run_queue(queue: list[tuple[int, str, int]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for pair, arm, slot in queue:
            rows.append(
                generate_arm(
                    pair=pair,
                    arm=arm,
                    requested_home_slot=slot,
                    task_text=task_text,
                    anchor_source=anchor_source,
                    anchor_sha256=anchor_sha,
                    hypothesis=hypothesis,
                    structure=structures[arm],
                    structure_path=structure_paths[arm],
                )
            )
        return rows

    manifests: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cache-r1-home") as pool:
        futures = [pool.submit(run_queue, queue) for queue in queues.values()]
        for future in as_completed(futures):
            manifests.extend(future.result())
    if len(manifests) != 6:
        raise base.CampaignError("R1 generation did not produce six arm manifests")
    if {item["anchor_sha256"] for item in manifests} != {anchor_sha}:
        raise base.CampaignError("R1 arms do not share the immutable R0 anchor")
    if len({item["hypothesis_sha256"] for item in manifests}) != 1:
        raise base.CampaignError("R1 arms do not share one hypothesis")
    print(json.dumps({"phase": "generate-r1", "arms": 6, "shared_anchor_sha256": anchor_sha}))


def validate_receipt(path: Path, *, architect_receipt: bool = False) -> dict[str, Any]:
    receipt = read_json(path)
    if architect_receipt:
        if (
            receipt.get("model") != "gpt-5.6-sol"
            or receipt.get("reasoning_effort") != "max"
            or receipt.get("service_tier") != "fast"
            or receipt.get("request_tier") != "priority"
            or receipt.get("tools_used") != []
        ):
            raise base.CampaignError("architect receipt failed model-boundary audit")
    else:
        if (
            receipt.get("model") != "gpt-5.6-luna"
            or receipt.get("reasoning_effort") != "high"
            or receipt.get("service_tier") != "default"
            or receipt.get("request_tier") != "default"
            or receipt.get("tools_used") != []
        ):
            raise base.CampaignError(f"inner receipt failed Luna-high audit: {receipt.get('call_id')}")
    return receipt


def seal() -> None:
    generate()
    if GLOBAL_SEAL.is_file():
        existing = read_json(GLOBAL_SEAL)
        for entry in existing["entries"]:
            require_file_hash(CAMPAIGN_DIR / entry["artifact_path"], entry["artifact_sha256"], entry["label"])
            require_file_hash(CAMPAIGN_DIR / entry["seal_path"], entry["seal_sha256"], f"{entry['label']} seal")
        print(json.dumps({"phase": "seal-r1", "cached": True, "arms": len(existing["entries"])}))
        return
    if EVALUATION.exists() and any(EVALUATION.rglob("replay-*.json")):
        raise base.CampaignError("frozen evaluation exists before the R1 global seal")
    architect_receipt_path = MODEL_CALLS / "R1-structural-mutation-architect" / "final-receipt.json"
    architect_receipt = validate_receipt(architect_receipt_path, architect_receipt=True)
    prompt = (MODEL_CALLS / "R1-structural-mutation-architect" / "prompt.txt").read_text(encoding="utf-8")
    validate_architect_response(read_json(PROPOSAL)["architect_response"], prompt, architect_receipt)
    structures = {"incumbent": read_json(R0_STRUCTURE), "candidate": read_json(PROPOSED_STRUCTURE)}
    expected_inner_calls = 0
    entries: list[dict[str, Any]] = []
    common_anchor: set[str] = set()
    common_task: set[str] = set()
    common_hypothesis: set[str] = set()
    for pair in range(1, 4):
        for arm in ("incumbent", "candidate"):
            target_dir = arm_dir(pair, arm)
            manifest_path = target_dir / "generation-manifest.json"
            artifact_path = target_dir / "artifact" / "policy.py"
            manifest = read_json(manifest_path)
            expected_call_count = len(base.flattened_calls(structures[arm]))
            if len(manifest.get("call_receipts", [])) != expected_call_count:
                raise base.CampaignError(f"{arm_label(pair, arm)} call count violates topology")
            if manifest.get("requested_home_slot") != routing_slot(pair, arm):
                raise base.CampaignError(f"{arm_label(pair, arm)} routing differs from contract")
            for item in manifest["call_receipts"]:
                receipt_path = CAMPAIGN_DIR / item["path"]
                receipt = validate_receipt(receipt_path)
                if receipt.get("requested_home_slot") != routing_slot(pair, arm) or receipt.get("home_slot") != routing_slot(pair, arm):
                    raise base.CampaignError(f"{item['call_id']} crossed-home routing failed")
                if base.sha256_file(receipt_path) != item["sha256"]:
                    raise base.CampaignError(f"{item['call_id']} receipt hash differs")
                expected_inner_calls += 1
            common_anchor.add(manifest["anchor_sha256"])
            common_task.add(manifest["task_sha256"])
            common_hypothesis.add(manifest["hypothesis_sha256"])
            validation = base.generic_validate_policy(artifact_path)
            seal_path = target_dir / "seal.json"
            arm_seal = {
                "schema_version": 1,
                "display_round": 1,
                "label": arm_label(pair, arm),
                "pair": pair,
                "arm": arm,
                "sealed_at": base.utc_now(),
                "artifact_path": rel(artifact_path),
                "artifact_sha256": base.sha256_file(artifact_path),
                "artifact_bytes": artifact_path.stat().st_size,
                "generation_manifest_path": rel(manifest_path),
                "generation_manifest_sha256": base.sha256_file(manifest_path),
                "model_receipts": [
                    {"path": item["path"], "sha256": item["sha256"]}
                    for item in manifest["call_receipts"]
                ],
                "preseal_generic_validity": validation,
                "official_score_known_at_seal": False,
                "frozen_evaluation_known_at_seal": False,
            }
            base.write_json_new(seal_path, arm_seal)
            entries.append(
                {
                    "label": arm_seal["label"],
                    "pair": pair,
                    "arm": arm,
                    "artifact_path": arm_seal["artifact_path"],
                    "artifact_sha256": arm_seal["artifact_sha256"],
                    "seal_path": rel(seal_path),
                    "seal_sha256": base.sha256_file(seal_path),
                    "generic_valid": validation["valid"],
                }
            )
    if len(entries) != 6 or len(common_anchor) != 1 or len(common_task) != 1 or len(common_hypothesis) != 1:
        raise base.CampaignError("R1 common-input or six-arm seal invariant failed")
    expected_dynamic = 3 * (
        len(base.flattened_calls(structures["incumbent"]))
        + len(base.flattened_calls(structures["candidate"]))
    )
    if expected_inner_calls != expected_dynamic:
        raise base.CampaignError("R1 inner call count differs from the two topology graphs")
    selection_contract = {
        "pair_rule": R1_CONTRACT["pair_rule"],
        "promotion": R1_CONTRACT["promotion"],
        "close_confirmation": R1_CONTRACT["close_confirmation"],
        "tie_breaks": R1_CONTRACT["tie_breaks"],
        "predeclared_before_score_reveal": True,
    }
    global_seal = {
        "schema_version": 1,
        "display_round": 1,
        "sealed_at": base.utc_now(),
        "sealed_before_any_frozen_evaluation": True,
        "score_blind_generation": True,
        "pair_count": 3,
        "arm_count": 6,
        "architect": {
            "calls": 1,
            "receipt_path": rel(architect_receipt_path),
            "receipt_sha256": base.sha256_file(architect_receipt_path),
            "proposal_path": rel(PROPOSAL),
            "proposal_sha256": base.sha256_file(PROPOSAL),
            "model": "gpt-5.6-sol",
            "reasoning_effort": "max",
            "service_tier": "fast",
            "request_tier": "priority",
            "policy_code_emitted": False,
        },
        "inner_roles": {
            "calls": expected_inner_calls,
            "model": "gpt-5.6-luna",
            "reasoning_effort": "high",
            "service_tier": "default",
        },
        "common_inputs": {
            "anchor_policy_sha256": next(iter(common_anchor)),
            "task_sha256": next(iter(common_task)),
            "hypothesis_sha256": next(iter(common_hypothesis)),
        },
        "structures": {
            "incumbent": {"path": rel(R0_STRUCTURE), "sha256": base.sha256_file(R0_STRUCTURE), "call_count": len(base.flattened_calls(structures["incumbent"]))},
            "candidate": {"path": rel(PROPOSED_STRUCTURE), "sha256": base.sha256_file(PROPOSED_STRUCTURE), "call_count": len(base.flattened_calls(structures["candidate"]))},
        },
        "entries": entries,
        "aggregate_sha256": base.sha256_bytes(base.canonical_bytes(entries)),
        "benchmark_identity": expected_benchmark(),
        "selection_contract": selection_contract,
        "selection_contract_sha256": base.sha256_bytes(base.canonical_bytes(selection_contract)),
        "cache_r2_opened": False,
    }
    base.write_json_new(GLOBAL_SEAL, global_seal)
    print(
        json.dumps(
            {
                "phase": "seal-r1",
                "arms": len(entries),
                "generic_valid": sum(bool(item["generic_valid"]) for item in entries),
                "inner_calls": expected_inner_calls,
                "aggregate_sha256": global_seal["aggregate_sha256"],
            }
        )
    )


def evaluation_dir(pair: int, arm: str) -> Path:
    return EVALUATION / f"pair-{pair:02d}" / arm


def run_replay(
    *,
    pair: int,
    arm: str,
    entry: dict[str, Any],
    replay: int,
    runner: Any,
    traces: list[Any],
) -> dict[str, Any]:
    target = evaluation_dir(pair, arm) / f"replay-{replay:02d}.json"
    if target.is_file():
        existing = read_json(target)
        if existing.get("artifact_sha256") != entry["artifact_sha256"]:
            raise base.CampaignError(f"existing replay artifact differs: {entry['label']}")
        return existing
    artifact_path = CAMPAIGN_DIR / entry["artifact_path"]
    require_file_hash(artifact_path, entry["artifact_sha256"], entry["label"])
    started_at = base.utc_now()
    started = time.monotonic()
    result = runner.evaluate_candidate(artifact_path, traces=traces, timeout_s=60.0)
    normalized = base.normalized_evaluation_result(result)
    record = {
        "schema_version": 1,
        "display_round": 1,
        "pair": pair,
        "arm": arm,
        "label": entry["label"],
        "replay": replay,
        "artifact_path": entry["artifact_path"],
        "artifact_sha256": entry["artifact_sha256"],
        "benchmark": expected_benchmark() | {"runner_sha256": base.sha256_file(base.RUNNER_SOURCE)},
        "started_at": started_at,
        "finished_at": base.utc_now(),
        "duration_seconds": round(time.monotonic() - started, 6),
        "result": result,
        "normalized_result_sha256": base.sha256_bytes(base.canonical_bytes(normalized)),
        "valid": base.official_result_valid(result),
    }
    base.write_json_new(target, record)
    print(
        json.dumps(
            {"evaluated": entry["label"], "replay": replay, "score": result.get("score"), "valid": record["valid"]}
        ),
        flush=True,
    )
    return record


def arm_summary(pair: int, arm: str, required_replays: int = 2) -> dict[str, Any]:
    records = [read_json(evaluation_dir(pair, arm) / f"replay-{index:02d}.json") for index in range(1, required_replays + 1)]
    hashes = {row["normalized_result_sha256"] for row in records}
    valid = all(bool(row["valid"]) for row in records) and len(hashes) == 1
    score_value = records[0]["result"].get("score")
    score = float(score_value) if isinstance(score_value, (int, float)) and math.isfinite(float(score_value)) else None
    invalid_reasons: list[str] = []
    if any(not row["valid"] for row in records):
        invalid_reasons.append("official_replay_invalid")
    if len(hashes) != 1:
        invalid_reasons.append("replay_nondeterministic")
    if score is None:
        invalid_reasons.append("nonfinite_or_missing_score")
        valid = False
    return {
        "pair": pair,
        "arm": arm,
        "artifact_sha256": records[0]["artifact_sha256"],
        "score": score,
        "valid": valid,
        "replay_deterministic": len(hashes) == 1,
        "normalized_result_sha256": records[0]["normalized_result_sha256"],
        "invalid_reasons": invalid_reasons,
        "replay_paths": [rel(evaluation_dir(pair, arm) / f"replay-{index:02d}.json") for index in range(1, required_replays + 1)],
    }


def compute_duel_summaries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for pair in range(1, 4):
        incumbent = arm_summary(pair, "incumbent")
        candidate = arm_summary(pair, "candidate")
        if not incumbent["valid"] or not candidate["valid"]:
            verdict = "invalid_pair"
        elif candidate["score"] > incumbent["score"]:
            verdict = "candidate_win"
        elif incumbent["score"] > candidate["score"]:
            verdict = "incumbent_win"
        else:
            verdict = "tie"
        gap = (
            float(candidate["score"] - incumbent["score"])
            if candidate["score"] is not None and incumbent["score"] is not None
            else None
        )
        pairs.append({"pair": pair, "incumbent": incumbent, "candidate": candidate, "candidate_minus_incumbent": gap, "verdict": verdict})
    incumbent_scores = [row["incumbent"]["score"] for row in pairs]
    candidate_scores = [row["candidate"]["score"] for row in pairs]
    finite_scores = all(value is not None for value in incumbent_scores + candidate_scores)
    incumbent_median = float(statistics.median(incumbent_scores)) if finite_scores else None
    candidate_median = float(statistics.median(candidate_scores)) if finite_scores else None
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
        "candidate_strict_median_win": (
            candidate_median is not None and incumbent_median is not None and candidate_median > incumbent_median
        ),
    }
    return pairs, aggregate


def evaluate() -> None:
    if os.environ.get("CACHE_SCORER_CHESS_GO") != "GO":
        raise base.CampaignError("fresh chess GO is required: set CACHE_SCORER_CHESS_GO=GO")
    seal()
    if EVALUATION_BATCH.is_file():
        print(json.dumps({"phase": "evaluate-r1", "cached": True, "batch_sha256": base.sha256_file(EVALUATION_BATCH)}))
        return
    global_seal = read_json(GLOBAL_SEAL)
    if len(global_seal.get("entries", [])) != 6:
        raise base.CampaignError("R1 global seal is incomplete")
    for entry in global_seal["entries"]:
        require_file_hash(CAMPAIGN_DIR / entry["artifact_path"], entry["artifact_sha256"], entry["label"])
        require_file_hash(CAMPAIGN_DIR / entry["seal_path"], entry["seal_sha256"], f"{entry['label']} seal")
    root_manifest = read_json(WORKSPACE / "source-manifest.json")
    require_file_hash(base.RUNNER_SOURCE, root_manifest["frozen_runner"]["sha256"], "frozen runner")
    runner = base.load_module("_cache_transfer_r1_frozen_evaluator", base.RUNNER_SOURCE)
    traces = runner.generate_trace_suite(R1_CONTRACT["benchmark"]["seed"], R1_CONTRACT["benchmark"]["scale"])
    rows = [
        {
            "name": trace.name,
            "capacity_bytes": trace.capacity_bytes,
            "accesses": [{"now": access.now, "key": access.key, "size": access.size} for access in trace.accesses],
        }
        for trace in traces
    ]
    if len(traces) != R1_CONTRACT["benchmark"]["trace_count"]:
        raise base.CampaignError("frozen R1 trace count changed")
    if base.sha256_bytes(base.canonical_bytes(rows)) != R1_CONTRACT["benchmark"]["fixture_sha256"]:
        raise base.CampaignError("frozen R1 fixture identity changed")
    entry_by_key = {(int(item["pair"]), str(item["arm"])): item for item in global_seal["entries"]}
    with base.HeavyEvaluationLock(base.HEAVY_LOCK):
        for pair in range(1, 4):
            for arm in ("incumbent", "candidate"):
                for replay in (1, 2):
                    run_replay(pair=pair, arm=arm, entry=entry_by_key[(pair, arm)], replay=replay, runner=runner, traces=traces)
        pairs, aggregate = compute_duel_summaries()
        threshold = float(R1_CONTRACT["close_confirmation"]["absolute_threshold"])
        median_close = (
            aggregate["candidate_median"] is not None
            and aggregate["incumbent_median"] is not None
            and abs(aggregate["candidate_median"] - aggregate["incumbent_median"]) <= threshold
        )
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
                    run_replay(pair=pair, arm=arm, entry=entry_by_key[(pair, arm)], replay=3, runner=runner, traces=traces)
    confirmations: list[dict[str, Any]] = []
    if close_triggered:
        for pair in range(1, 4):
            for arm in ("incumbent", "candidate"):
                records = [read_json(evaluation_dir(pair, arm) / f"replay-{index:02d}.json") for index in (1, 2, 3)]
                confirmations.append(
                    {
                        "label": arm_label(pair, arm),
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
        "display_round": 1,
        "completed_at": base.utc_now(),
        "pre_evaluation_seal_path": rel(GLOBAL_SEAL),
        "pre_evaluation_seal_sha256": base.sha256_file(GLOBAL_SEAL),
        "benchmark": expected_benchmark() | {"runner_sha256": base.sha256_file(base.RUNNER_SOURCE)},
        "replay_count": 2,
        "pairs": pairs,
        "aggregate": aggregate,
        "close_threshold": threshold,
        "close_confirmation_triggered": close_triggered,
        "confirmations": confirmations,
        "confirmation_passed": confirmation_passed,
        "promotion_contract_passed": promoted,
    }
    base.write_json_new(EVALUATION_BATCH, batch)
    print(
        json.dumps(
            {
                "phase": "evaluate-r1",
                "candidate_wins": aggregate["candidate_wins"],
                "incumbent_wins": aggregate["incumbent_wins"],
                "incumbent_median": aggregate["incumbent_median"],
                "candidate_median": aggregate["candidate_median"],
                "close_triggered": close_triggered,
                "promoted": promoted,
            }
        )
    )


def usage_totals(receipts: list[dict[str, Any]]) -> dict[str, int]:
    return base.sum_usage(receipts)


def build_token_accounting() -> dict[str, Any]:
    receipt_paths = sorted(
        path
        for path in MODEL_CALLS.rglob("final-receipt.json")
        if read_json(path).get("call_id", "").startswith("R1-")
    )
    receipts = [read_json(path) for path in receipt_paths]
    architect_rows = [row for row in receipts if row["call_id"] == "R1-structural-mutation-architect"]
    inner_rows = [row for row in receipts if row["call_id"].startswith("R1-pair")]
    global_seal = read_json(GLOBAL_SEAL)
    expected_inner = int(global_seal["inner_roles"]["calls"])
    if len(architect_rows) != 1 or len(inner_rows) != expected_inner or len(receipts) != 1 + expected_inner:
        raise base.CampaignError("R1 token accounting call cardinality failed")
    failures: list[dict[str, Any]] = []
    for path in sorted(MODEL_CALLS.rglob("failure-receipt.json")):
        call_root = path
        while call_root.parent != MODEL_CALLS and call_root.parent != call_root:
            call_root = call_root.parent
        if not call_root.name.startswith("R1-"):
            continue
        row = read_json(path)
        row["path"] = rel(path)
        raw_path = path.parent / "raw-events.jsonl"
        row["raw_events_sha256"] = base.sha256_file(raw_path) if raw_path.is_file() else None
        failures.append(row)
    return {
        "schema_version": 1,
        "display_round": 1,
        "rule": {
            "total_tokens": "input_tokens + output_tokens",
            "effective_tokens": "input_tokens - cached_input_tokens + output_tokens",
            "reasoning_output_tokens": "subset of output tokens",
        },
        "architect": usage_totals(architect_rows),
        "topology_inner_roles": usage_totals(inner_rows),
        "round_model_calls": usage_totals(receipts),
        "completed_model_calls": len(receipts),
        "transport_attempts": len(receipts) + len(failures),
        "failed_transport_attempts": len(failures),
        "transport_failures": failures,
        "spend": {
            "billing_mode": "ChatGPT subscription via Codex login",
            "paid_api_spend_usd": 0.0,
            "estimated_api_spend_usd": None,
            "paid_api_used": False,
        },
        "receipt_paths": [
            {"call_id": row["call_id"], "path": rel(path), "sha256": base.sha256_file(path)}
            for path, row in sorted(zip(receipt_paths, receipts), key=lambda item: item[1]["call_id"])
        ],
    }


def choose_candidate_representative(batch: dict[str, Any]) -> dict[str, Any]:
    median = batch["aggregate"]["candidate_median"]
    candidates = [
        row["candidate"] for row in batch["pairs"] if row["candidate"]["valid"] and row["candidate"]["score"] == median
    ]
    if not candidates:
        raise base.CampaignError("candidate median representative is unavailable")
    return min(candidates, key=lambda row: row["artifact_sha256"])


def finalize() -> None:
    if not EVALUATION_BATCH.is_file():
        raise base.CampaignError("R1 evaluate must complete before finalize")
    if DECISION.is_file():
        print(json.dumps({"phase": "finalize-r1", "cached": True, "decision_sha256": base.sha256_file(DECISION)}))
        return
    batch = read_json(EVALUATION_BATCH)
    if batch.get("pre_evaluation_seal_sha256") != base.sha256_file(GLOBAL_SEAL):
        raise base.CampaignError("R1 evaluation batch does not bind the global seal")
    promoted = bool(batch["promotion_contract_passed"])
    if promoted:
        representative = choose_candidate_representative(batch)
        pair = int(representative["pair"])
        source_policy = arm_dir(pair, "candidate") / "artifact" / "policy.py"
        source_structure = PROPOSED_STRUCTURE
        source_seal = arm_dir(pair, "candidate") / "seal.json"
        champion_source = "promoted-candidate"
    else:
        representative = None
        pair = None
        source_policy = R0_POLICY
        source_structure = R0_STRUCTURE
        source_seal = None
        champion_source = "retained-r0"
    base.write_bytes_new(CHAMPION_R1 / "policy.py", source_policy.read_bytes())
    base.write_bytes_new(CHAMPION_R1 / "structure.json", source_structure.read_bytes())
    accounting = build_token_accounting()
    base.write_json_new(TOKEN_ACCOUNTING, accounting)
    selection_receipt = {
        "schema_version": 1,
        "display_round": 1,
        "selected_at": base.utc_now(),
        "promoted": promoted,
        "champion_source": champion_source,
        "representative_pair": pair,
        "artifact_path": rel(CHAMPION_R1 / "policy.py"),
        "artifact_sha256": base.sha256_file(CHAMPION_R1 / "policy.py"),
        "structure_path": rel(CHAMPION_R1 / "structure.json"),
        "structure_sha256": base.sha256_file(CHAMPION_R1 / "structure.json"),
        "source_artifact_path": rel(source_policy),
        "source_artifact_sha256": base.sha256_file(source_policy),
        "source_seal_path": rel(source_seal) if source_seal is not None else None,
        "source_seal_sha256": base.sha256_file(source_seal) if source_seal is not None else None,
        "starting_r0_policy_sha256": EXPECTED_R0_POLICY_SHA,
        "starting_r0_structure_sha256": EXPECTED_R0_STRUCTURE_SHA,
        "evaluation_batch_path": rel(EVALUATION_BATCH),
        "evaluation_batch_sha256": base.sha256_file(EVALUATION_BATCH),
        "promotion_contract": R1_CONTRACT["promotion"],
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
        "cache_r2_opened": False,
    }
    base.write_json_new(CHAMPION_R1 / "selection-receipt.json", selection_receipt)
    decision = {
        "schema_version": 1,
        "display_round": 1,
        "status": "round-complete-stop-required",
        "promoted": promoted,
        "selection_receipt_path": rel(CHAMPION_R1 / "selection-receipt.json"),
        "selection_receipt_sha256": base.sha256_file(CHAMPION_R1 / "selection-receipt.json"),
        "champion_policy_sha256": selection_receipt["artifact_sha256"],
        "champion_structure_sha256": selection_receipt["structure_sha256"],
        "evaluation_batch_sha256": base.sha256_file(EVALUATION_BATCH),
        "token_accounting_sha256": base.sha256_file(TOKEN_ACCOUNTING),
        "cache_r2_opened": False,
        "next_round_permitted": False,
    }
    base.write_json_new(DECISION, decision)
    state = {
        "schema_version": 1,
        "campaign_id": R1_CONTRACT["campaign_id"],
        "display_round": 1,
        "status": "stopped-after-display-r1",
        "round_decision_path": rel(DECISION),
        "round_decision_sha256": base.sha256_file(DECISION),
        "champion_selection_receipt": rel(CHAMPION_R1 / "selection-receipt.json"),
        "champion_artifact_sha256": selection_receipt["artifact_sha256"],
        "champion_structure_sha256": selection_receipt["structure_sha256"],
        "promoted": promoted,
        "cache_r2_opened": False,
        "next_round_permitted": False,
        "git_commit_created": False,
    }
    base.write_json_new(STATE, state)
    print(
        json.dumps(
            {
                "phase": "finalize-r1",
                "promoted": promoted,
                "champion_artifact_sha256": selection_receipt["artifact_sha256"],
                "cache_r2_opened": False,
            }
        )
    )


def audit_invariants() -> list[str]:
    checks: list[str] = []
    require_file_hash(R0_POLICY, EXPECTED_R0_POLICY_SHA, "immutable R0 policy")
    require_file_hash(R0_STRUCTURE, EXPECTED_R0_STRUCTURE_SHA, "immutable R0 structure")
    require_file_hash(R0_SELECTION, EXPECTED_R0_SELECTION_SHA, "immutable R0 selection")
    require_file_hash(R0_ATOMIC, EXPECTED_R0_ATOMIC_SHA, "immutable R0 atomic state")
    checks.append("authoritative-r0-hashes-unchanged")
    seal_value = read_json(GLOBAL_SEAL)
    if len(seal_value["entries"]) != 6 or seal_value["architect"]["calls"] != 1:
        raise base.CampaignError("final audit found incomplete sealed duel")
    checks.append("one-architect-and-six-sealed-arms")
    validate_receipt(MODEL_CALLS / "R1-structural-mutation-architect" / "final-receipt.json", architect_receipt=True)
    for entry in seal_value["entries"]:
        require_file_hash(CAMPAIGN_DIR / entry["artifact_path"], entry["artifact_sha256"], entry["label"])
        require_file_hash(CAMPAIGN_DIR / entry["seal_path"], entry["seal_sha256"], f"{entry['label']} seal")
        for item in read_json(CAMPAIGN_DIR / entry["seal_path"])["model_receipts"]:
            validate_receipt(CAMPAIGN_DIR / item["path"])
    checks.append("strict-sol-luna-model-boundary-and-receipts")
    batch = read_json(EVALUATION_BATCH)
    pairs, aggregate = compute_duel_summaries()
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
            raise base.CampaignError(f"final audit recomputation differs for {key}")
    if [row["verdict"] for row in pairs] != [row["verdict"] for row in batch["pairs"]]:
        raise base.CampaignError("final audit pair verdicts differ")
    checks.append("frozen-replay2-and-promotion-recomputed")
    selection = read_json(CHAMPION_R1 / "selection-receipt.json")
    if selection["promotion_contract_passed"] != batch["promotion_contract_passed"]:
        raise base.CampaignError("selection promotion flag differs from evaluator contract")
    require_file_hash(CHAMPION_R1 / "policy.py", selection["artifact_sha256"], "R1 champion policy")
    require_file_hash(CHAMPION_R1 / "structure.json", selection["structure_sha256"], "R1 champion structure")
    checks.append("champion-policy-and-structure-bound-to-decision")
    state = read_json(STATE)
    if state.get("display_round") != 1 or state.get("cache_r2_opened") is not False or state.get("next_round_permitted") is not False:
        raise base.CampaignError("R1 stop state is invalid")
    if (WORKSPACE / "rounds" / "R2").exists() or (WORKSPACE / "champion-r2").exists():
        raise base.CampaignError("final audit found Cache R2 opened")
    checks.append("stopped-at-r1-with-cache-r2-unopened")
    return checks


def write_reports(test_receipt: dict[str, Any], verification: dict[str, Any]) -> None:
    batch = read_json(EVALUATION_BATCH)
    decision = read_json(DECISION)
    selection = read_json(CHAMPION_R1 / "selection-receipt.json")
    accounting = read_json(TOKEN_ACCOUNTING)
    report = {
        "schema_version": 1,
        "campaign_id": R1_CONTRACT["campaign_id"],
        "display_round": 1,
        "status": "atomic-state-ready-stopped-after-r1",
        "completed_at": base.utc_now(),
        "starting_champion": read_json(SOURCE_MANIFEST)["starting_champion"],
        "architect": {
            "proposal_path": rel(PROPOSAL),
            "proposal_sha256": base.sha256_file(PROPOSAL),
            "mutation": read_json(PROPOSAL)["architect_response"]["mutation"],
            "candidate_structure_path": rel(PROPOSED_STRUCTURE),
            "candidate_structure_sha256": base.sha256_file(PROPOSED_STRUCTURE),
        },
        "benchmark": batch["benchmark"],
        "pairs": batch["pairs"],
        "aggregate": batch["aggregate"],
        "close_confirmation": {
            "threshold": batch["close_threshold"],
            "triggered": batch["close_confirmation_triggered"],
            "confirmations": batch["confirmations"],
            "passed": batch["confirmation_passed"],
        },
        "promotion": {
            "contract_passed": batch["promotion_contract_passed"],
            "decision": decision,
            "selection": selection,
        },
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
        "cache_r2_opened": False,
        "next_round_permitted": False,
    }
    base.write_json_new(REPORT_JSON, report)
    lines = [
        "# Cache Transfer League — display R1",
        "",
        "One score-blind structural mutation was tested in three matched Luna-high pairs against the fixed R20/R0 topology.",
        "",
        "| Pair | Incumbent | Candidate | Delta | Verdict | Valid |",
        "|---:|---:|---:|---:|---|:---:|",
    ]
    for row in batch["pairs"]:
        inc = row["incumbent"]["score"]
        cand = row["candidate"]["score"]
        gap = row["candidate_minus_incumbent"]
        valid = row["incumbent"]["valid"] and row["candidate"]["valid"]
        inc_text = f"{inc:.4f}" if inc is not None else "invalid"
        cand_text = f"{cand:.4f}" if cand is not None else "invalid"
        gap_text = f"{gap:+.4f}" if gap is not None else "n/a"
        lines.append(f"| {row['pair']} | {inc_text} | {cand_text} | {gap_text} | {row['verdict']} | {'yes' if valid else 'no'} |")
    aggregate = batch["aggregate"]
    lines.extend(
        [
            "",
            f"Medians: incumbent `{aggregate['incumbent_median']}`, candidate `{aggregate['candidate_median']}`. Pair wins: candidate `{aggregate['candidate_wins']}`, incumbent `{aggregate['incumbent_wins']}`, ties `{aggregate['ties']}`.",
            "",
            f"Close confirmation threshold `0.25`: triggered `{batch['close_confirmation_triggered']}`, passed `{batch['confirmation_passed']}`.",
            "",
            f"Promotion contract passed: `{batch['promotion_contract_passed']}`. Champion source: `{selection['champion_source']}`; policy `{selection['artifact_sha256']}`; structure `{selection['structure_sha256']}`.",
            "",
            f"Tests: `{test_receipt['passed']}` ({test_receipt['summary']}). Final audit: `{verification['passed']}`.",
            "",
            f"Completed calls: `{accounting['completed_model_calls']}`; effective tokens: `{accounting['round_model_calls']['effective_tokens']}`; paid API spend: `$0.00` (subscription transport).",
            "",
            "Stopped after display R1. Cache R2 was not opened. No Git commit was created.",
            "",
        ]
    )
    base.write_text_new(REPORT_MD, "\n".join(lines))


def verify() -> None:
    if not DECISION.is_file():
        raise base.CampaignError("R1 finalize must complete before verify")
    if ATOMIC_COMMIT.is_file():
        print(json.dumps({"phase": "verify-r1", "cached": True, "atomic_sha256": base.sha256_file(ATOMIC_COMMIT)}))
        return
    started_at = base.utc_now()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(CAMPAIGN_DIR / "test_r1_contract.py")],
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
        "started_at": started_at,
        "finished_at": base.utc_now(),
        "command": [sys.executable, "-m", "pytest", "-q", rel(CAMPAIGN_DIR / "test_r1_contract.py")],
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "summary": (proc.stdout + proc.stderr).strip(),
        "stdout_sha256": base.sha256_bytes(proc.stdout.encode("utf-8")),
        "stderr_sha256": base.sha256_bytes(proc.stderr.encode("utf-8")),
    }
    base.write_json_new(TEST_RECEIPT, test_receipt)
    if proc.returncode != 0:
        raise base.CampaignError(f"R1 contract tests failed: {test_receipt['summary']}")
    checks = audit_invariants()
    verification = {
        "schema_version": 1,
        "verified_at": base.utc_now(),
        "passed": True,
        "checks": checks,
        "test_receipt_path": rel(TEST_RECEIPT),
        "test_receipt_sha256": base.sha256_file(TEST_RECEIPT),
        "r0_unchanged": True,
        "strict_model_split_passed": True,
        "all_six_sealed_before_score": True,
        "frozen_replay2_recomputed": True,
        "cache_r2_opened": False,
        "git_commit_created": False,
    }
    base.write_json_new(VERIFICATION, verification)
    write_reports(test_receipt, verification)
    components = {
        "r1_contract": R1_CONTRACT_PATH,
        "source_manifest": SOURCE_MANIFEST,
        "proposal": PROPOSAL,
        "proposed_structure": PROPOSED_STRUCTURE,
        "hypothesis": HYPOTHESIS,
        "pre_evaluation_seal": GLOBAL_SEAL,
        "evaluation_batch": EVALUATION_BATCH,
        "token_accounting": TOKEN_ACCOUNTING,
        "selection_receipt": CHAMPION_R1 / "selection-receipt.json",
        "champion_policy": CHAMPION_R1 / "policy.py",
        "champion_structure": CHAMPION_R1 / "structure.json",
        "round_decision": DECISION,
        "state": STATE,
        "test_receipt": TEST_RECEIPT,
        "verification_receipt": VERIFICATION,
        "round_report_json": REPORT_JSON,
        "round_report_md": REPORT_MD,
    }
    component_rows = {
        name: {"path": rel(path), "sha256": base.sha256_file(path)} for name, path in components.items()
    }
    marker = {
        "schema_version": 1,
        "campaign_id": R1_CONTRACT["campaign_id"],
        "display_round": 1,
        "status": "atomically-committed-campaign-state-stopped-after-r1",
        "committed_at": base.utc_now(),
        "components": component_rows,
        "aggregate_sha256": base.sha256_bytes(base.canonical_bytes(component_rows)),
        "champion_artifact_sha256": base.sha256_file(CHAMPION_R1 / "policy.py"),
        "champion_structure_sha256": base.sha256_file(CHAMPION_R1 / "structure.json"),
        "promoted": read_json(DECISION)["promoted"],
        "cache_r2_opened": False,
        "next_round_permitted": False,
        "git_commit_created": False,
    }
    # This immutable marker is deliberately the final campaign-state write.
    base.write_json_new(ATOMIC_COMMIT, marker)
    print(
        json.dumps(
            {
                "phase": "verify-r1",
                "tests": test_receipt["summary"],
                "audit_checks": len(checks),
                "atomic_sha256": base.sha256_file(ATOMIC_COMMIT),
                "cache_r2_opened": False,
            }
        )
    )


def run_all_before_evaluation() -> None:
    prepare()
    architect()
    generate()
    seal()


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache Transfer League display R1 matched structure duel")
    parser.add_argument(
        "phase",
        choices=("prepare", "architect", "generate", "seal", "evaluate", "finalize", "verify", "pre-eval", "all"),
    )
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare()
    elif args.phase == "architect":
        architect()
    elif args.phase == "generate":
        generate()
    elif args.phase == "seal":
        seal()
    elif args.phase == "evaluate":
        evaluate()
    elif args.phase == "finalize":
        finalize()
    elif args.phase == "verify":
        verify()
    elif args.phase == "pre-eval":
        run_all_before_evaluation()
    else:
        run_all_before_evaluation()
        evaluate()
        finalize()
        verify()


if __name__ == "__main__":
    main()
