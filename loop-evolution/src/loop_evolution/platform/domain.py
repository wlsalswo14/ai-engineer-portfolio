from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any

from loop_evolution.platform.common import content_hash, freeze_mapping


class Environment(StrEnum):
    TEXT_ONLY = "text_only"
    EXECUTABLE = "executable"
    STRUCTURED_DATA = "structured_data"
    FORMAL_STATE = "formal_state"
    EXTERNAL_WORLD = "external_world"


class Oracle(StrEnum):
    EXACT = "exact"
    SCHEMA = "schema"
    EXECUTABLE_TEST = "executable_test"
    STATE_TRANSITION = "state_transition"
    EVIDENCE = "evidence"
    HUMAN_ONLY = "human_only"


class Uncertainty(StrEnum):
    LOW = "low"
    AMBIGUOUS = "ambiguous"
    OPEN_ENDED = "open_ended"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class Risk(StrEnum):
    REVERSIBLE = "reversible"
    COSTLY = "costly"
    SAFETY_CRITICAL = "safety_critical"
    IRREVERSIBLE = "irreversible"


class ResourceEnvelope(StrEnum):
    INSTANT = "instant"
    BOUNDED = "bounded"
    DELIBERATIVE = "deliberative"
    LONG_HORIZON = "long_horizon"


class CoverageStatus(StrEnum):
    VERIFIED = "VERIFIED"
    EVIDENCE_BOUND = "EVIDENCE_BOUND"
    UNVERIFIABLE = "UNVERIFIABLE"
    UNSUPPORTED = "UNSUPPORTED"


class CandidateState(StrEnum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    SHADOW_RUNNING = "SHADOW_RUNNING"
    SCREEN_REJECTED = "SCREEN_REJECTED"
    DEV_REJECTED = "DEV_REJECTED"
    DEV_ADMITTED = "DEV_ADMITTED"
    ARCHIVED = "ARCHIVED"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASE_REJECTED = "RELEASE_REJECTED"
    CERTIFIED = "CERTIFIED"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"
    RETIRED = "RETIRED"

    @classmethod
    def allowed_successors(cls, state: CandidateState) -> frozenset[CandidateState]:
        return {
            cls.DRAFT: frozenset({cls.SEALED}),
            cls.SEALED: frozenset({cls.SHADOW_RUNNING}),
            cls.SHADOW_RUNNING: frozenset({cls.SCREEN_REJECTED, cls.DEV_REJECTED, cls.DEV_ADMITTED}),
            cls.DEV_ADMITTED: frozenset({cls.ARCHIVED}),
            cls.ARCHIVED: frozenset({cls.RELEASE_PENDING, cls.RETIRED}),
            cls.RELEASE_PENDING: frozenset({cls.RELEASE_REJECTED, cls.CERTIFIED}),
            cls.RELEASE_REJECTED: frozenset({cls.CERTIFIED, cls.RETIRED}),
            cls.CERTIFIED: frozenset({cls.PROMOTED, cls.RETIRED}),
            cls.PROMOTED: frozenset({cls.ROLLED_BACK, cls.RETIRED}),
        }.get(state, frozenset())


class MutationKind(StrEnum):
    ADD = "add"
    DELETE = "delete"
    REPLACE = "replace"
    REORDER = "reorder"
    CONFIG = "config"
    ROUTE = "route"
    PROMPT = "prompt"


class RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INCONCLUSIVE_QUOTA = "INCONCLUSIVE_QUOTA"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class TaskProfile:
    goal: str
    environment: Environment
    oracle: Oracle
    uncertainty: Uncertainty
    risk: Risk
    resource_envelope: ResourceEnvelope
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_mapping(dict(self.metadata)))


@dataclass(frozen=True)
class CoverageDecision:
    status: CoverageStatus
    solve: bool
    verify: bool
    recover: bool
    stop: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityContract:
    capability_id: str
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    allowed_tools: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ("stop",)


@dataclass(frozen=True)
class TypedArtifact:
    artifact_type: str
    value: Any
    producer: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProtocolMotif:
    motif_id: str
    steps: tuple[str, ...]
    supported_oracles: tuple[Oracle, ...]
    max_model_calls: int
    description: str
    max_tokens: int = 64_000
    timeout_seconds: int = 900
    recover_conditions: tuple[str, ...] = ("bounded_failure",)
    stop_conditions: tuple[str, ...] = ("decision", "budget_exhausted", "unsupported")


@dataclass(frozen=True)
class ExecutionGraph:
    graph_id: str
    parent_id: str | None
    motif_id: str
    steps: tuple[str, ...]
    config: dict[str, Any]
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", freeze_mapping(dict(self.config)))

    @classmethod
    def create(
        cls,
        *,
        motif_id: str,
        steps: tuple[str, ...],
        config: dict[str, Any] | None = None,
        parent_id: str | None = None,
        version: int = 1,
    ) -> ExecutionGraph:
        payload = {
            "parent_id": parent_id,
            "motif_id": motif_id,
            "steps": steps,
            "config": dict(config or {}),
            "version": version,
        }
        return cls(
            graph_id=f"graph_{content_hash(payload)[:16]}",
            parent_id=parent_id,
            motif_id=motif_id,
            steps=steps,
            config=dict(config or {}),
            version=version,
        )

    def with_identity(self) -> ExecutionGraph:
        return ExecutionGraph.create(
            motif_id=self.motif_id,
            steps=self.steps,
            config=self.config,
            parent_id=self.parent_id,
            version=self.version,
        )


