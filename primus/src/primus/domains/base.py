from __future__ import annotations

import json
import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from primus.config import DomainConfig, SystemConfig
from primus.errors import ContractError
from primus.jsonutil import content_hash, read_json


@dataclass(frozen=True)
class EvaluationOutcome:
    valid: bool
    score: float | None
    failure_class: str | None
    evidence: tuple[str, ...]
    public_feedback: dict[str, str]
    raw_result_sha256: str
    failure_origin: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)


class DomainAdapter(ABC):
    def __init__(self, system: SystemConfig, config: DomainConfig):
        self.system = system
        self.config = config

    def taskset(self, split: str) -> dict[str, Any]:
        path = self.config.public_taskset if split == "development" else self.config.certification_taskset
        value = read_json(path)
        if value.get("domain") != self.config.id or value.get("split") != split:
            raise ContractError(f"taskset identity mismatch: {path}")
        if not isinstance(value.get("cases"), list) or not value["cases"]:
            raise ContractError(f"taskset has no cases: {path}")
        return value

    def taskset_digest(self, split: str) -> str:
        return content_hash(self.taskset(split))

    def case_semantic_payload(self, split: str, replicate: int) -> dict[str, Any]:
        """Return the evaluator-meaningful case identity, excluding display-only IDs."""
        case = self.case_for(split, replicate)
        result = {key: value for key, value in case.items() if key != "id"}
        metadata = result.get("metadata")
        if isinstance(metadata, dict):
            result["metadata"] = {
                key: value
                for key, value in metadata.items()
                if key not in {"result_dir", "benchmark_role"}
            }
        return result

    def case_semantic_digest(self, split: str, replicate: int) -> str:
        return content_hash(self.case_semantic_payload(split, replicate))

    def semantic_selection_digest(self, split: str, replicates: list[int]) -> str:
        taskset = self.taskset(split)
        selection_unit = str(taskset.get("selection_unit", "case"))
        if selection_unit not in {"case", "suite"}:
            raise ContractError(f"invalid selection_unit: {selection_unit}")
        if selection_unit == "suite":
            semantic_cases = sorted({
                self.case_semantic_digest(split, index)
                for index in range(1, len(taskset["cases"]) + 1)
            })
        else:
            # Ordering and display IDs are not new evidence. Sorting prevents a
            # task-bank reorder from bypassing the one-use hidden boundary.
            semantic_cases = sorted(self.case_semantic_digest(split, item) for item in replicates)
        return content_hash({
            "domain": self.config.id,
            "adapter": self.config.adapter,
            "split": split,
            "selection_unit": selection_unit,
            "semantic_cases": semantic_cases,
        })

    def semantic_case_digests(self, split: str) -> set[str]:
        cases = self.taskset(split)["cases"]
        return {self.case_semantic_digest(split, index) for index in range(1, len(cases) + 1)}

    def task_for(self, split: str, replicate: int) -> str:
        cases = self.taskset(split)["cases"]
        case = cases[(replicate - 1) % len(cases)]
        return str(case.get("request") or self.config.public_task.read_text(encoding="utf-8"))

    def case_for(self, split: str, replicate: int) -> dict[str, Any]:
        cases = self.taskset(split)["cases"]
        return dict(cases[(replicate - 1) % len(cases)])

    def anchor_text(self, payload: dict[str, Any], split: str, replicate: int) -> str:
        if self.config.artifact_scope == "task_local":
            case = self.case_for(split, replicate)
            anchor = case.get("anchor_artifact")
            if anchor is None:
                return "No prior task-local artifact exists. Solve this task independently."
            return json.dumps(anchor, ensure_ascii=False, sort_keys=True)
        return self.artifact_text(payload)

    def decode_reference_artifact(self, raw: bytes) -> dict[str, Any]:
        value = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise ContractError("reference artifact must decode to an object")
        return value

    def smoke_payload(self, reference_payload: dict[str, Any]) -> dict[str, Any] | None:
        configured = self.config.evaluator.get("smoke_payload")
        if isinstance(configured, dict):
            return dict(configured)
        if self.config.artifact_scope == "domain_lineage":
            return reference_payload
        return None

    @abstractmethod
    def artifact_text(self, payload: dict[str, Any]) -> str:
        """Return the incumbent-visible artifact representation."""

    @abstractmethod
    def evaluate(
        self,
        *,
        payload: dict[str, Any],
        split: str,
        replicate: int,
        output_directory: Path,
    ) -> EvaluationOutcome: ...


def adapter_for(system: SystemConfig, config: DomainConfig) -> DomainAdapter:
    builtins = {
        "chess": "primus.domains.chess:ChessAdapter",
        "cache": "primus.domains.cache:CacheAdapter",
        "coding": "primus.domains.coding:CodingAdapter",
        "reasoning_tools": "primus.domains.reasoning_tools:ReasoningToolsAdapter",
    }
    specification = builtins.get(config.adapter, config.adapter)
    if ":" not in specification:
        raise ContractError(f"adapter must be a builtin name or module:Class: {config.adapter}")
    module_name, class_name = specification.split(":", 1)
    try:
        module = importlib.import_module(module_name)
        adapter_type = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ContractError(f"cannot load adapter: {specification}") from exc
    if not isinstance(adapter_type, type) or not issubclass(adapter_type, DomainAdapter):
        raise ContractError(f"adapter is not a DomainAdapter: {specification}")
    return adapter_type(system, config)


def files_payload(payload: dict[str, Any], *, only: str | None = None) -> dict[str, str]:
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise ContractError("artifact must contain a non-empty files object")
    normalized: dict[str, str] = {}
    for name, content in files.items():
        if not isinstance(name, str) or not isinstance(content, str) or not content.strip():
            raise ContractError("artifact files must map paths to non-empty strings")
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ContractError(f"artifact path is unsafe: {name}")
        normalized[path.as_posix()] = content
    if only is not None and set(normalized) != {only}:
        raise ContractError(f"artifact must contain only {only}")
    return normalized
