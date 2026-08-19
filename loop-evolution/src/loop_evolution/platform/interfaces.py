from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loop_evolution.platform.domain import (
    CandidateManifest,
    CoverageDecision,
    EvaluationManifest,
    EvaluationReport,
    ExecutionGraph,
    ModelUsage,
    PromotionCertificate,
    ProtocolMotif,
    TaskProfile,
)


@dataclass(frozen=True)
class ModelResponse:
    text: str
    usage: ModelUsage = ModelUsage(model_calls=1)
    trace_refs: tuple[str, ...] = ()


class ModelBackend(Protocol):
    def complete(self, *, role: str, prompt: str, working_directory: str) -> ModelResponse: ...


class ToolAwareModelBackend(Protocol):
    def complete_with_tools(
        self,
        *,
        role: str,
        prompt: str,
        working_directory: str,
        allowed_tools: tuple[str, ...],
        timeout_seconds: float,
    ) -> ModelResponse: ...


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    feedback: str
    evidence_refs: tuple[str, ...] = ()


class Verifier(Protocol):
    def verify(self, *, profile: TaskProfile, output: str, working_directory: str) -> VerificationResult: ...


class TaskFingerprinter(Protocol):
    def classify(self, request: str) -> TaskProfile: ...


class CoverageService(Protocol):
    def resolve(self, profile: TaskProfile) -> CoverageDecision: ...


class ProtocolComposer(Protocol):
    def compose(self, profile: TaskProfile, coverage: CoverageDecision) -> ProtocolMotif: ...


class CandidateFactory(Protocol):
    def propose(self, parent: ExecutionGraph, hypothesis: str) -> tuple[CandidateManifest, ...]: ...


class Evaluator(Protocol):
    def evaluate(self, graph: ExecutionGraph, manifest: EvaluationManifest) -> EvaluationReport: ...


class PromotionAuthority(Protocol):
    def certify(
        self,
        *,
        parent: EvaluationReport,
        candidate: EvaluationReport,
        manifest: EvaluationManifest,
    ) -> PromotionCertificate: ...