@dataclass(frozen=True)
class ChangeSet:
    kind: MutationKind
    target: str
    before: Any
    after: Any
    rationale: str


@dataclass(frozen=True)
class CandidateManifest:
    candidate_id: str
    parent_graph_id: str
    candidate_graph: ExecutionGraph
    changes: tuple[ChangeSet, ...]
    hypothesis: str
    falsification_test: str
    state: CandidateState = CandidateState.DRAFT
    expected_cost_delta: dict[str, float] = field(default_factory=dict)
    profile_predicate: dict[str, str] = field(default_factory=dict)
    package_id: str = ""
    cohesion_statement: str = ""
    proposer_model: str = ""
    proposer_reasoning_effort: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_cost_delta", freeze_mapping(dict(self.expected_cost_delta)))
        object.__setattr__(self, "profile_predicate", freeze_mapping(dict(self.profile_predicate)))

    @property
    def content_sha256(self) -> str:
        return content_hash(asdict(self))

    def transition(self, state: CandidateState) -> CandidateManifest:
        if state not in CandidateState.allowed_successors(self.state):
            raise ValueError(f"illegal candidate transition: {self.state.value} -> {state.value}")
        return replace(self, state=state)


@dataclass(frozen=True)
class EvaluationManifest:
    evaluation_epoch: str
    model: str
    reasoning_effort: str
    task_ids: tuple[str, ...]
    seeds: tuple[int, ...]
    max_model_calls: int
    max_tokens: int
    evaluator_version: str
    stage: str = "development"
    max_wall_seconds: int = 900
    schema_version: int = 1
    auth_mode: str = "codex_subscription"
    sandbox: str = "read-only"
    service_tier: str = "codex_quota"
    allow_paid_api: bool = False
    allow_model_fallback: bool = False

    @property
    def content_sha256(self) -> str:
        return content_hash(asdict(self))


@dataclass(frozen=True)
class ScoreVector:
    quality: float
    safety: float
    robustness: float
    efficiency: float
    latency_ms: float
    model_calls: int
    tokens: int
    complexity: float = 0.0


@dataclass(frozen=True)
class EvaluationReport:
    candidate_id: str
    graph_id: str
    score: ScoreVector
    valid: bool
    violations: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    case_results: tuple[CaseResult, ...] = ()
    evaluation_epoch: str = ""
    complete: bool = True
    stop_reason: str = ""

    @property
    def content_sha256(self) -> str:
        return content_hash(asdict(self))


@dataclass(frozen=True)
class PromotionCertificate:
    certificate_id: str
    parent_graph_id: str
    candidate_graph_id: str
    evaluation_epoch: str
    approved: bool
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    signature: str = ""
    reverse_ablation_confirmed: bool = False
    manifest_sha256: str = ""
    parent_report_sha256: str = ""
    candidate_report_sha256: str = ""
    promotion_target: str = "global"


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    model_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def budget_tokens(self) -> int:
        """Tokens charged to the run budget, excluding reused cached input."""
        uncached_input = max(0, self.input_tokens - self.cached_input_tokens)
        return uncached_input + self.output_tokens

    def __add__(self, other: ModelUsage) -> ModelUsage:
        return ModelUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens + other.reasoning_output_tokens,
            model_calls=self.model_calls + other.model_calls,
        )


@dataclass(frozen=True)
class StepTrace:
    sequence: int
    step: str
    status: str
    input_sha256: str
    output_sha256: str
    usage: ModelUsage
    latency_ms: float
    error: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    run_id: str
    graph_id: str
    output: str
    status: RunStatus
    stop_reason: str
    traces: tuple[StepTrace, ...]
    usage: ModelUsage
    latency_ms: float
    evaluation_seed: int | None = None
    profile: TaskProfile | None = None
    coverage: CoverageDecision | None = None
    selected_harness: str = ""
    planner_source: str = ""
    planner_confidence: float = 0.0
    planner_reasons: tuple[str, ...] = ()
    planner_fallback_used: bool = False
    planner_policy_id: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", freeze_mapping(dict(self.artifacts)))


@dataclass(frozen=True)
class TaskCase:
    task_id: str
    family: str
    request: str
    expected: Any
    scorer: str
    critical: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_mapping(dict(self.metadata)))


@dataclass(frozen=True)
class CaseResult:
    task_id: str
    family: str
    passed: bool
    score: float
    critical: bool
    output_sha256: str
    status: RunStatus
    usage: ModelUsage
    latency_ms: float
    failure_kind: str | None = None
    run_id: str = ""
    traces: tuple[StepTrace, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    profile: TaskProfile | None = None
    coverage: CoverageDecision | None = None
    selected_harness: str = ""
    planner_source: str = ""
    planner_confidence: float = 0.0
    planner_reasons: tuple[str, ...] = ()
    planner_fallback_used: bool = False
    planner_policy_id: str = ""
    raw_output: str = ""


@dataclass(frozen=True)
class ExecutionLimits:
    max_model_calls: int
    max_tokens: int
    max_wall_seconds: int

    def validate(self) -> None:
        if min(self.max_model_calls, self.max_tokens, self.max_wall_seconds) <= 0:
            raise ValueError("execution limits must be positive")
