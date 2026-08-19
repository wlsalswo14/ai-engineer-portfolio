#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


CAMPAIGN_DIR = Path(__file__).resolve().parent
ROOT = CAMPAIGN_DIR.parents[1]
WORKSPACE = CAMPAIGN_DIR / "workspace"
CONTRACT_PATH = CAMPAIGN_DIR / "campaign-contract.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
ARCHIVE = Path(CONTRACT["benchmark"]["authority_root"])
TASK_SOURCE = (
    ARCHIVE
    / "research"
    / "agentloop-harness-research"
    / "benchmark_tasks_v3"
    / "fast"
    / "cache-policy"
    / "TASK.md"
)
RUNNER_SOURCE = ARCHIVE / "benchmarks" / "runners" / "cache_policy_loop.py"
FIELD_SOURCE = (
    ARCHIVE / "research" / "agentloop-harness-research" / "benchmark_fields_v3.json"
)
SEMANTIC_SOURCE = (
    ARCHIVE
    / "research"
    / "agentloop-harness-research"
    / "scripts"
    / "benchmark_semantic_fixes_v3.py"
)
HISTORY_ROOT = ROOT / "experiments" / "chess-tier5-clean" / "workspace" / "rounds"
SOURCE_ROUNDS = ((20, "r0001"), (24, "r0005"), (26, "r0007"), (30, "r0011"))
HOME_POOL = (
    Path(r"C:\Users\jinminjae\.codex-wlsalswo14\wlsalswo14"),
    Path(r"C:\Users\jinminjae\.codex-bteamjin14"),
    Path(r"C:\Users\jinminjae\.codex"),
)
MODEL_CALLS = WORKSPACE / "model-calls"
SOURCE_SNAPSHOTS = WORKSPACE / "source-snapshots"
TRANSLATIONS = WORKSPACE / "translated-structures"
BOOTSTRAP = WORKSPACE / "bootstrap"
ANCHOR = WORKSPACE / "anchor"
EVALUATION = WORKSPACE / "evaluation"
HEAVY_LOCK = ROOT / CONTRACT["coordination"]["heavy_lock"].replace("/", os.sep)
EXPECTED_TASK_SHA256 = "6cdc13ad7f94046b8302190bcb4d82ed30a1279d4c1cb7975360d98002fe88bb"

EXTERNAL_INPUT_MAP = {
    "task": "task",
    "champion_engine": "anchor_policy",
    "champion_metrics": "anchor_contract",
    "state_capsule": "task_constraints",
    "candidate_hypothesis": "candidate_hypothesis",
    "loop_structure": "loop_structure",
}


class CampaignError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_bytes_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise CampaignError(f"immutable file differs: {path}")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise


def write_text_new(path: Path, text: str) -> None:
    write_bytes_new(path, text.encode("utf-8"))


def write_json_new(path: Path, value: Any) -> None:
    write_text_new(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CampaignError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_plan_path(internal_round: str) -> Path:
    return HISTORY_ROOT / internal_round / "generation" / "normalized-plan.json"


def prepare() -> None:
    if WORKSPACE.exists() and not (WORKSPACE / "source-manifest.json").exists():
        unexpected = [path for path in WORKSPACE.iterdir() if path.name != "source-snapshots"]
        if unexpected:
            raise CampaignError("workspace exists without a source manifest; refusing ambiguous reuse")
    for required in (TASK_SOURCE, RUNNER_SOURCE, FIELD_SOURCE, SEMANTIC_SOURCE):
        if not required.is_file():
            raise CampaignError(f"authoritative source missing: {required}")
    if sha256_file(TASK_SOURCE) != EXPECTED_TASK_SHA256:
        raise CampaignError("authoritative task hash mismatch")

    fields = json.loads(FIELD_SOURCE.read_text(encoding="utf-8"))
    field = fields["fields"][CONTRACT["benchmark"]["field"]]
    fixture = field["fixture"]
    for key in ("seed", "scale", "case_count", "canonical_sha256"):
        contract_key = "trace_count" if key == "case_count" else "fixture_sha256" if key == "canonical_sha256" else key
        if fixture[key] != CONTRACT["benchmark"][contract_key]:
            raise CampaignError(f"benchmark contract mismatch for {key}")

    runner = load_module("_cache_transfer_authority_prepare", RUNNER_SOURCE)
    traces = runner.generate_trace_suite(
        CONTRACT["benchmark"]["seed"], CONTRACT["benchmark"]["scale"]
    )
    rows = [
        {
            "name": trace.name,
            "capacity_bytes": trace.capacity_bytes,
            "accesses": [
                {"now": access.now, "key": access.key, "size": access.size}
                for access in trace.accesses
            ],
        }
        for trace in traces
    ]
    fixture_sha = sha256_bytes(canonical_bytes(rows))
    if len(traces) != CONTRACT["benchmark"]["trace_count"]:
        raise CampaignError("frozen trace count mismatch")
    if fixture_sha != CONTRACT["benchmark"]["fixture_sha256"]:
        raise CampaignError("frozen fixture hash mismatch")

    structures: list[dict[str, Any]] = []
    for display_round, internal_round in SOURCE_ROUNDS:
        plan_path = source_plan_path(internal_round)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        structure = plan["structure"]
        structure_path = SOURCE_SNAPSHOTS / f"R{display_round}-structure.json"
        write_json_new(structure_path, structure)
        structures.append(
            {
                "display_source_round": display_round,
                "internal_source_round": internal_round,
                "authoritative_path": str(plan_path),
                "authoritative_file_sha256": sha256_file(plan_path),
                "structure_id": plan["structure_id"],
                "structure_snapshot": str(structure_path.relative_to(CAMPAIGN_DIR)),
                "structure_sha256": sha256_bytes(canonical_bytes(structure)),
                "stage_count": len(structure["stages"]),
                "call_count": sum(len(stage["calls"]) for stage in structure["stages"]),
            }
        )

    write_bytes_new(SOURCE_SNAPSHOTS / "TASK.md", TASK_SOURCE.read_bytes())
    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "clean_lineage": True,
        "task": {
            "path": str(TASK_SOURCE),
            "sha256": sha256_file(TASK_SOURCE),
            "snapshot": str((SOURCE_SNAPSHOTS / "TASK.md").relative_to(CAMPAIGN_DIR)),
        },
        "frozen_runner": {"path": str(RUNNER_SOURCE), "sha256": sha256_file(RUNNER_SOURCE)},
        "field_contract": {"path": str(FIELD_SOURCE), "sha256": sha256_file(FIELD_SOURCE)},
        "semantic_adapter": {"path": str(SEMANTIC_SOURCE), "sha256": sha256_file(SEMANTIC_SOURCE)},
        "fixture": {
            "seed": CONTRACT["benchmark"]["seed"],
            "scale": CONTRACT["benchmark"]["scale"],
            "trace_count": len(traces),
            "canonical_sha256": fixture_sha,
            "fixture_payload_persisted": False,
        },
        "historical_structures": structures,
        "prohibited_cache_history_read": True,
        "recycle_bin_read": False,
    }
    write_json_new(WORKSPACE / "source-manifest.json", manifest)
    print(json.dumps({"phase": "prepare", "fixture_sha256": fixture_sha, "structures": 4}))


def codex_launcher() -> list[str]:
    wrapper = shutil.which("codex.cmd") or shutil.which("codex")
    node = shutil.which("node")
    if not wrapper or not node:
        raise CampaignError("Codex subscription launcher prerequisites are missing")
    script = Path(wrapper).resolve().parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    if not script.is_file():
        raise CampaignError(f"Codex JavaScript launcher missing: {script}")
    return [node, str(script)]


def parse_codex_jsonl(payload: str) -> tuple[str, dict[str, int], list[str], list[dict[str, Any]]]:
    messages: list[str] = []
    item_types: list[str] = []
    events: list[dict[str, Any]] = []
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    for raw in payload.splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        events.append(event)
        event_type = str(event.get("type", ""))
        if event_type == "item.completed":
            item = event.get("item", {})
            item_type = str(item.get("type", ""))
            item_types.append(item_type)
            if item_type == "agent_message" and item.get("text"):
                messages.append(str(item["text"]))
        elif event_type == "turn.completed":
            raw_usage = event.get("usage", {})
            for key in usage:
                usage[key] = int(raw_usage.get(key, 0))
        elif event_type in {"turn.failed", "error"}:
            raise CampaignError(str(event.get("message") or event.get("error") or "Codex call failed"))
    if not messages:
        raise CampaignError("Codex call completed without an agent message")
    return messages[-1], usage, item_types, events


def inspect_codex_jsonl_transport(payload: str) -> tuple[dict[str, int], list[str], int]:
    """Recover usage and transport errors without accepting a failed stream output."""
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    errors: list[str] = []
    malformed_lines = 0
    for raw in payload.splitlines():
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            malformed_lines += 1
            continue
        event_type = str(event.get("type", ""))
        if event_type == "turn.completed":
            raw_usage = event.get("usage", {})
            for key in usage:
                usage[key] = int(raw_usage.get(key, 0))
        elif event_type in {"turn.failed", "error"}:
            errors.append(str(event.get("message") or event.get("error") or "Codex call failed"))
    return usage, errors, malformed_lines


def transport_failure_receipt(
    *,
    call_id: str,
    model: str,
    effort: str,
    service_tier: str | None,
    home_slot: int,
    requested_home_slot: int,
    prompt_sha256: str,
    raw_events: str,
    stderr: str,
    failure_stage: str,
    error_message: str,
    started_at: str | None,
    finished_at: str,
    duration_seconds: float | None,
    returncode: int,
    recovered_after_runner_exit: bool,
) -> dict[str, Any]:
    usage, stream_errors, malformed_lines = inspect_codex_jsonl_transport(raw_events)
    return {
        "schema_version": 2,
        "call_id": call_id,
        "model": model,
        "reasoning_effort": effort,
        "service_tier": service_tier or "default",
        "request_tier": "priority" if service_tier == "fast" else "default",
        "home_slot": home_slot,
        "requested_home_slot": requested_home_slot,
        "failure_kind": "transport",
        "failure_stage": failure_stage,
        "error_message": error_message,
        "error_message_sha256": sha256_bytes(error_message.encode("utf-8")),
        "stream_error_messages": stream_errors,
        "malformed_jsonl_lines": malformed_lines,
        "prompt_sha256": prompt_sha256,
        "usage": usage,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
        "returncode": returncode,
        "raw_events_sha256": sha256_bytes(raw_events.encode("utf-8")),
        "stderr_sha256": sha256_bytes(stderr.encode("utf-8")),
        "recovered_after_runner_exit": recovered_after_runner_exit,
        "selection_eligibility": False,
    }


