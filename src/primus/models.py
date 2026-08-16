from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from primus.errors import ContractError
from primus.jsonutil import content_hash


# Kept as a compatibility alias for existing imports and inaugural migration.
# Runtime domain discovery is configuration-driven in primus.config.
BUILTIN_DOMAINS = ("chess", "cache", "coding", "reasoning_tools")
DOMAINS = BUILTIN_DOMAINS


class FailureOrigin(StrEnum):
    CANDIDATE = "candidate"
    INFRASTRUCTURE = "infrastructure"


class RoundStatus(StrEnum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    SCREEN_GENERATED = "SCREEN_GENERATED"
    SCREEN_EVALUATED = "SCREEN_EVALUATED"
    SCREEN_PASSED = "SCREEN_PASSED"
    # Legacy v2 names remain readable for rounds created before direct comparison.
    ABLATION_GENERATED = "ABLATION_GENERATED"
    ATTRIBUTION_EVALUATED = "ATTRIBUTION_EVALUATED"
    CERT_GENERATED = "CERT_GENERATED"
    # Legacy v1 names remain readable for already-started rounds.
    GENERATED_DEV = "GENERATED_DEV"
    PUBLIC_EVALUATED = "PUBLIC_EVALUATED"
    PROVISIONAL = "PROVISIONAL"
    GENERATED_CERT = "GENERATED_CERT"
    HIDDEN_EVALUATED = "HIDDEN_EVALUATED"
    CERTIFIED = "CERTIFIED"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    FALSIFIED = "FALSIFIED"
    UNRESOLVED = "UNRESOLVED"


TERMINAL_STATUSES = {
    RoundStatus.PROMOTED,
    RoundStatus.REJECTED,
    RoundStatus.FALSIFIED,
    RoundStatus.UNRESOLVED,
}


ALLOWED_TRANSITIONS: dict[RoundStatus, set[RoundStatus]] = {
    RoundStatus.CREATED: {RoundStatus.PLANNED, RoundStatus.REJECTED},
    RoundStatus.PLANNED: {RoundStatus.SCREEN_GENERATED, RoundStatus.GENERATED_DEV, RoundStatus.REJECTED, RoundStatus.UNRESOLVED},
    RoundStatus.SCREEN_GENERATED: {RoundStatus.SCREEN_EVALUATED, RoundStatus.UNRESOLVED},
    RoundStatus.SCREEN_EVALUATED: {RoundStatus.SCREEN_PASSED, RoundStatus.REJECTED, RoundStatus.FALSIFIED},
    RoundStatus.SCREEN_PASSED: {RoundStatus.PROVISIONAL, RoundStatus.UNRESOLVED},
    RoundStatus.ABLATION_GENERATED: {RoundStatus.ATTRIBUTION_EVALUATED, RoundStatus.UNRESOLVED},
    RoundStatus.ATTRIBUTION_EVALUATED: {RoundStatus.PROVISIONAL, RoundStatus.REJECTED, RoundStatus.FALSIFIED},
    RoundStatus.GENERATED_DEV: {RoundStatus.PUBLIC_EVALUATED, RoundStatus.UNRESOLVED},
    RoundStatus.PUBLIC_EVALUATED: {RoundStatus.PROVISIONAL, RoundStatus.REJECTED, RoundStatus.FALSIFIED},
    RoundStatus.PROVISIONAL: {RoundStatus.CERT_GENERATED, RoundStatus.GENERATED_CERT, RoundStatus.UNRESOLVED},
    RoundStatus.CERT_GENERATED: {RoundStatus.HIDDEN_EVALUATED, RoundStatus.UNRESOLVED},
    RoundStatus.GENERATED_CERT: {RoundStatus.HIDDEN_EVALUATED, RoundStatus.UNRESOLVED},
    RoundStatus.HIDDEN_EVALUATED: {RoundStatus.CERTIFIED, RoundStatus.FALSIFIED, RoundStatus.REJECTED},
    RoundStatus.CERTIFIED: {RoundStatus.PROMOTED},
}


@dataclass(frozen=True)
class Budget:
    max_calls: int
    max_total_tokens: int
    max_effective_tokens: int
    max_wall_seconds: int
    max_output_tokens: int = 0

    def validate(self) -> None:
        if min(self.max_calls, self.max_total_tokens, self.max_effective_tokens, self.max_wall_seconds) <= 0:
            raise ContractError("all primary budget fields must be positive")
        if self.max_output_tokens < 0:
            raise ContractError("max_output_tokens cannot be negative")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Budget":
        result = cls(**{key: int(value.get(key, 0)) for key in cls.__dataclass_fields__})
        result.validate()
        return result


@dataclass(frozen=True)
class ModelPolicy:
    model: str
    reasoning_effort: str
    service_tier: str
    request_tier: str = "priority"
    max_wall_seconds: int = 1800
    codex_executable: str = "codex.cmd"
    codex_home_pool: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelPolicy":
        result = cls(
            model=str(value["model"]),
            reasoning_effort=str(value["reasoning_effort"]),
            service_tier=str(value["service_tier"]),
            request_tier=str(value.get("request_tier", "priority")),
            max_wall_seconds=int(value.get("max_wall_seconds", 1800)),
            codex_executable=str(value.get("codex_executable", "codex.cmd")),
            codex_home_pool=tuple(str(item) for item in value.get("codex_home_pool", ())),
        )
        if result.service_tier.casefold() != "fast" or result.request_tier.casefold() != "priority":
            raise ContractError("Primus requires Fast/priority model policy")
        return result


@dataclass(frozen=True)
class LoopCall:
    id: str
    role: str
    objective: str
    inputs: tuple[str, ...]
    output_type: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LoopCall":
        call = cls(
            id=str(value["id"]),
            role=str(value["role"]),
            objective=str(value["objective"]),
            inputs=tuple(str(item) for item in value.get("inputs", ())),
            output_type=str(value["output_type"]),
        )
        if not call.id or not call.role or not call.objective:
            raise ContractError("loop call fields cannot be empty")
        return call


@dataclass(frozen=True)
class LoopStructure:
    name: str
    organization: str
    information_flow: str
    calls: tuple[LoopCall, ...]
    final_call_id: str
    changed_factor: str = "bootstrap"
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def structure_id(self) -> str:
        return f"loop_{content_hash(self.to_dict(include_id=False))[:16]}"

    def validate(self, *, max_calls: int) -> None:
        if not self.name or not self.calls:
            raise ContractError("loop structure requires a name and calls")
        if len(self.calls) > max_calls:
            raise ContractError(f"loop exceeds call budget: {len(self.calls)} > {max_calls}")
        ids = [call.id for call in self.calls]
        if len(ids) != len(set(ids)):
            raise ContractError("loop call IDs must be unique")
        if ids[-1] != self.final_call_id:
            raise ContractError("final_call_id must be the last sequential call")
        available = {"task", "champion_artifact", "champion_metrics", "public_audit", "hypothesis", "loop_structure"}
        for call in self.calls:
            unknown = set(call.inputs) - available
            if unknown:
                raise ContractError(f"call {call.id} has unavailable inputs: {sorted(unknown)}")
            available.add(call.id)
        if self.calls[-1].output_type not in {"artifact", "engine", "policy", "patch", "answer", "tool_trace"}:
            raise ContractError("final call must emit a domain artifact")

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        value = {
            "name": self.name,
            "organization": self.organization,
            "information_flow": self.information_flow,
            "calls": [asdict(call) for call in self.calls],
            "final_call_id": self.final_call_id,
            "changed_factor": self.changed_factor,
            "provenance": self.provenance,
        }
        if include_id:
            value["structure_id"] = self.structure_id
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LoopStructure":
        calls: list[LoopCall] = []
        if "calls" in value:
            calls = [LoopCall.from_dict(item) for item in value["calls"]]
        else:
            for stage in value.get("stages", []):
                calls.extend(LoopCall.from_dict(item) for item in stage.get("calls", []))
        result = cls(
            name=str(value["name"]),
            organization=str(value.get("organization", "sequential")),
            information_flow=str(value.get("information_flow", "")),
            calls=tuple(calls),
            final_call_id=str(value["final_call_id"]),
            changed_factor=str(value.get("changed_factor") or value.get("hypothesis", {}).get("causal_change", {}).get("factor", "legacy")),
            provenance=dict(value.get("provenance", {})),
        )
        return result


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    model_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def effective_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens) + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(**{name: getattr(self, name) + getattr(other, name) for name in self.__dataclass_fields__})

    def to_dict(self) -> dict[str, int]:
        value = asdict(self)
        value.update(total_tokens=self.total_tokens, effective_tokens=self.effective_tokens)
        return value


@dataclass(frozen=True)
class ArmResult:
    arm: str
    replicate: int
    valid: bool
    score: float | None
    artifact_sha256: str
    structure_sha256: str
    usage: Usage
    failure_class: str | None = None
    evidence: tuple[str, ...] = ()
    failure_origin: str | None = None
    raw_result_sha256: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    case_fingerprint: str = ""
    case_family: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["usage"] = self.usage.to_dict()
        return value


@dataclass(frozen=True)
class PairedDecision:
    passed: bool
    wins: int
    losses: int
    ties: int
    candidate_median: float | None
    incumbent_median: float | None
    median_delta: float | None
    mean_delta: float | None
    lower_confidence_delta: float | None
    invalid_candidate: int
    invalid_incumbent: int
    cost_delta_effective_tokens: int
    reasons: tuple[str, ...]
    rescue_wins: int = 0
    both_invalid: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
