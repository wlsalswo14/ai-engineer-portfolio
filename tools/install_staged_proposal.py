from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loop_evolution.common import atomic_json, content_hash, read_json  # noqa: E402
from loop_evolution.plan import LoopPlan  # noqa: E402


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(staging_dir: Path, generation_dir: Path, capsule_path: Path) -> dict[str, object]:
    staged_plan_path = staging_dir / "normalized-plan.json"
    delegated_receipt_path = staging_dir / "subagent-receipt.json"
    payload = read_json(staged_plan_path)
    delegated = read_json(delegated_receipt_path)
    capsule = read_json(capsule_path)
    expected_mode = str(capsule["search_control"]["proposal_mode"])
    plan = LoopPlan.from_payload(payload, expected_mode=expected_mode)
    plan.validate_search_context(capsule)
    output = delegated.get("output", {})
    validation = delegated.get("validation", {})
    if delegated.get("provenance", {}).get("reasoning_effort") != "max":
        raise RuntimeError("staged proposal is not from a max reasoning subagent")
    if delegated.get("provenance", {}).get("agent_mode") != "independent_subagent":
        raise RuntimeError("staged proposal is not from an independent subagent")
    if output.get("structure_id") != plan.structure_id:
        raise RuntimeError("staged receipt structure ID does not match the plan")
    if output.get("normalized_plan_file_sha256") != _file_sha256(staged_plan_path):
        raise RuntimeError("staged proposal file hash does not match the receipt")
    if not validation.get("passed"):
        raise RuntimeError("staged proposal was not validated")

    live_plan_path = generation_dir / "normalized-plan.json"
    if live_plan_path.is_file():
        live = LoopPlan.from_payload(read_json(live_plan_path), expected_mode=expected_mode)
        if live.structure_id != plan.structure_id:
            raise RuntimeError("a different live proposal already exists")
        return {"installed": False, "already_present": True, "structure_id": plan.structure_id}

    session_path = generation_dir / "architect-session.json"
    session = read_json(session_path)
    policy = session.get("proposal_policy")
    policy_sha256 = session.get("proposal_policy_sha256")
    if not isinstance(policy, dict) or policy.get("reasoning_effort") != "max":
        raise RuntimeError("live architect session is not the active max policy")

    response = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    prompt_path = generation_dir / "attempts" / "attempt-01" / "architect-prompt.txt"
    receipt = {
        "schema_version": 1,
        "attempt": 1,
        "agent_role": "structural_architect",
        "proposal_policy": policy,
        "proposal_policy_sha256": policy_sha256,
        "execution_provenance": "collaboration_subagent_direct_contingency",
        "official_codex_backend_invoked": False,
        "delegated_subagent_receipt_path": str(delegated_receipt_path.resolve()),
        "delegated_subagent_receipt_sha256": _file_sha256(delegated_receipt_path),
        "prompt_sha256": (
            content_hash(prompt_path.read_text(encoding="utf-8")) if prompt_path.is_file() else None
        ),
        "response_sha256": content_hash(response),
        "usage": {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "model_calls": 0,
        },
        "trace_refs": ["collaboration-subagent:gpt-5.6-sol:max"],
        "validation": validation,
    }
    generation_dir.mkdir(parents=True, exist_ok=True)
    (generation_dir / "architect-response.txt").write_text(response, encoding="utf-8")
    atomic_json(generation_dir / "architect-receipt.json", receipt)
    atomic_json(live_plan_path, payload)
    atomic_json(
        session_path,
        {
            **session,
            "delegated_subagent_receipt_path": str(delegated_receipt_path.resolve()),
            "delegated_subagent_receipt_sha256": _file_sha256(delegated_receipt_path),
        },
    )
    return {
        "installed": True,
        "already_present": False,
        "structure_id": plan.structure_id,
        "live_plan_path": str(live_plan_path.resolve()),
        "receipt_path": str((generation_dir / "architect-receipt.json").resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--generation-dir", type=Path, required=True)
    parser.add_argument("--capsule", type=Path, required=True)
    args = parser.parse_args()
    result = install(args.staging_dir.resolve(), args.generation_dir.resolve(), args.capsule.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