def write_transport_resume_manifest(
    *,
    call_id: str,
    call_dir: Path,
    prompt_sha256: str,
    model: str,
    effort: str,
    service_tier: str | None,
    home_slot: int,
) -> Path:
    prior_failure = call_dir / "failure-receipt.json"
    raw_path = call_dir / "raw-events.jsonl"
    manifest_path = call_dir / "transport-resume-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("call_id") != call_id
            or manifest.get("prompt_sha256") != prompt_sha256
            or manifest.get("attempt_01", {}).get("failure_receipt_sha256") != sha256_file(prior_failure)
            or manifest.get("attempt_01", {}).get("raw_events_sha256") != sha256_file(raw_path)
        ):
            raise CampaignError(f"transport resume manifest differs for {call_id}")
        return manifest_path

    round_prefix = call_id.split("-", 1)[0]
    completed: list[dict[str, Any]] = []
    for completed_dir in sorted(MODEL_CALLS.glob(f"{round_prefix}-*")):
        receipt_path = completed_dir / "final-receipt.json"
        result_path = completed_dir / "result.json"
        if completed_dir == call_dir or not (receipt_path.is_file() and result_path.is_file()):
            continue
        completed.append(
            {
                "call_id": completed_dir.name,
                "receipt_path": str(receipt_path.relative_to(CAMPAIGN_DIR)),
                "receipt_sha256": sha256_file(receipt_path),
                "result_path": str(result_path.relative_to(CAMPAIGN_DIR)),
                "result_sha256": sha256_file(result_path),
            }
        )
    failure = json.loads(prior_failure.read_text(encoding="utf-8"))
    if (
        failure.get("call_id") != call_id
        or failure.get("failure_kind") != "transport"
        or failure.get("prompt_sha256") != prompt_sha256
        or int(failure.get("home_slot", -1)) != home_slot
    ):
        raise CampaignError(f"transport failure is not eligible for same-prompt resume: {call_id}")
    manifest = {
        "schema_version": 1,
        "status": "authorized-bounded-same-prompt-transport-resume",
        "call_id": call_id,
        "same_call_id": True,
        "same_prompt": True,
        "prompt_sha256": prompt_sha256,
        "model": model,
        "reasoning_effort": effort,
        "service_tier": service_tier or "default",
        "request_tier": "priority" if service_tier == "fast" else "default",
        "home_slot": home_slot,
        "bounded_max_attempts": 2,
        "retry_attempt": 2,
        "retry_directory": str((call_dir / "retry-02").relative_to(CAMPAIGN_DIR)),
        "semantic_failure": False,
        "direct_substitution": False,
        "best_of_n": False,
        "attempt_01": {
            "raw_events_path": str(raw_path.relative_to(CAMPAIGN_DIR)),
            "raw_events_sha256": sha256_file(raw_path),
            "failure_receipt_path": str(prior_failure.relative_to(CAMPAIGN_DIR)),
            "failure_receipt_sha256": sha256_file(prior_failure),
            "usage": failure.get("usage", {}),
        },
        "completed_calls_reused_without_reexecution": completed,
        "created_at": utc_now(),
    }
    write_json_new(manifest_path, manifest)
    return manifest_path


def parse_json_response(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start < 0:
            raise CampaignError("model response did not contain a JSON object")
        try:
            value, _ = json.JSONDecoder().raw_decode(stripped[start:])
        except json.JSONDecodeError as exc:
            raise CampaignError("model response JSON could not be parsed") from exc
        return value


def run_codex(
    *,
    call_id: str,
    role: str,
    prompt: str,
    model: str,
    effort: str,
    home_slot: int,
    service_tier: str | None,
    timeout_seconds: int,
) -> tuple[Any, dict[str, Any]]:
    call_dir = MODEL_CALLS / call_id
    result_path = call_dir / "result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        return result["parsed_response"], result["receipt"]
    requested_home_slot = home_slot
    if not 0 <= requested_home_slot < len(HOME_POOL):
        raise CampaignError(f"invalid home slot: {home_slot}")
    unavailable_slots: set[int] = set()
    for failure_path in MODEL_CALLS.rglob("failure-receipt.json"):
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        raw_path = failure_path.parent / "raw-events.jsonl"
        raw = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.is_file() else ""
        if "usage limit" in raw.casefold() or "quota" in raw.casefold():
            unavailable_slots.add(int(failure["home_slot"]))
    available_slots = [
        (requested_home_slot + offset) % len(HOME_POOL)
        for offset in range(len(HOME_POOL))
        if (requested_home_slot + offset) % len(HOME_POOL) not in unavailable_slots
    ]
    if not available_slots:
        raise CampaignError("all subscription homes are unavailable")
    home_slot = available_slots[0]
    home = HOME_POOL[home_slot]
    if not (home / "auth.json").is_file():
        raise CampaignError(f"subscription home {home_slot} has no auth.json")
    actor_dir = WORKSPACE / "actors" / call_id
    actor_dir.mkdir(parents=True, exist_ok=True)
    write_text_new(
        actor_dir / "BOUNDARY.txt",
        "This isolated actor directory intentionally contains no benchmark fixtures, scores, prior Cache artifacts, or prior Cache notes.\n",
    )
    instruction = f"Role: {role}\n\n{prompt}"
    write_text_new(call_dir / "prompt.txt", instruction)
    prior_failure = call_dir / "failure-receipt.json"
    original_raw_path = call_dir / "raw-events.jsonl"
    original_stderr_path = call_dir / "stderr.txt"
    if not prior_failure.is_file() and original_raw_path.is_file() and original_stderr_path.is_file():
        raw_events = original_raw_path.read_text(encoding="utf-8", errors="replace")
        stderr = original_stderr_path.read_text(encoding="utf-8", errors="replace")
        _, stream_errors, malformed_lines = inspect_codex_jsonl_transport(raw_events)
        if not stream_errors and malformed_lines == 0:
            raise CampaignError(f"orphaned call output has no transport-failure evidence: {call_id}")
        error_message = stream_errors[-1] if stream_errors else "malformed JSONL transport stream"
        finished = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(original_raw_path.stat().st_mtime))
        failure = transport_failure_receipt(
            call_id=call_id,
            model=model,
            effort=effort,
            service_tier=service_tier,
            home_slot=home_slot,
            requested_home_slot=requested_home_slot,
            prompt_sha256=sha256_bytes(instruction.encode("utf-8")),
            raw_events=raw_events,
            stderr=stderr,
            failure_stage="jsonl_stream",
            error_message=error_message,
            started_at=None,
            finished_at=finished,
            duration_seconds=None,
            returncode=0,
            recovered_after_runner_exit=True,
        )
        write_json_new(prior_failure, failure)
    if prior_failure.is_file():
        retry_dir = call_dir / "retry-02"
        if (retry_dir / "failure-receipt.json").is_file():
            raise CampaignError(f"bounded transport retry already failed for {call_id}")
        write_transport_resume_manifest(
            call_id=call_id,
            call_dir=call_dir,
            prompt_sha256=sha256_bytes(instruction.encode("utf-8")),
            model=model,
            effort=effort,
            service_tier=service_tier,
            home_slot=home_slot,
        )
        attempt_dir = retry_dir
    else:
        attempt_dir = call_dir

    command = [
        *codex_launcher(),
        "--config",
        'web_search="disabled"',
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--model",
        model,
        "--config",
        f'model_reasoning_effort="{effort}"',
        "--config",
        "agents.enabled=false",
        "--sandbox",
        "read-only",
        "--cd",
        str(actor_dir),
    ]
    if service_tier:
        command.extend(["--config", f'service_tier="{service_tier}"'])
    command.append("-")
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(home)
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("CODEX_API_KEY", None)
    started_at = utc_now()
    started = time.monotonic()
    proc = subprocess.run(
        command,
        input=instruction,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
        env=environment,
        check=False,
    )
    duration = time.monotonic() - started
    write_text_new(attempt_dir / "raw-events.jsonl", proc.stdout)
    write_text_new(attempt_dir / "stderr.txt", proc.stderr)
    if proc.returncode != 0:
        failure = transport_failure_receipt(
            call_id=call_id,
            model=model,
            effort=effort,
            service_tier=service_tier,
            home_slot=home_slot,
            requested_home_slot=requested_home_slot,
            prompt_sha256=sha256_bytes(instruction.encode("utf-8")),
            raw_events=proc.stdout,
            stderr=proc.stderr,
            failure_stage="process_exit",
            error_message=proc.stderr[-1000:] or f"Codex exited {proc.returncode}",
            started_at=started_at,
            finished_at=utc_now(),
            duration_seconds=duration,
            returncode=proc.returncode,
            recovered_after_runner_exit=False,
        )
        write_json_new(attempt_dir / "failure-receipt.json", failure)
        raise CampaignError(f"Codex call {call_id} failed: {proc.stderr[-1000:]}")
    try:
        response, usage, item_types, _ = parse_codex_jsonl(proc.stdout)
    except (CampaignError, json.JSONDecodeError) as exc:
        failure = transport_failure_receipt(
            call_id=call_id,
            model=model,
            effort=effort,
            service_tier=service_tier,
            home_slot=home_slot,
            requested_home_slot=requested_home_slot,
            prompt_sha256=sha256_bytes(instruction.encode("utf-8")),
            raw_events=proc.stdout,
            stderr=proc.stderr,
            failure_stage="jsonl_stream",
            error_message=str(exc),
            started_at=started_at,
            finished_at=utc_now(),
            duration_seconds=duration,
            returncode=proc.returncode,
            recovered_after_runner_exit=False,
        )
        write_json_new(attempt_dir / "failure-receipt.json", failure)
        raise CampaignError(f"Codex call {call_id} transport stream failed: {exc}") from exc
    forbidden_tool_items = sorted(
        set(item_types)
        & {"command_execution", "file_change", "mcp_tool_call", "web_search", "computer_action"}
    )
    if forbidden_tool_items:
        raise CampaignError(f"isolated score-blind call used forbidden tools: {forbidden_tool_items}")
    parsed = parse_json_response(response)
    write_text_new(call_dir / "response.txt", response)
    write_json_new(call_dir / "parsed-response.json", parsed)
    receipt = {
        "schema_version": 1,
        "call_id": call_id,
        "role": role,
        "model": model,
        "reasoning_effort": effort,
        "service_tier": service_tier or "default",
        "request_tier": "priority" if service_tier == "fast" else "default",
        "home_slot": home_slot,
        "requested_home_slot": requested_home_slot,
        "home_identity_sha256": sha256_bytes(str(home).encode("utf-8")),
        "sandbox": "read-only",
        "ephemeral": True,
        "ignore_user_config": True,
        "web_search": False,
        "tools_used": forbidden_tool_items,
        "item_types": item_types,
        "prompt_sha256": sha256_bytes(instruction.encode("utf-8")),
        "response_sha256": sha256_bytes(response.encode("utf-8")),
        "raw_events_sha256": sha256_bytes(proc.stdout.encode("utf-8")),
        "raw_events_path": str((attempt_dir / "raw-events.jsonl").relative_to(CAMPAIGN_DIR)),
        "transport_retry": prior_failure.is_file(),
        "prior_transport_failure_receipt": (
            str(prior_failure.relative_to(CAMPAIGN_DIR)) if prior_failure.is_file() else None
        ),
        "transport_resume_manifest": (
            str((call_dir / "transport-resume-manifest.json").relative_to(CAMPAIGN_DIR))
            if prior_failure.is_file()
            else None
        ),
        "usage": usage,
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": round(duration, 3),
        "returncode": proc.returncode,
    }
    write_json_new(call_dir / "final-receipt.json", receipt)
    result = {"schema_version": 1, "parsed_response": parsed, "receipt": receipt}
    write_json_new(result_path, result)
    return parsed, receipt


