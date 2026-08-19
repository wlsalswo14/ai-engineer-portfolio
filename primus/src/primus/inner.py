from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from primus.backend import CodexBackend
from primus.errors import ContractError
from primus.jsonutil import atomic_json, bytes_hash, parse_json_object, read_json
from primus.models import Budget, LoopStructure, Usage


@dataclass(frozen=True)
class GeneratedArtifact:
    payload: dict[str, Any]
    raw_bytes: bytes
    usage: Usage
    artifact_sha256: str
    call_receipts: tuple[str, ...]


class InnerLoopExecutor:
    def __init__(self, backend: CodexBackend):
        self.backend = backend

    def execute(
        self,
        *,
        structure: LoopStructure,
        task: str,
        champion_artifact: str,
        champion_metrics: dict[str, Any],
        public_audit: list[dict[str, Any]],
        hypothesis: dict[str, Any],
        artifact_contract: dict[str, Any],
        budget: Budget,
        working_directory: Path,
    ) -> GeneratedArtifact:
        structure.validate(max_calls=budget.max_calls)
        working_directory.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, str] = {}
        total = Usage()
        receipt_paths: list[str] = []
        started = time.monotonic()
        common: dict[str, Any] = {
            "task": task,
            "champion_artifact": champion_artifact,
            "champion_metrics": champion_metrics,
            "public_audit": public_audit,
            "hypothesis": hypothesis,
            "loop_structure": structure.to_dict(),
        }
        for index, call in enumerate(structure.calls, 1):
            remaining_seconds = budget.max_wall_seconds - (time.monotonic() - started)
            if remaining_seconds <= 0:
                raise ContractError("inner loop exceeded the sealed wall-clock budget")
            inputs = {name: outputs[name] if name in outputs else common[name] for name in call.inputs}
            final = call.id == structure.final_call_id
            prompt = self._prompt(call.objective, inputs, artifact_contract if final else None)
            call_dir = working_directory / "calls" / f"{index:02d}-{call.id}"
            cached = self._cached_call(call_dir, role=call.role, prompt=prompt)
            if cached is None:
                execution_directory = call_dir / "workspace"
                response = self.backend.complete(
                    role=call.role,
                    prompt=prompt,
                    working_directory=execution_directory,
                    receipt_dir=call_dir,
                    timeout_seconds=remaining_seconds,
                )
                response_text, response_usage = response.text, response.usage
            else:
                response_text, response_usage = cached
            total = total + response_usage
            if (
                total.model_calls > budget.max_calls
                or total.total_tokens > budget.max_total_tokens
                or total.effective_tokens > budget.max_effective_tokens
                or (budget.max_output_tokens > 0 and total.output_tokens > budget.max_output_tokens)
            ):
                raise ContractError("inner loop exceeded the sealed budget")
            if time.monotonic() - started > budget.max_wall_seconds:
                raise ContractError("inner loop exceeded the sealed wall-clock budget")
            outputs[call.id] = response_text
            receipt_paths.append(str((call_dir / "receipt.json").resolve()))
        payload = parse_json_object(outputs[structure.final_call_id])
        self._validate_artifact_shape(payload, artifact_contract)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        atomic_json(working_directory / "artifact.json", payload)
        atomic_json(
            working_directory / "generation-manifest.json",
            {
                "schema_version": 1,
                "structure_id": structure.structure_id,
                "structure_sha256": bytes_hash(json.dumps(structure.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
                "artifact_sha256": bytes_hash(raw),
                "usage": total.to_dict(),
                "call_receipts": receipt_paths,
                "all_calls_completed_before_evaluation": True,
                "wall_seconds": time.monotonic() - started,
                "isolated_call_workspaces": True,
            },
        )
        return GeneratedArtifact(payload, raw, total, bytes_hash(raw), tuple(receipt_paths))

    @staticmethod
    def _cached_call(call_dir: Path, *, role: str, prompt: str) -> tuple[str, Usage] | None:
        receipt_path = call_dir / "receipt.json"
        response_path = call_dir / "response.txt"
        prompt_path = call_dir / "prompt.txt"
        if not (receipt_path.is_file() and response_path.is_file() and prompt_path.is_file()):
            return None
        expected_prompt = f"Role: {role}\n\n{prompt}"
        receipt = read_json(receipt_path)
        response = response_path.read_text(encoding="utf-8")
        if prompt_path.read_text(encoding="utf-8") != expected_prompt:
            raise ContractError(f"cached call prompt differs: {call_dir}")
        if bytes_hash(expected_prompt.encode("utf-8")) != receipt.get("prompt_sha256"):
            raise ContractError(f"cached call prompt digest differs: {call_dir}")
        if bytes_hash(response.encode("utf-8")) != receipt.get("response_sha256"):
            raise ContractError(f"cached call response digest differs: {call_dir}")
        raw = receipt.get("usage", {})
        usage = Usage(**{key: int(raw.get(key, 0)) for key in Usage.__dataclass_fields__})
        return response, usage

    @staticmethod
    def _prompt(objective: str, inputs: dict[str, Any], final_contract: dict[str, Any] | None) -> str:
        contract = ""
        if final_contract is not None:
            contract = (
                "\n\nFINAL ARTIFACT CONTRACT\n"
                + json.dumps(final_contract, ensure_ascii=False, sort_keys=True)
                + "\nReturn exactly one JSON object satisfying this contract. Do not return Markdown or prose outside it."
            )
        return (
            "Execute only this role in one lineage. Do not inspect evaluator files, hidden tasksets, scores, or other runs.\n\n"
            f"OBJECTIVE\n{objective}\n\n"
            "SEALED INPUTS\n"
            + json.dumps(inputs, ensure_ascii=False, sort_keys=True)
            + contract
        )

    @staticmethod
    def _validate_artifact_shape(payload: dict[str, Any], contract: dict[str, Any]) -> None:
        required = tuple(str(item) for item in contract.get("required_keys", ()))
        missing = [key for key in required if key not in payload]
        if missing:
            raise ContractError(f"artifact misses required keys: {missing}")
        allowed = set(str(item) for item in contract.get("allowed_keys", required))
        if allowed and set(payload) - allowed:
            raise ContractError(f"artifact has forbidden keys: {sorted(set(payload)-allowed)}")
