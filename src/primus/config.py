from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from primus.errors import ContractError
from primus.jsonutil import content_hash, read_json
from primus.models import Budget, ModelPolicy


@dataclass(frozen=True)
class EvaluationConfig:
    screening_replicates: int
    certification_replicates: int
    minimum_effect: float
    confidence: float
    bootstrap_samples: int
    quality_scale: float
    token_penalty_per_1k: float
    call_penalty: float
    invalid_rate_tolerance: float
    control_interval_rounds: int
    control_replicates: int
    quality_non_regression_tolerance: float
    minimum_cost_reduction_ratio: float
    allow_efficiency_promotion: bool

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvaluationConfig":
        result = cls(
            screening_replicates=int(value.get("screening_replicates", value.get("development_replicates", 3))),
            certification_replicates=int(value.get("certification_replicates", 3)),
            minimum_effect=float(value.get("minimum_effect", 0.0)),
            confidence=float(value.get("confidence", 0.95)),
            bootstrap_samples=int(value.get("bootstrap_samples", 5000)),
            quality_scale=float(value.get("quality_scale", 1.0)),
            token_penalty_per_1k=float(value.get("token_penalty_per_1k", 0.0)),
            call_penalty=float(value.get("call_penalty", 0.0)),
            invalid_rate_tolerance=float(value.get("invalid_rate_tolerance", 0.0)),
            control_interval_rounds=int(value.get("control_interval_rounds", 5)),
            control_replicates=int(value.get("control_replicates", 1)),
            quality_non_regression_tolerance=float(value.get("quality_non_regression_tolerance", 0.0)),
            minimum_cost_reduction_ratio=float(value.get("minimum_cost_reduction_ratio", 0.15)),
            allow_efficiency_promotion=bool(value.get("allow_efficiency_promotion", True)),
        )
        if min(result.screening_replicates, result.certification_replicates) < 3:
            raise ContractError("screening and certification each require >=3 paired replicates")
        if result.control_interval_rounds < 0 or result.control_replicates < 1:
            raise ContractError("control scheduling fields are invalid")
        if not 0.5 < result.confidence < 1.0:
            raise ContractError("confidence must be between .5 and 1")
        if result.quality_non_regression_tolerance < 0:
            raise ContractError("quality_non_regression_tolerance cannot be negative")
        if not 0 <= result.minimum_cost_reduction_ratio < 1:
            raise ContractError("minimum_cost_reduction_ratio must be in [0,1)")
        return result


@dataclass(frozen=True)
class ExplorationConfig:
    mode_cycle: tuple[str, ...]
    minimum_research_sources: int
    maximum_research_sources: int
    adaptive: bool
    novelty_interval_rounds: int
    portfolio_size: int
    probe_replicates: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExplorationConfig":
        allowed = {"open", "add", "delete", "replace", "recombine", "de_novo", "research_transfer"}
        cycle = tuple(str(item) for item in value.get(
            "mode_cycle",
            ("open", "add", "delete", "research_transfer", "recombine", "de_novo"),
        ))
        result = cls(
            mode_cycle=cycle,
            minimum_research_sources=int(value.get("minimum_research_sources", 2)),
            maximum_research_sources=int(value.get("maximum_research_sources", 5)),
            adaptive=bool(value.get("adaptive", True)),
            novelty_interval_rounds=int(value.get("novelty_interval_rounds", 5)),
            portfolio_size=int(value.get("portfolio_size", 1)),
            probe_replicates=int(value.get("probe_replicates", 1)),
        )
        if not cycle or set(cycle) - allowed:
            raise ContractError(f"invalid exploration mode cycle: {cycle}")
        if result.minimum_research_sources < 1 or result.maximum_research_sources < result.minimum_research_sources:
            raise ContractError("research source bounds are invalid")
        if result.novelty_interval_rounds < 1:
            raise ContractError("novelty_interval_rounds must be positive")
        if not 1 <= result.portfolio_size <= 8:
            raise ContractError("portfolio_size must be in 1..8")
        if not 1 <= result.probe_replicates <= 3:
            raise ContractError("probe_replicates must be in 1..3")
        return result


@dataclass(frozen=True)
class DomainConfig:
    id: str
    enabled: bool
    adapter: str
    artifact_scope: str
    public_task: Path
    public_taskset: Path
    certification_taskset: Path
    artifact_contract: dict[str, Any]
    budget: Budget
    evaluation: EvaluationConfig
    exploration: ExplorationConfig
    evaluator: dict[str, Any]
    raw: dict[str, Any]

    @property
    def digest(self) -> str:
        return content_hash(self.raw)


@dataclass(frozen=True)
class SystemConfig:
    root: Path
    architect_policy: ModelPolicy
    executor_policy: ModelPolicy
    domains: tuple[str, ...]
    heavy_lock: Path
    raw: dict[str, Any]

    @property
    def digest(self) -> str:
        return content_hash(self.raw)


def _resolve(root: Path, raw: str) -> Path:
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def load_system(root: Path) -> SystemConfig:
    root = root.resolve()
    raw = read_json(root / "config" / "system.json")
    domains = tuple(str(item) for item in raw.get("domains", ()))
    if not domains or len(domains) != len(set(domains)):
        raise ContractError("system domains must be a non-empty unique list")
    invalid = [item for item in domains if re.fullmatch(r"[a-z][a-z0-9_]*", item) is None]
    if invalid:
        raise ContractError(f"invalid domain IDs: {invalid}")
    missing = [item for item in domains if not (root / "config" / "domains" / f"{item}.json").is_file()]
    if missing:
        raise ContractError(f"domain configs are missing: {missing}")
    return SystemConfig(
        root=root,
        architect_policy=ModelPolicy.from_dict(raw["architect_policy"]),
        executor_policy=ModelPolicy.from_dict(raw["executor_policy"]),
        domains=domains,
        heavy_lock=_resolve(root, str(raw.get("heavy_lock", "state/heavy-evaluation.lock"))),
        raw=raw,
    )


def load_domain(root: Path, domain: str) -> DomainConfig:
    root = root.resolve()
    if re.fullmatch(r"[a-z][a-z0-9_]*", domain) is None:
        raise ContractError(f"invalid domain: {domain}")
    path = root / "config" / "domains" / f"{domain}.json"
    if not path.is_file():
        raise ContractError(f"unknown domain: {domain}")
    raw = read_json(path)
    if raw.get("id") != domain:
        raise ContractError(f"domain ID mismatch: {path}")
    public_taskset = _resolve(root, str(raw["public_taskset"] ))
    certification_taskset = _resolve(root, str(raw["certification_taskset"]))
    if public_taskset == certification_taskset:
        raise ContractError("public and certification tasksets must be distinct")
    artifact_scope = str(raw.get("artifact_scope", "domain_lineage"))
    if artifact_scope not in {"domain_lineage", "task_local"}:
        raise ContractError(f"invalid artifact_scope for {domain}: {artifact_scope}")
    return DomainConfig(
        id=domain,
        enabled=bool(raw.get("enabled", True)),
        adapter=str(raw["adapter"]),
        artifact_scope=artifact_scope,
        public_task=_resolve(root, str(raw["public_task"])),
        public_taskset=public_taskset,
        certification_taskset=certification_taskset,
        artifact_contract=dict(raw["artifact_contract"]),
        budget=Budget.from_dict(raw["budget"]),
        evaluation=EvaluationConfig.from_dict(raw["evaluation"]),
        exploration=ExplorationConfig.from_dict(dict(raw.get("exploration", {}))),
        evaluator=dict(raw["evaluator"]),
        raw=raw,
    )