def flattened_calls(structure: dict[str, Any]) -> list[dict[str, Any]]:
    return [call for stage in structure["stages"] for call in stage["calls"]]


def translation_prompt(sources: list[dict[str, Any]], task_text: str) -> str:
    return f"""
You are the STRUCTURE ARCHITECT for a score-blind bootstrap. You may output only
roles, topology language, visibility, and a qualitative hypothesis. You must
never output Python, pseudocode, a policy implementation, an algorithm listing,
or final policy code. Do not use tools or inspect the filesystem; everything you
may use is inline below.

Translate exactly four historical loop STRUCTURES from chess vocabulary to the
Cache Policy task. This is vocabulary translation only, not a new proposal.
For every structure preserve exactly:

- organization;
- number and order of stages;
- every stage's sequential/parallel mode;
- number and order of calls in every stage;
- dependency graph and visibility arity;
- output-kind pattern, translating `engine` to `policy` and retaining `analysis`;
- the final-call position.

Translate external input names with this exact table and no alternatives:
`task -> task`, `champion_engine -> anchor_policy`,
`champion_metrics -> anchor_contract`, `state_capsule -> task_constraints`,
`candidate_hypothesis -> candidate_hypothesis`, and
`loop_structure -> loop_structure`. Translate a dependency on an earlier call
to that translated call's exact new id. Input list order and length must remain
unchanged.

Do not mention chess, UCI, engines, Elo, benchmark traces, fixture metadata,
official scores, or historical outcomes in any translated field. Do not change
model or evaluation policy. Do not create variants. Keep each objective concise
but operational for a Luna-high executor. A policy-producing call must request
one complete policy artifact; an analysis call must request evidence only and
must not author policy code.

Return one strict JSON object and no prose:
{{
  "architect_scope": "fixed-topology-domain-translation-only",
  "translations": [
    {{
      "display_source_round": 20,
      "hypothesis": {{
        "observed_bottleneck": "qualitative, score-free text",
        "causal_change": "qualitative, score-free text",
        "expected_effect": "qualitative, score-free text",
        "falsifier": "all-valid and median promotion contract, without a score"
      }},
      "structure": {{
        "name": "...",
        "organization": "...",
        "information_flow": "...",
        "stages": [
          {{"id": "...", "mode": "sequential", "calls": [
            {{"id": "...", "role": "...", "objective": "...", "inputs": ["..."], "output_type": "policy"}}
          ]}}
        ],
        "final_call_id": "..."
      }},
      "translation_audit": {{
        "topology_changed": false,
        "dependency_graph_changed": false,
        "visibility_arity_changed": false,
        "policy_code_emitted": false
      }}
    }}
  ]
}}

Cache Policy task contract:
---
{task_text}
---

Authoritative source structures (structure fields only; no outcomes or scores):
{json.dumps(sources, indent=2, ensure_ascii=False)}
""".strip()


def validate_translation(
    display_round: int, source: dict[str, Any], translated: dict[str, Any]
) -> dict[str, Any]:
    errors: list[str] = []
    target = translated.get("structure")
    if not isinstance(target, dict):
        raise CampaignError(f"R{display_round} translation has no structure object")
    if target.get("organization") != source.get("organization"):
        errors.append("organization changed")
    source_stages = source.get("stages", [])
    target_stages = target.get("stages", [])
    if len(target_stages) != len(source_stages):
        errors.append("stage count changed")
    source_calls = flattened_calls(source)
    target_calls = flattened_calls(target) if len(target_stages) == len(source_stages) else []
    if len(target_calls) != len(source_calls):
        errors.append("call count changed")
    source_to_target: dict[str, str] = {}
    if len(target_calls) == len(source_calls):
        for source_call, target_call in zip(source_calls, target_calls, strict=True):
            source_to_target[str(source_call["id"])] = str(target_call.get("id", ""))
        for stage_index, (source_stage, target_stage) in enumerate(
            zip(source_stages, target_stages, strict=True), start=1
        ):
            if target_stage.get("mode") != source_stage.get("mode"):
                errors.append(f"stage {stage_index} mode changed")
            if len(target_stage.get("calls", [])) != len(source_stage.get("calls", [])):
                errors.append(f"stage {stage_index} call count changed")
        for call_index, (source_call, target_call) in enumerate(
            zip(source_calls, target_calls, strict=True), start=1
        ):
            expected_output = "policy" if source_call["output_type"] == "engine" else source_call["output_type"]
            if target_call.get("output_type") != expected_output:
                errors.append(f"call {call_index} output kind changed")
            source_inputs = source_call.get("inputs", [])
            target_inputs = target_call.get("inputs", [])
            if len(target_inputs) != len(source_inputs):
                errors.append(f"call {call_index} visibility arity changed")
                continue
            expected_inputs = [
                source_to_target[item] if item in source_to_target else EXTERNAL_INPUT_MAP.get(item, f"<unmapped:{item}>")
                for item in source_inputs
            ]
            if target_inputs != expected_inputs:
                errors.append(
                    f"call {call_index} visibility/dependencies changed: expected {expected_inputs}, got {target_inputs}"
                )
        expected_final = source_to_target.get(str(source.get("final_call_id")))
        if target.get("final_call_id") != expected_final:
            errors.append("final-call position changed")
    serialized = json.dumps(translated, sort_keys=True, ensure_ascii=False).casefold()
    forbidden_vocabulary = ("chess", "uci", "elo", "engine", "stockfish")
    for word in forbidden_vocabulary:
        if re.search(rf"\b{re.escape(word)}\b", serialized):
            errors.append(f"untranslated domain vocabulary: {word}")
    for marker in ("class policy", "def access", "```python", "import "):
        if marker in serialized:
            errors.append(f"architect emitted code marker: {marker}")
    audit = translated.get("translation_audit", {})
    for key in (
        "topology_changed",
        "dependency_graph_changed",
        "visibility_arity_changed",
        "policy_code_emitted",
    ):
        if audit.get(key) is not False:
            errors.append(f"translation audit did not certify {key}=false")
    return {
        "display_source_round": display_round,
        "valid": not errors,
        "errors": errors,
        "source_stage_count": len(source_stages),
        "translated_stage_count": len(target_stages),
        "source_call_count": len(source_calls),
        "translated_call_count": len(target_calls),
        "source_dependency_graph": [
            [source_calls.index(next(c for c in source_calls if c["id"] == item)) for item in call.get("inputs", []) if item in {c["id"] for c in source_calls}]
            for call in source_calls
        ],
        "translated_dependency_graph": [
            [target_calls.index(next(c for c in target_calls if c["id"] == item)) for item in call.get("inputs", []) if item in {c["id"] for c in target_calls}]
            for call in target_calls
        ] if target_calls else [],
    }


def translate() -> None:
    manifest_path = WORKSPACE / "source-manifest.json"
    if not manifest_path.is_file():
        raise CampaignError("prepare must complete before translate")
    sources: list[dict[str, Any]] = []
    source_by_round: dict[int, dict[str, Any]] = {}
    for display_round, _ in SOURCE_ROUNDS:
        source = json.loads((SOURCE_SNAPSHOTS / f"R{display_round}-structure.json").read_text(encoding="utf-8"))
        source_by_round[display_round] = source
        sources.append({"display_source_round": display_round, "structure": source})
    task_text = (SOURCE_SNAPSHOTS / "TASK.md").read_text(encoding="utf-8")
    parsed, receipt = run_codex(
        call_id="bootstrap-fixed-topology-translation",
        role="score-blind fixed-topology Cache domain translator and contract architect",
        prompt=translation_prompt(sources, task_text),
        model="gpt-5.6-sol",
        effort="max",
        home_slot=0,
        service_tier="fast",
        timeout_seconds=1800,
    )
    if not isinstance(parsed, dict) or parsed.get("architect_scope") != "fixed-topology-domain-translation-only":
        raise CampaignError("architect response has the wrong scope")
    translations = parsed.get("translations")
    if not isinstance(translations, list) or len(translations) != 4:
        raise CampaignError("architect must return exactly four translations")
    by_round = {int(item.get("display_source_round", -1)): item for item in translations if isinstance(item, dict)}
    if set(by_round) != {20, 24, 26, 30}:
        raise CampaignError("architect translation round set is invalid")
    audits: list[dict[str, Any]] = []
    for display_round, _ in SOURCE_ROUNDS:
        translated = by_round[display_round]
        audit = validate_translation(display_round, source_by_round[display_round], translated)
        audits.append(audit)
        if not audit["valid"]:
            raise CampaignError(f"R{display_round} translation invalid: {audit['errors']}")
        payload = {
            "schema_version": 1,
            "display_source_round": display_round,
            "source_structure_sha256": sha256_bytes(canonical_bytes(source_by_round[display_round])),
            "architect_receipt_sha256": sha256_file(MODEL_CALLS / "bootstrap-fixed-topology-translation" / "final-receipt.json"),
            "hypothesis": translated["hypothesis"],
            "structure": translated["structure"],
            "translation_audit": audit,
        }
        write_json_new(TRANSLATIONS / f"R{display_round}.json", payload)
    seal_entries = [
        {
            "display_source_round": display_round,
            "path": str((TRANSLATIONS / f"R{display_round}.json").relative_to(CAMPAIGN_DIR)),
            "sha256": sha256_file(TRANSLATIONS / f"R{display_round}.json"),
        }
        for display_round, _ in SOURCE_ROUNDS
    ]
    write_json_new(
        WORKSPACE / "translation-seal.json",
        {
            "schema_version": 1,
            "sealed_at": utc_now(),
            "architect_model": receipt["model"],
            "architect_reasoning_effort": receipt["reasoning_effort"],
            "architect_service_tier": receipt["service_tier"],
            "architect_request_tier": receipt["request_tier"],
            "policy_code_emitted": False,
            "entries": seal_entries,
            "aggregate_sha256": sha256_bytes(canonical_bytes(seal_entries)),
        },
    )
    print(json.dumps({"phase": "translate", "structures": 4, "architect_tokens": receipt["usage"]}))


def anchor_prompt(task_text: str) -> str:
    return f"""
Create the campaign's one fresh mechanical LRU anchor policy. This is a baseline,
not an optimized candidate. Use only the Python standard library and implement
the exact task interface. The policy must maintain only information visible from
past and current accesses, return only unique currently cached integer keys, be
deterministic, ignore oversize objects without evicting, update recency on hits,
and evict least-recently-used objects until a fitting miss can be admitted.

Do not use tools, read files, inspect benchmarks, mention fixtures, generate
variants, or optimize beyond ordinary byte-capacity LRU. Return one strict JSON
object and no prose: {{"policy_source": "the complete contents of policy.py",
"artifact_kind": "fresh_mechanical_lru_anchor"}}.

Task contract:
---
{task_text}
---
""".strip()


def strip_source_fence(source: str) -> str:
    stripped = source.strip()
    if stripped.startswith("```python") or stripped.startswith("```py") or stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped + "\n"


def extract_policy_source(parsed: Any, *, call_id: str) -> str:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("policy_source"), str):
        raise CampaignError(f"{call_id} did not return policy_source")
    source = strip_source_fence(parsed["policy_source"])
    if len(source.encode("utf-8")) > 128_000:
        raise CampaignError(f"{call_id} returned an oversized policy")
    return source


def generate_anchor(task_text: str) -> tuple[str, dict[str, Any]]:
    parsed, receipt = run_codex(
        call_id="fresh-lru-anchor",
        role="fresh mechanical LRU anchor policy constructor",
        prompt=anchor_prompt(task_text),
        model="gpt-5.6-luna",
        effort="high",
        home_slot=0,
        service_tier=None,
        timeout_seconds=900,
    )
    if parsed.get("artifact_kind") != "fresh_mechanical_lru_anchor":
        raise CampaignError("anchor response did not certify the requested artifact kind")
    source = extract_policy_source(parsed, call_id="fresh-lru-anchor")
    artifact_path = ANCHOR / "artifact" / "policy.py"
    write_text_new(artifact_path, source)
    write_json_new(
        ANCHOR / "generation-manifest.json",
        {
            "schema_version": 1,
            "artifact_kind": "fresh_mechanical_lru_anchor",
            "artifact_path": str(artifact_path.relative_to(CAMPAIGN_DIR)),
            "artifact_sha256": sha256_file(artifact_path),
            "model_receipt": str((MODEL_CALLS / "fresh-lru-anchor" / "final-receipt.json").relative_to(CAMPAIGN_DIR)),
            "model": receipt["model"],
            "reasoning_effort": receipt["reasoning_effort"],
            "official_scores_visible": False,
            "benchmark_fixtures_visible": False,
        },
    )
    return source, receipt


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
            "artifact_kind": "fresh mechanical byte-capacity LRU anchor",
            "artifact_sha256": anchor_sha256,
            "score_information": "withheld",
            "required_comparison": "preserve interface legality and online-only access visibility",
        }
    if name == "task_constraints":
        return {
            "standard_library_only": True,
            "online_one_access_at_a_time": True,
            "must_return_only_currently_cached_unique_integer_keys": True,
            "must_never_exceed_capacity": True,
            "no_benchmark_paths_or_trace_hardcoding": True,
            "no_scores_available": True,
        }
    if name == "candidate_hypothesis":
        return hypothesis
    if name == "loop_structure":
        return structure
    if name in prior_outputs:
        return prior_outputs[name]
    raise CampaignError(f"unresolvable visible input: {name}")


def role_prompt(
    *,
    display_round: int,
    representative: int,
    call: dict[str, Any],
    visible_inputs: dict[str, Any],
) -> str:
    output_type = call["output_type"]
    if output_type == "policy":
        output_contract = """
Return one strict JSON object and no prose:
{"policy_source":"complete contents of policy.py","artifact_kind":"single_policy"}
The source must be complete, deterministic, online-only, standard-library-only,
and must define class Policy with __init__(capacity_bytes) and
access(key, size, now). Do not return a diff, multiple variants, benchmark data,
or evaluator-specific constants. You may reason internally, but return exactly
one artifact.
""".strip()
    elif output_type == "analysis":
        output_contract = """
Return one strict JSON object and no prose:
{"analysis_packet":{"certificate":"...","witnesses":[],"obligations":[],"exact_actions":[]},"artifact_kind":"analysis_only"}
Do not output policy source, Python, patches, diffs, alternative policies, or a
ranked selection. Analyze only the one visible policy lineage and provide the
bounded evidence requested by your role.
""".strip()
    else:
        raise CampaignError(f"unsupported call output type: {output_type}")
    return f"""
Execute exactly one role in a fixed historical topology translated to Cache
Policy vocabulary. This is representative {representative} for topology R{display_round}.
It is an independent run: no other representative, candidate, evaluation, or
score is visible. Do not use tools or inspect the filesystem; use only the inline
visible inputs below. Do not search, sample variants, or ask another agent.

Role id: {call['id']}
Role: {call['role']}
Objective: {call['objective']}
Output kind: {output_type}

{output_contract}

Visible inputs, exactly as fixed by the topology:
{json.dumps(visible_inputs, indent=2, ensure_ascii=False)}
""".strip()


def generate_representative(
    display_round: int,
    representative: int,
    home_slot: int,
    task_text: str,
    anchor_source: str,
    anchor_sha256: str,
) -> dict[str, Any]:
    translation_path = TRANSLATIONS / f"R{display_round}.json"
    translated = json.loads(translation_path.read_text(encoding="utf-8"))
    structure = translated["structure"]
    hypothesis = translated["hypothesis"]
    calls = flattened_calls(structure)
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
        call_id = f"R{display_round}-rep{representative:02d}-call{call_index:02d}-{call['id']}"
        parsed, receipt = run_codex(
            call_id=call_id,
            role=str(call["role"]),
            prompt=role_prompt(
                display_round=display_round,
                representative=representative,
                call=call,
                visible_inputs=visible_inputs,
            ),
            model="gpt-5.6-luna",
            effort="high",
            home_slot=home_slot,
            service_tier=None,
            timeout_seconds=900,
        )
        if call["output_type"] == "policy":
            output = {
                "artifact_kind": "policy",
                "policy_source": extract_policy_source(parsed, call_id=call_id),
                "sha256": sha256_bytes(extract_policy_source(parsed, call_id=call_id).encode("utf-8")),
            }
        else:
            if not isinstance(parsed, dict) or parsed.get("artifact_kind") != "analysis_only":
                raise CampaignError(f"{call_id} did not return analysis_only")
            serialized = json.dumps(parsed, sort_keys=True, ensure_ascii=False).casefold()
            if any(marker in serialized for marker in ("class policy", "def access", "```python")):
                raise CampaignError(f"{call_id} emitted policy code from an analysis role")
            output = parsed
        prior_outputs[str(call["id"])] = output
        receipt_path = MODEL_CALLS / call_id / "final-receipt.json"
        call_receipts.append(
            {
                "call_id": call_id,
                "role_id": call["id"],
                "output_type": call["output_type"],
                "path": str(receipt_path.relative_to(CAMPAIGN_DIR)),
                "sha256": sha256_file(receipt_path),
                "usage": receipt["usage"],
            }
        )
    final_call_id = structure["final_call_id"]
    final_output = prior_outputs.get(final_call_id)
    if not isinstance(final_output, dict) or final_output.get("artifact_kind") != "policy":
        raise CampaignError(f"R{display_round} rep {representative} final call did not emit policy")
    rep_dir = BOOTSTRAP / f"R{display_round}" / f"rep-{representative:02d}"
    artifact_path = rep_dir / "artifact" / "policy.py"
    write_text_new(artifact_path, final_output["policy_source"])
    manifest = {
        "schema_version": 1,
        "display_round": 0,
        "display_source_round": display_round,
        "representative": representative,
        "independent": True,
        "other_representatives_visible": False,
        "official_scores_visible": False,
        "benchmark_fixtures_visible": False,
        "home_slot": home_slot,
        "model": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "anchor_sha256": anchor_sha256,
        "translated_structure_sha256": sha256_file(translation_path),
        "artifact_path": str(artifact_path.relative_to(CAMPAIGN_DIR)),
        "artifact_sha256": sha256_file(artifact_path),
        "call_receipts": call_receipts,
    }
    write_json_new(rep_dir / "generation-manifest.json", manifest)
    print(
        json.dumps(
            {
                "generated": f"R{display_round}/rep-{representative:02d}",
                "calls": len(calls),
                "artifact_sha256": manifest["artifact_sha256"],
            }
        ),
        flush=True,
    )
    return manifest


def generate() -> None:
    if not (WORKSPACE / "translation-seal.json").is_file():
        raise CampaignError("translate must complete before generate")
    task_text = (SOURCE_SNAPSHOTS / "TASK.md").read_text(encoding="utf-8")
    anchor_source, _ = generate_anchor(task_text)
    anchor_sha256 = sha256_file(ANCHOR / "artifact" / "policy.py")
    jobs: list[tuple[int, int, int]] = []
    for structure_index, (display_round, _) in enumerate(SOURCE_ROUNDS):
        for representative in range(1, 4):
            job_index = structure_index * 3 + representative - 1
            jobs.append((display_round, representative, job_index % len(HOME_POOL)))
    queues = [[job for job in jobs if job[2] == slot] for slot in range(len(HOME_POOL))]

    def run_queue(queue: list[tuple[int, int, int]]) -> list[dict[str, Any]]:
        return [
            generate_representative(
                display_round,
                representative,
                home_slot,
                task_text,
                anchor_source,
                anchor_sha256,
            )
            for display_round, representative, home_slot in queue
        ]

    generated: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(HOME_POOL), thread_name_prefix="cache-rep-home") as pool:
        futures = [pool.submit(run_queue, queue) for queue in queues]
        for future in as_completed(futures):
            generated.extend(future.result())
    if len(generated) != 12:
        raise CampaignError("generation did not produce exactly twelve representatives")
    print(json.dumps({"phase": "generate", "anchor_sha256": anchor_sha256, "representatives": 12}))


GENERIC_VALIDATOR = r'''
import importlib.util,json,sys

candidate = sys.argv[1]
spec = importlib.util.spec_from_file_location("candidate_policy_generic", candidate)
if spec is None or spec.loader is None:
    raise RuntimeError("candidate import spec unavailable")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Policy = module.Policy

cases = [
    (1, [(1,1,0),(1,1,1),(2,1,2),(2,1,3),(3,2,4),(1,1,5)]),
    (3, [(10,1,0),(11,1,1),(12,1,2),(10,1,3),(13,1,4),(11,1,5),(14,4,6)]),
    (8, [(1,2,0),(2,3,1),(1,2,2),(3,4,3),(4,1,4),(2,3,5),(5,9,6),(4,1,7)]),
]

def replay(capacity, accesses):
    policy = Policy(capacity)
    if int(getattr(policy, "capacity_bytes")) != capacity:
        raise AssertionError("capacity_bytes not preserved")
    cache = {}
    transcript = []
    for key,size,now in accesses:
        evicted = policy.access(key,size,now)
        if not isinstance(evicted,list):
            raise AssertionError("eviction result is not list")
        if any(type(item) is not int for item in evicted):
            raise AssertionError("eviction key is not int")
        if len(evicted) != len(set(evicted)):
            raise AssertionError("duplicate eviction")
        for victim in evicted:
            if victim not in cache:
                raise AssertionError("evicted nonresident key")
            del cache[victim]
        if key not in cache and size <= capacity:
            if sum(cache.values()) + size > capacity:
                raise AssertionError("insufficient eviction")
            cache[key] = size
        if sum(cache.values()) > capacity:
            raise AssertionError("capacity exceeded")
        transcript.append(evicted)
    return transcript

first = [replay(*case) for case in cases]
second = [replay(*case) for case in cases]
if first != second:
    raise AssertionError("nondeterministic replay")
print(json.dumps({"valid":True,"deterministic":True,"case_count":len(cases),"access_count":sum(len(x[1]) for x in cases)},sort_keys=True))
'''.strip()


def generic_validate_policy(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        tree = None
        errors.append(f"syntax_error:{exc.msg}:{exc.lineno}")
    if tree is not None:
        policy_classes = [
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Policy"
        ]
        if len(policy_classes) != 1:
            errors.append("requires_exactly_one_top_level_Policy_class")
        else:
            methods = {
                node.name
                for node in policy_classes[0].body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if not {"__init__", "access"}.issubset(methods):
                errors.append("Policy_missing_required_methods")
    lower = source.casefold()
    campaign_forbidden = (
        "__main__",
        "inspect",
        "traceback",
        "eval(",
        "exec(",
        "compile(",
        "globals(",
        "locals(",
    )
    for marker in campaign_forbidden:
        if marker in lower:
            errors.append(f"campaign_forbidden_token:{marker}")
    runner = load_module(f"_cache_transfer_static_{uuid.uuid4().hex}", RUNNER_SOURCE)
    official_static_reject = runner.static_audit_candidate(path)
    if official_static_reject:
        errors.append(official_static_reject)
    runtime: dict[str, Any] = {}
    if not errors:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", GENERIC_VALIDATOR, str(path.resolve())],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=5,
                check=False,
            )
            if proc.returncode != 0:
                errors.append(f"generic_runtime_returncode:{proc.returncode}:{proc.stderr[-1000:]}")
            else:
                runtime = json.loads(proc.stdout)
                if runtime.get("valid") is not True or runtime.get("deterministic") is not True:
                    errors.append("generic_runtime_did_not_certify_validity")
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            errors.append(f"generic_runtime_error:{type(exc).__name__}")
    return {
        "valid": not errors,
        "errors": errors,
        "official_static_reject": official_static_reject,
        "runtime": runtime,
        "source_bytes": len(source.encode("utf-8")),
    }


def seal_artifact(
    *,
    label: str,
    artifact_path: Path,
    manifest_path: Path,
    seal_path: Path,
    kind: str,
) -> dict[str, Any]:
    if seal_path.is_file():
        existing = json.loads(seal_path.read_text(encoding="utf-8"))
        if existing.get("artifact_sha256") != sha256_file(artifact_path):
            raise CampaignError(f"existing seal artifact mismatch: {label}")
        return existing
    validation = generic_validate_policy(artifact_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt_entries: list[dict[str, str]] = []
    if kind == "anchor":
        receipt_path = MODEL_CALLS / "fresh-lru-anchor" / "final-receipt.json"
        receipt_entries.append(
            {"path": str(receipt_path.relative_to(CAMPAIGN_DIR)), "sha256": sha256_file(receipt_path)}
        )
    else:
        receipt_entries.extend(
            {"path": item["path"], "sha256": item["sha256"]}
            for item in manifest["call_receipts"]
        )
    seal = {
        "schema_version": 1,
        "label": label,
        "kind": kind,
        "sealed_at": utc_now(),
        "artifact_path": str(artifact_path.relative_to(CAMPAIGN_DIR)),
        "artifact_sha256": sha256_file(artifact_path),
        "artifact_bytes": artifact_path.stat().st_size,
        "generation_manifest_path": str(manifest_path.relative_to(CAMPAIGN_DIR)),
        "generation_manifest_sha256": sha256_file(manifest_path),
        "model_receipts": receipt_entries,
        "preseal_generic_validity": validation,
        "official_score_known_at_seal": False,
        "frozen_evaluation_known_at_seal": False,
    }
    write_json_new(seal_path, seal)
    return seal


def seal() -> None:
    if EVALUATION.exists() and any(EVALUATION.rglob("replay-*.json")):
        raise CampaignError("frozen evaluation exists before global seal creation")
    required = [
        ANCHOR / "artifact" / "policy.py",
        ANCHOR / "generation-manifest.json",
        WORKSPACE / "translation-seal.json",
    ]
    for display_round, _ in SOURCE_ROUNDS:
        required.append(TRANSLATIONS / f"R{display_round}.json")
        for representative in range(1, 4):
            rep_dir = BOOTSTRAP / f"R{display_round}" / f"rep-{representative:02d}"
            required.extend((rep_dir / "artifact" / "policy.py", rep_dir / "generation-manifest.json"))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise CampaignError(f"generation incomplete; missing {missing}")

    architect_receipt = json.loads(
        (MODEL_CALLS / "bootstrap-fixed-topology-translation" / "final-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        architect_receipt.get("model") != "gpt-5.6-sol"
        or architect_receipt.get("reasoning_effort") != "max"
        or architect_receipt.get("service_tier") != "fast"
        or architect_receipt.get("request_tier") != "priority"
    ):
        raise CampaignError("architect receipt violates Sol/max/Fast boundary")
    anchor_receipt = json.loads(
        (MODEL_CALLS / "fresh-lru-anchor" / "final-receipt.json").read_text(encoding="utf-8")
    )
    if (
        anchor_receipt.get("model") != "gpt-5.6-luna"
        or anchor_receipt.get("reasoning_effort") != "high"
    ):
        raise CampaignError("anchor receipt violates Luna-high boundary")
    shared_anchor_sha = sha256_file(ANCHOR / "artifact" / "policy.py")
    topology_call_count = 0
    for display_round, _ in SOURCE_ROUNDS:
        expected_calls = len(flattened_calls(json.loads((TRANSLATIONS / f"R{display_round}.json").read_text(encoding="utf-8"))["structure"]))
        for representative in range(1, 4):
            manifest = json.loads(
                (
                    BOOTSTRAP
                    / f"R{display_round}"
                    / f"rep-{representative:02d}"
                    / "generation-manifest.json"
                ).read_text(encoding="utf-8")
            )
            if manifest.get("anchor_sha256") != shared_anchor_sha:
                raise CampaignError("representatives do not share one immutable anchor hash")
            if len(manifest.get("call_receipts", [])) != expected_calls:
                raise CampaignError(f"R{display_round} rep {representative} call count violates topology")
            for item in manifest["call_receipts"]:
                receipt = json.loads((CAMPAIGN_DIR / item["path"]).read_text(encoding="utf-8"))
                if (
                    receipt.get("model") != "gpt-5.6-luna"
                    or receipt.get("reasoning_effort") != "high"
                    or receipt.get("service_tier") != "default"
                ):
                    raise CampaignError(f"inner role is not Luna-high: {item['call_id']}")
                topology_call_count += 1
    if topology_call_count != 27:
        raise CampaignError(f"expected exactly 27 Luna-high topology calls, got {topology_call_count}")

    seals: list[dict[str, Any]] = []
    anchor_seal = seal_artifact(
        label="anchor",
        artifact_path=ANCHOR / "artifact" / "policy.py",
        manifest_path=ANCHOR / "generation-manifest.json",
        seal_path=ANCHOR / "seal.json",
        kind="anchor",
    )
    seals.append(anchor_seal)
    for display_round, _ in SOURCE_ROUNDS:
        for representative in range(1, 4):
            rep_dir = BOOTSTRAP / f"R{display_round}" / f"rep-{representative:02d}"
            seals.append(
                seal_artifact(
                    label=f"R{display_round}-rep-{representative:02d}",
                    artifact_path=rep_dir / "artifact" / "policy.py",
                    manifest_path=rep_dir / "generation-manifest.json",
                    seal_path=rep_dir / "seal.json",
                    kind="representative",
                )
            )
    if len(seals) != 13:
        raise CampaignError("global seal requires anchor plus twelve representatives")
    entries = [
        {
            "label": item["label"],
            "artifact_path": item["artifact_path"],
            "artifact_sha256": item["artifact_sha256"],
            "seal_path": str(
                (
                    ANCHOR / "seal.json"
                    if item["kind"] == "anchor"
                    else next(
                        path
                        for path in BOOTSTRAP.rglob("seal.json")
                        if json.loads(path.read_text(encoding="utf-8"))["label"] == item["label"]
                    )
                ).relative_to(CAMPAIGN_DIR)
            ),
            "generic_valid": item["preseal_generic_validity"]["valid"],
        }
        for item in seals
    ]
    for entry in entries:
        entry["seal_sha256"] = sha256_file(CAMPAIGN_DIR / entry["seal_path"])
    global_seal = {
        "schema_version": 1,
        "display_round": 0,
        "sealed_at": utc_now(),
        "sealed_before_any_frozen_evaluation": True,
        "score_blind_generation": True,
        "anchor_count": 1,
        "structure_count": 4,
        "representatives_per_structure": 3,
        "representative_count": 12,
        "model_boundary": {
            "architect_calls": 1,
            "architect_model": "gpt-5.6-sol",
            "architect_reasoning_effort": "max",
            "architect_service_tier": "fast",
            "anchor_calls": 1,
            "anchor_model": "gpt-5.6-luna",
            "anchor_reasoning_effort": "high",
            "topology_calls": topology_call_count,
            "topology_model": "gpt-5.6-luna",
            "topology_reasoning_effort": "high",
        },
        "shared_anchor_sha256": shared_anchor_sha,
        "entries": entries,
        "aggregate_sha256": sha256_bytes(canonical_bytes(entries)),
        "benchmark_identity": {
            "field": CONTRACT["benchmark"]["field"],
            "seed": CONTRACT["benchmark"]["seed"],
            "scale": CONTRACT["benchmark"]["scale"],
            "trace_count": CONTRACT["benchmark"]["trace_count"],
            "fixture_sha256": CONTRACT["benchmark"]["fixture_sha256"],
        },
        "selection_contract": {
            **CONTRACT["selection"],
            "close_confirmation": CONTRACT["close_confirmation"],
            "close_threshold_rationale": "The absolute 0.25 band was fixed before score reveal as a conservative near-tie boundary: it is small enough not to redefine the primary median decision, while requiring an additional immutable replay when deterministic scorer or transcription drift could plausibly reverse a practically indistinguishable ordering.",
            "predeclared_before_score_reveal": True,
        },
    }
    global_seal["selection_contract_sha256"] = sha256_bytes(
        canonical_bytes(global_seal["selection_contract"])
    )
    write_json_new(WORKSPACE / "pre-evaluation-seal.json", global_seal)
    print(
        json.dumps(
            {
                "phase": "seal",
                "artifacts": 13,
                "generic_valid": sum(bool(item["generic_valid"]) for item in entries),
                "aggregate_sha256": global_seal["aggregate_sha256"],
            }
        )
    )


def normalized_evaluation_result(result: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(result))
    value.pop("candidate", None)
    return value


def official_result_valid(result: dict[str, Any]) -> bool:
    details = result.get("details")
    if not isinstance(details, dict):
        return False
    score = result.get("score")
    return (
        isinstance(score, (int, float))
        and math.isfinite(float(score))
        and result.get("trace_count") == CONTRACT["benchmark"]["trace_count"]
        and result.get("invalid_operation_count") == 0
        and result.get("timeout_count") == 0
        and "runtime_error" not in details
        and "static_reject" not in details
    )


class HeavyEvaluationLock:
    def __init__(self, path: Path):
        self.path = path
        self.token = uuid.uuid4().hex

    def __enter__(self) -> HeavyEvaluationLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "kind": "cache-policy-frozen-v3-replay2",
            "campaign": CONTRACT["campaign_id"],
            "pid": os.getpid(),
            "token": self.token,
            "acquired_at": utc_now(),
        }
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as exc:
            owner = self.path.read_text(encoding="utf-8", errors="replace")[:2000]
            raise CampaignError(f"heavy evaluation lock is held: {owner}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if current.get("token") == self.token:
            self.path.unlink()


def evaluation_target_dir(label: str) -> Path:
    if label == "anchor":
        return EVALUATION / "anchor"
    prefix, rep = label.split("-rep-")
    return EVALUATION / prefix / f"rep-{rep}"


def run_frozen_replay(
    *,
    label: str,
    artifact_path: Path,
    artifact_sha256: str,
    replay: int,
    runner: Any,
    traces: list[Any],
) -> dict[str, Any]:
    target = evaluation_target_dir(label) / f"replay-{replay:02d}.json"
    if target.is_file():
        value = json.loads(target.read_text(encoding="utf-8"))
        if value.get("artifact_sha256") != artifact_sha256:
            raise CampaignError(f"evaluation artifact hash mismatch for {label}")
        return value
    if sha256_file(artifact_path) != artifact_sha256:
        raise CampaignError(f"sealed artifact changed before evaluation: {label}")
    started_at = utc_now()
    started = time.monotonic()
    result = runner.evaluate_candidate(artifact_path, traces=traces, timeout_s=60.0)
    normalized = normalized_evaluation_result(result)
    record = {
        "schema_version": 1,
        "label": label,
        "replay": replay,
        "artifact_path": str(artifact_path.relative_to(CAMPAIGN_DIR)),
        "artifact_sha256": artifact_sha256,
        "benchmark": {
            "field": CONTRACT["benchmark"]["field"],
            "seed": CONTRACT["benchmark"]["seed"],
            "scale": CONTRACT["benchmark"]["scale"],
            "trace_count": CONTRACT["benchmark"]["trace_count"],
            "fixture_sha256": CONTRACT["benchmark"]["fixture_sha256"],
            "runner_sha256": sha256_file(RUNNER_SOURCE),
        },
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": round(time.monotonic() - started, 6),
        "result": result,
        "normalized_result_sha256": sha256_bytes(canonical_bytes(normalized)),
        "valid": official_result_valid(result),
    }
    write_json_new(target, record)
    print(
        json.dumps(
            {
                "evaluated": label,
                "replay": replay,
                "score": result.get("score"),
                "valid": record["valid"],
            }
        ),
        flush=True,
    )
    return record


def structure_summaries(required_replays: int = 2) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for display_round, _ in SOURCE_ROUNDS:
        reps: list[dict[str, Any]] = []
        for representative in range(1, 4):
            label = f"R{display_round}-rep-{representative:02d}"
            records = [
                json.loads(
                    (evaluation_target_dir(label) / f"replay-{replay:02d}.json").read_text(encoding="utf-8")
                )
                for replay in range(1, required_replays + 1)
            ]
            hashes = {item["normalized_result_sha256"] for item in records}
            deterministic = len(hashes) == 1
            valid = deterministic and all(bool(item["valid"]) for item in records)
            seal = json.loads(
                (BOOTSTRAP / f"R{display_round}" / f"rep-{representative:02d}" / "seal.json").read_text(
                    encoding="utf-8"
                )
            )
            reps.append(
                {
                    "representative": representative,
                    "artifact_sha256": seal["artifact_sha256"],
                    "score": float(records[0]["result"].get("score", 0.0)),
                    "valid": valid,
                    "replay_deterministic": deterministic,
                    "replay_hash": records[0]["normalized_result_sha256"],
                    "failure": (
                        None
                        if valid
                        else {
                            "trace_count": records[0]["result"].get("trace_count"),
                            "invalid_operation_count": records[0]["result"].get("invalid_operation_count"),
                            "timeout_count": records[0]["result"].get("timeout_count"),
                            "details": records[0]["result"].get("details"),
                        }
                    ),
                }
            )
        scores = [item["score"] for item in reps]
        summaries.append(
            {
                "display_source_round": display_round,
                "representatives": reps,
                "all_valid": all(item["valid"] for item in reps),
                "median_score": statistics.median(scores),
                "minimum_score": min(scores),
                "mean_score": statistics.fmean(scores),
            }
        )
    return summaries


def ranked_eligible(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (item for item in summaries if item["all_valid"]),
        key=lambda item: (
            -item["median_score"],
            -item["minimum_score"],
            -item["mean_score"],
            item["display_source_round"],
        ),
    )


def evaluate() -> None:
    if os.environ.get("CACHE_SCORER_CHESS_GO") != "GO":
        raise CampaignError("fresh chess GO is required: set CACHE_SCORER_CHESS_GO=GO")
    global_seal_path = WORKSPACE / "pre-evaluation-seal.json"
    if not global_seal_path.is_file():
        raise CampaignError("seal must complete before evaluate")
    global_seal = json.loads(global_seal_path.read_text(encoding="utf-8"))
    if len(global_seal.get("entries", [])) != 13:
        raise CampaignError("pre-evaluation seal is incomplete")
    for entry in global_seal["entries"]:
        artifact = CAMPAIGN_DIR / entry["artifact_path"]
        seal_path = CAMPAIGN_DIR / entry["seal_path"]
        if sha256_file(artifact) != entry["artifact_sha256"] or sha256_file(seal_path) != entry["seal_sha256"]:
            raise CampaignError(f"pre-evaluation seal integrity failure: {entry['label']}")
    source_manifest = json.loads((WORKSPACE / "source-manifest.json").read_text(encoding="utf-8"))
    if sha256_file(RUNNER_SOURCE) != source_manifest["frozen_runner"]["sha256"]:
        raise CampaignError("authoritative frozen runner changed")
    runner = load_module("_cache_transfer_frozen_evaluator", RUNNER_SOURCE)
    traces = runner.generate_trace_suite(
        CONTRACT["benchmark"]["seed"], CONTRACT["benchmark"]["scale"]
    )
    rows = [
        {
            "name": trace.name,
            "capacity_bytes": trace.capacity_bytes,
            "accesses": [
                {"now": access.now, "key": access.key, "size": access.size}
                for access in trace.accesses
            ],
        }
        for trace in traces
    ]
    if sha256_bytes(canonical_bytes(rows)) != CONTRACT["benchmark"]["fixture_sha256"]:
        raise CampaignError("fixture identity changed at reveal")

    with HeavyEvaluationLock(HEAVY_LOCK):
        for entry in global_seal["entries"]:
            artifact = CAMPAIGN_DIR / entry["artifact_path"]
            for replay in (1, 2):
                run_frozen_replay(
                    label=entry["label"],
                    artifact_path=artifact,
                    artifact_sha256=entry["artifact_sha256"],
                    replay=replay,
                    runner=runner,
                    traces=traces,
                )
        summaries = structure_summaries(required_replays=2)
        eligible = ranked_eligible(summaries)
        threshold = float(CONTRACT["close_confirmation"]["trigger_absolute_median_difference_lte"])
        close_triggered = (
            len(eligible) >= 2
            and abs(eligible[0]["median_score"] - eligible[1]["median_score"]) <= threshold
        )
        confirmation_labels: list[str] = []
        if close_triggered:
            for item in eligible[:2]:
                display_round = item["display_source_round"]
                for representative in range(1, 4):
                    label = f"R{display_round}-rep-{representative:02d}"
                    seal_entry = next(row for row in global_seal["entries"] if row["label"] == label)
                    run_frozen_replay(
                        label=label,
                        artifact_path=CAMPAIGN_DIR / seal_entry["artifact_path"],
                        artifact_sha256=seal_entry["artifact_sha256"],
                        replay=3,
                        runner=runner,
                        traces=traces,
                    )
                    confirmation_labels.append(label)
    confirmations: list[dict[str, Any]] = []
    for label in confirmation_labels:
        records = [
            json.loads((evaluation_target_dir(label) / f"replay-{index:02d}.json").read_text(encoding="utf-8"))
            for index in (1, 2, 3)
        ]
        confirmations.append(
            {
                "label": label,
                "normalized_result_sha256": records[0]["normalized_result_sha256"],
                "confirmed": len({row["normalized_result_sha256"] for row in records}) == 1,
            }
        )
    batch = {
        "schema_version": 1,
        "completed_at": utc_now(),
        "pre_evaluation_seal_sha256": sha256_file(global_seal_path),
        "replay_count": 2,
        "structure_summaries": summaries,
        "eligible_order": [item["display_source_round"] for item in eligible],
        "close_threshold": threshold,
        "close_confirmation_triggered": close_triggered,
        "confirmations": confirmations,
        "confirmation_passed": all(item["confirmed"] for item in confirmations),
    }
    write_json_new(EVALUATION / "evaluation-batch.json", batch)
    print(
        json.dumps(
            {
                "phase": "evaluate",
                "eligible_order": batch["eligible_order"],
                "close_confirmation_triggered": close_triggered,
                "confirmation_passed": batch["confirmation_passed"],
            }
        )
    )


def sum_usage(receipts: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "model_calls": len(receipts),
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "effective_tokens": 0,
    }
    for receipt in receipts:
        usage = receipt["usage"]
        totals["input_tokens"] += int(usage["input_tokens"])
        totals["cached_input_tokens"] += int(usage["cached_input_tokens"])
        totals["output_tokens"] += int(usage["output_tokens"])
        totals["reasoning_output_tokens"] += int(usage["reasoning_output_tokens"])
    totals["uncached_input_tokens"] = totals["input_tokens"] - totals["cached_input_tokens"]
    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    totals["effective_tokens"] = totals["uncached_input_tokens"] + totals["output_tokens"]
    return totals


def token_accounting() -> dict[str, Any]:
    receipts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(MODEL_CALLS.rglob("final-receipt.json"))
    ]
    architect = [row for row in receipts if row["call_id"] == "bootstrap-fixed-topology-translation"]
    anchor = [row for row in receipts if row["call_id"] == "fresh-lru-anchor"]
    topology = [row for row in receipts if row["call_id"].startswith("R")]
    if (len(architect), len(anchor), len(topology), len(receipts)) != (1, 1, 27, 29):
        raise CampaignError(
            f"token accounting expected 1 architect + 1 anchor + 27 topology calls; got {len(architect)}, {len(anchor)}, {len(topology)}, {len(receipts)}"
        )
    failures = [
        json.loads(path.read_text(encoding="utf-8"))
        | {
            "path": str(path.relative_to(CAMPAIGN_DIR)),
            "raw_events_sha256": (
                sha256_file(path.parent / "raw-events.jsonl")
                if (path.parent / "raw-events.jsonl").is_file()
                else None
            ),
        }
        for path in sorted(MODEL_CALLS.rglob("failure-receipt.json"))
    ]
    return {
        "schema_version": 1,
        "rule": {
            "total_tokens": "input_tokens + output_tokens",
            "effective_tokens": "input_tokens - cached_input_tokens + output_tokens",
            "reasoning_output_tokens": "subset of output tokens",
        },
        "architect": sum_usage(architect),
        "anchor": sum_usage(anchor),
        "topology_inner_roles": sum_usage(topology),
        "campaign_model_calls": sum_usage(receipts),
        "transport_attempts": len(receipts) + len(failures),
        "completed_model_calls": len(receipts),
        "failed_transport_attempts": len(failures),
        "transport_failures": failures,
        "receipt_paths": [
            {
                "call_id": row["call_id"],
                "path": str(
                    next(
                        path
                        for path in MODEL_CALLS.rglob("final-receipt.json")
                        if json.loads(path.read_text(encoding="utf-8"))["call_id"] == row["call_id"]
                    ).relative_to(CAMPAIGN_DIR)
                ),
            }
            for row in sorted(receipts, key=lambda item: item["call_id"])
        ],
    }


def anchor_evaluation_summary() -> dict[str, Any]:
    records = [
        json.loads((EVALUATION / "anchor" / f"replay-{index:02d}.json").read_text(encoding="utf-8"))
        for index in (1, 2)
    ]
    return {
        "score": float(records[0]["result"].get("score", 0.0)),
        "valid": all(bool(row["valid"]) for row in records),
        "replay_deterministic": len({row["normalized_result_sha256"] for row in records}) == 1,
        "artifact_sha256": records[0]["artifact_sha256"],
    }


def finalize() -> None:
    batch_path = EVALUATION / "evaluation-batch.json"
    if not batch_path.is_file():
        raise CampaignError("evaluate must complete before finalize")
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    global_seal_path = WORKSPACE / "pre-evaluation-seal.json"
    if batch.get("pre_evaluation_seal_sha256") != sha256_file(global_seal_path):
        raise CampaignError("evaluation batch does not bind the pre-evaluation seal")
    if batch.get("close_confirmation_triggered") and not batch.get("confirmation_passed"):
        raise CampaignError("predeclared close-result confirmation failed")
    summaries = structure_summaries(required_replays=2)
    eligible = ranked_eligible(summaries)
    anchor_summary = anchor_evaluation_summary()
    if eligible:
        selected = eligible[0]
        display_source_round = int(selected["display_source_round"])
        median_score = float(selected["median_score"])
        median_reps = [
            item for item in selected["representatives"] if item["valid"] and item["score"] == median_score
        ]
        representative_row = min(median_reps, key=lambda item: item["artifact_sha256"])
        representative = int(representative_row["representative"])
        source_rep_dir = BOOTSTRAP / f"R{display_source_round}" / f"rep-{representative:02d}"
        source_artifact = source_rep_dir / "artifact" / "policy.py"
        source_seal = source_rep_dir / "seal.json"
        translation = json.loads((TRANSLATIONS / f"R{display_source_round}.json").read_text(encoding="utf-8"))
        fallback = False
    else:
        if not anchor_summary["valid"] or not anchor_summary["replay_deterministic"]:
            raise CampaignError("no eligible structure and anchor fallback is invalid")
        display_source_round = None
        representative = None
        representative_row = {
            "artifact_sha256": anchor_summary["artifact_sha256"],
            "score": anchor_summary["score"],
        }
        source_artifact = ANCHOR / "artifact" / "policy.py"
        source_seal = ANCHOR / "seal.json"
        translation = None
        fallback = True

    champion_dir = WORKSPACE / "champion-r0"
    write_bytes_new(champion_dir / "policy.py", source_artifact.read_bytes())
    if translation is not None:
        write_json_new(champion_dir / "structure.json", translation["structure"])
        write_json_new(champion_dir / "hypothesis.json", translation["hypothesis"])
    accounting = token_accounting()
    write_json_new(WORKSPACE / "token-accounting.json", accounting)
    selection_receipt = {
        "schema_version": 1,
        "display_round": 0,
        "status": "provisional-bootstrap-champion",
        "selected_at": utc_now(),
        "fallback_to_anchor": fallback,
        "display_source_round": display_source_round,
        "representative": representative,
        "artifact_sha256": sha256_file(champion_dir / "policy.py"),
        "score": representative_row["score"],
        "source_artifact_path": str(source_artifact.relative_to(CAMPAIGN_DIR)),
        "source_seal_path": str(source_seal.relative_to(CAMPAIGN_DIR)),
        "source_seal_sha256": sha256_file(source_seal),
        "selection_contract": CONTRACT["selection"],
        "eligible_order": [item["display_source_round"] for item in eligible],
        "close_confirmation": {
            "threshold": batch["close_threshold"],
            "triggered": batch["close_confirmation_triggered"],
            "passed": batch["confirmation_passed"],
        },
        "pre_evaluation_seal_path": str(global_seal_path.relative_to(CAMPAIGN_DIR)),
        "pre_evaluation_seal_sha256": sha256_file(global_seal_path),
        "evaluation_batch_path": str(batch_path.relative_to(CAMPAIGN_DIR)),
        "evaluation_batch_sha256": sha256_file(batch_path),
    }
    write_json_new(champion_dir / "selection-receipt.json", selection_receipt)
    report = {
        "schema_version": 1,
        "display_round": 0,
        "campaign_id": CONTRACT["campaign_id"],
        "status": "committable-provisional-bootstrap-r0",
        "benchmark": {
            "field": CONTRACT["benchmark"]["field"],
            "seed": CONTRACT["benchmark"]["seed"],
            "scale": CONTRACT["benchmark"]["scale"],
            "trace_count": CONTRACT["benchmark"]["trace_count"],
            "fixture_sha256": CONTRACT["benchmark"]["fixture_sha256"],
        },
        "anchor": anchor_summary,
        "structures": summaries,
        "selection": selection_receipt,
        "token_accounting": accounting,
        "model_contract_passed": True,
        "sealed_before_frozen_evaluation": True,
        "stop_after_round": True,
        "cache_r1_opened": False,
    }
    write_json_new(WORKSPACE / "R0-ROUND-REPORT.json", report)
    lines = [
        "# Cache Transfer League — display R0",
        "",
        "Fresh bootstrap only. No prior Cache lineage, artifacts, scores, or error notes were used.",
        "",
        f"Frozen benchmark: `{CONTRACT['benchmark']['field']}`, seed `{CONTRACT['benchmark']['seed']}`, scale `{CONTRACT['benchmark']['scale']}`, {CONTRACT['benchmark']['trace_count']} traces, fixture `{CONTRACT['benchmark']['fixture_sha256']}`.",
        "",
        "| Fixed source topology | Rep 1 | Rep 2 | Rep 3 | Median | All valid |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for item in summaries:
        scores = [rep["score"] for rep in item["representatives"]]
        lines.append(
            f"| R{item['display_source_round']} | {scores[0]:.4f} | {scores[1]:.4f} | {scores[2]:.4f} | {item['median_score']:.4f} | {'yes' if item['all_valid'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            f"Anchor replay score: `{anchor_summary['score']:.4f}`; valid/deterministic: `{anchor_summary['valid'] and anchor_summary['replay_deterministic']}`.",
            "",
            (
                f"Provisional R0 selects fixed R{display_source_round} topology, representative {representative}, artifact `{selection_receipt['artifact_sha256']}`."
                if not fallback
                else f"No structure passed all-valid; provisional R0 falls back to the shared LRU anchor `{selection_receipt['artifact_sha256']}`."
            ),
            "",
            f"Close confirmation (0.25 absolute median band): triggered `{batch['close_confirmation_triggered']}`, passed `{batch['confirmation_passed']}`.",
            "",
            "Campaign stop is final at display R0. Cache R1 was not opened.",
            "",
        ]
    )
    write_text_new(CAMPAIGN_DIR / "R0-ROUND-REPORT.md", "\n".join(lines))
    state = {
        "schema_version": 1,
        "campaign_id": CONTRACT["campaign_id"],
        "display_round": 0,
        "status": "stopped-after-bootstrap-r0",
        "champion_selection_receipt": str((champion_dir / "selection-receipt.json").relative_to(CAMPAIGN_DIR)),
        "champion_artifact_sha256": selection_receipt["artifact_sha256"],
        "cache_r1_opened": False,
        "next_round_permitted": False,
    }
    write_json_new(WORKSPACE / "state.json", state)
    print(
        json.dumps(
            {
                "phase": "finalize",
                "display_round": 0,
                "selected_source_round": display_source_round,
                "representative": representative,
                "artifact_sha256": selection_receipt["artifact_sha256"],
                "stopped": True,
            }
        )
    )


def verify() -> None:
    test_started = utc_now()
    test_proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(CAMPAIGN_DIR / "test_bootstrap_contract.py")],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        check=False,
    )
    if test_proc.returncode != 0:
        raise CampaignError(f"verify: pytest failed\n{test_proc.stdout}\n{test_proc.stderr}")
    test_receipt = {
        "schema_version": 1,
        "command": [sys.executable, "-m", "pytest", "-q", "test_bootstrap_contract.py"],
        "started_at": test_started,
        "finished_at": utc_now(),
        "returncode": test_proc.returncode,
        "stdout": test_proc.stdout,
        "stderr": test_proc.stderr,
        "passed": True,
    }
    write_json_new(WORKSPACE / "test-receipt.json", test_receipt)
    global_seal = json.loads((WORKSPACE / "pre-evaluation-seal.json").read_text(encoding="utf-8"))
    if len(global_seal["entries"]) != 13:
        raise CampaignError("verify: global seal count")
    if global_seal["model_boundary"]["topology_calls"] != 27:
        raise CampaignError("verify: topology call count")
    anchor_hashes = set()
    for entry in global_seal["entries"]:
        artifact = CAMPAIGN_DIR / entry["artifact_path"]
        seal_path = CAMPAIGN_DIR / entry["seal_path"]
        if sha256_file(artifact) != entry["artifact_sha256"]:
            raise CampaignError(f"verify: artifact changed {entry['label']}")
        if sha256_file(seal_path) != entry["seal_sha256"]:
            raise CampaignError(f"verify: seal changed {entry['label']}")
        if entry["label"] != "anchor":
            manifest_path = artifact.parents[1] / "generation-manifest.json"
            anchor_hashes.add(json.loads(manifest_path.read_text(encoding="utf-8"))["anchor_sha256"])
    if anchor_hashes != {global_seal["shared_anchor_sha256"]}:
        raise CampaignError("verify: more than one starting anchor")
    batch = json.loads((EVALUATION / "evaluation-batch.json").read_text(encoding="utf-8"))
    for item in batch["structure_summaries"]:
        for rep in item["representatives"]:
            if not rep["replay_deterministic"]:
                raise CampaignError("verify: nondeterministic replay")
    if batch["close_confirmation_triggered"] and not batch["confirmation_passed"]:
        raise CampaignError("verify: close confirmation failed")
    state = json.loads((WORKSPACE / "state.json").read_text(encoding="utf-8"))
    if state != {
        **state,
        "display_round": 0,
        "status": "stopped-after-bootstrap-r0",
        "cache_r1_opened": False,
        "next_round_permitted": False,
    }:
        raise CampaignError("verify: campaign did not stop at R0")
    champion = WORKSPACE / "champion-r0" / "policy.py"
    if sha256_file(champion) != state["champion_artifact_sha256"]:
        raise CampaignError("verify: champion hash mismatch")
    validation = generic_validate_policy(champion)
    if not validation["valid"]:
        raise CampaignError(f"verify: champion generic validity failed: {validation['errors']}")
    accounting = token_accounting()
    if accounting["topology_inner_roles"]["model_calls"] != 27:
        raise CampaignError("verify: token accounting mismatch")
    audit_paths = [
        WORKSPACE / "source-manifest.json",
        WORKSPACE / "translation-seal.json",
        WORKSPACE / "pre-evaluation-seal.json",
        EVALUATION / "evaluation-batch.json",
        WORKSPACE / "token-accounting.json",
        WORKSPACE / "champion-r0" / "policy.py",
        WORKSPACE / "champion-r0" / "structure.json",
        WORKSPACE / "champion-r0" / "selection-receipt.json",
        WORKSPACE / "R0-ROUND-REPORT.json",
        CAMPAIGN_DIR / "R0-ROUND-REPORT.md",
        WORKSPACE / "state.json",
        WORKSPACE / "test-receipt.json",
    ]
    audit_entries = [
        {
            "path": str(path.relative_to(CAMPAIGN_DIR)),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in audit_paths
    ]
    verification_receipt = {
        "schema_version": 1,
        "verified_at": utc_now(),
        "valid": True,
        "display_round": 0,
        "stopped": True,
        "cache_r1_opened": False,
        "git_commit_created": False,
        "checks": {
            "fixture_identity": True,
            "fixed_topology_translations": True,
            "single_shared_anchor": True,
            "all_model_receipts": True,
            "seal_before_score": True,
            "replay2_deterministic": True,
            "all_valid_median_contract": True,
            "close_confirmation_contract": True,
            "token_accounting": True,
            "pytest": True,
        },
        "entries": audit_entries,
        "aggregate_sha256": sha256_bytes(canonical_bytes(audit_entries)),
    }
    write_json_new(WORKSPACE / "verification-receipt.json", verification_receipt)
    commit_entries = [
        *audit_entries,
        {
            "path": str((WORKSPACE / "verification-receipt.json").relative_to(CAMPAIGN_DIR)),
            "sha256": sha256_file(WORKSPACE / "verification-receipt.json"),
            "bytes": (WORKSPACE / "verification-receipt.json").stat().st_size,
        },
    ]
    atomic_commit = {
        "schema_version": 1,
        "campaign_id": CONTRACT["campaign_id"],
        "committed_at": utc_now(),
        "commit_kind": "campaign-state-manifest-not-git",
        "display_round": 0,
        "status": "atomically-committed-and-stopped",
        "champion_artifact_sha256": state["champion_artifact_sha256"],
        "cache_r1_opened": False,
        "next_round_permitted": False,
        "git_commit_created": False,
        "entries": commit_entries,
        "aggregate_sha256": sha256_bytes(canonical_bytes(commit_entries)),
    }
    write_json_new(WORKSPACE / "R0-ATOMIC-COMMIT.json", atomic_commit)
    print(
        json.dumps(
            {
                "phase": "verify",
                "valid": True,
                "display_round": 0,
                "champion_artifact_sha256": state["champion_artifact_sha256"],
                "model_calls": accounting["campaign_model_calls"]["model_calls"],
                "atomic_commit_sha256": sha256_file(WORKSPACE / "R0-ATOMIC-COMMIT.json"),
            }
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "translate", "generate", "seal", "evaluate", "finalize", "verify")
    )
    args = parser.parse_args(argv)
    commands = {
        "prepare": prepare,
        "translate": translate,
        "generate": generate,
        "seal": seal,
        "evaluate": evaluate,
        "finalize": finalize,
        "verify": verify,
    }
    commands[args.command]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
