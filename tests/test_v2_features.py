from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from primus.domains.base import DomainAdapter, EvaluationOutcome, adapter_for
from primus.errors import ContractError, LifecycleError
from primus.evolution.memory import compile_experiment_lesson
from primus.evolution.portfolio import rank_public_arms
from primus.evolution.search_policy import AdaptiveSearchPolicy
from primus.inner import InnerLoopExecutor
from primus.jsonutil import atomic_json, content_hash
from primus.models import ArmResult, Budget, LoopCall, LoopStructure, RoundStatus, Usage
from primus.orchestrator import PrimusOrchestrator
from primus.stats import judge_paired
from primus.store import PrimusStore


class SemanticAdapter(DomainAdapter):
    def artifact_text(self, payload: dict) -> str:
        return json.dumps(payload, sort_keys=True)

    def evaluate(self, **_: object) -> EvaluationOutcome:
        return EvaluationOutcome(True, 1.0, None, (), {}, "ok")


def _semantic_adapter(tmp_path: Path) -> SemanticAdapter:
    public = tmp_path / "public.json"
    hidden = tmp_path / "hidden.json"
    task = tmp_path / "task.md"
    task.write_text("task", encoding="utf-8")
    atomic_json(public, {
        "domain": "demo", "split": "development",
        "cases": [{"id": "public", "request": "public"}],
    })
    atomic_json(hidden, {
        "domain": "demo", "split": "certification",
        "cases": [
            {"id": "secret-a", "request": "alpha"},
            {"id": "secret-b", "request": "beta"},
        ],
    })
    config = SimpleNamespace(
        id="demo",
        adapter=f"{__name__}:SemanticAdapter",
        artifact_scope="task_local",
        public_task=task,
        public_taskset=public,
        certification_taskset=hidden,
        evaluator={},
    )
    system = SimpleNamespace(root=tmp_path)
    loaded = adapter_for(system, config)
    assert isinstance(loaded, SemanticAdapter)
    return loaded


def test_dynamic_adapter_and_semantic_identity_ignore_ids_and_order(tmp_path: Path) -> None:
    adapter = _semantic_adapter(tmp_path)
    first = adapter.semantic_selection_digest("certification", [1, 2])
    atomic_json(adapter.config.certification_taskset, {
        "domain": "demo", "split": "certification",
        "cases": [
            {"id": "renamed-b", "request": "beta"},
            {"id": "renamed-a", "request": "alpha"},
        ],
    })
    second = adapter.semantic_selection_digest("certification", [1, 2])
    assert first == second

    store = PrimusStore(tmp_path / "state-root")
    store.initialize()
    store.consume_hidden_selection(
        semantic_selection_sha256=first,
        taskset_selection_sha256="display-v1",
        domain="demo",
        run_id="r1",
    )
    with pytest.raises(LifecycleError, match="semantically identical"):
        store.consume_hidden_selection(
            semantic_selection_sha256=second,
            taskset_selection_sha256="display-v2",
            domain="demo",
            run_id="r2",
        )


def _arm(name: str, replicate: int, score: float | None, *, valid: bool, cost: int = 10) -> ArmResult:
    return ArmResult(
        name,
        replicate,
        valid,
        score,
        f"artifact-{name}-{replicate}",
        f"structure-{name}",
        Usage(input_tokens=cost, model_calls=1),
    )


def test_valid_candidate_can_rescue_an_invalid_incumbent() -> None:
    incumbent = [_arm("incumbent", index, None, valid=False) for index in range(1, 4)]
    candidate = [_arm("candidate", index, 0.5, valid=True) for index in range(1, 4)]
    decision = judge_paired(
        incumbent=incumbent,
        candidate=candidate,
        minimum_effect=0.1,
        confidence=0.9,
        bootstrap_samples=100,
        seed="rescue",
        require_confidence=True,
    )
    assert decision.passed
    assert decision.rescue_wins == 3


def test_public_lesson_is_score_free_and_changes_search_policy() -> None:
    receipt = {
        "split": "development",
        "hidden": False,
        "results": [
            {"arm": "incumbent", "replicate": 1, "valid": True, "score": 10.0, "usage": {"effective_tokens": 10}},
            {"arm": "candidate", "replicate": 1, "valid": True, "score": 9.0, "usage": {"effective_tokens": 20}, "failure_class": "budget_overrun"},
        ],
    }
    lesson = compile_experiment_lesson(
        domain="demo",
        run_id="demo-r0001",
        proposal={
            "exploration_operation": "add",
            "changed_factor": "one extra review",
            "hypothesis": "review improves quality",
            "predicted_observation": "fewer errors",
            "protected_behavior": ["one final artifact"],
        },
        public_receipt=receipt,
        public_decision={"passed": False},
    )
    serialized = json.dumps(lesson, sort_keys=True)
    assert "10.0" not in serialized and "9.0" not in serialized
    assert lesson["observations"]["cost_signal"] == "higher"
    policy = AdaptiveSearchPolicy(
        cycle=("open", "add", "delete", "replace", "recombine", "de_novo", "research_transfer"),
        novelty_interval_rounds=5,
    )
    assert policy.choose(round_index=2, lessons=[lesson]) == "delete"


def test_public_portfolio_prefers_valid_quality_then_cost() -> None:
    results = {
        "a": [_arm("a", 1, 0.9, valid=True, cost=30)],
        "b": [_arm("b", 1, 0.9, valid=True, cost=10)],
        "c": [_arm("c", 1, None, valid=False, cost=1)],
    }
    assert rank_public_arms(results, ("a", "b", "c")) == ["b", "a", "c"]


def test_task_local_promotion_changes_harness_not_reference_artifact(tmp_path: Path) -> None:
    store = PrimusStore(tmp_path)
    store.initialize()
    structure = LoopStructure(
        name="one",
        organization="sequential",
        information_flow="one call",
        calls=(LoopCall("emit", "producer", "emit", ("task",), "answer"),),
        final_call_id="emit",
    ).to_dict()
    incumbent = store.import_champion(
        domain="demo",
        champion_id="a",
        structure=structure,
        artifact=b'{"answer":"reference"}',
        active=True,
        source={},
        artifact_scope="task_local",
    )
    run = store.create_round("demo")
    for status in (
        RoundStatus.PLANNED,
        RoundStatus.SCREEN_GENERATED,
        RoundStatus.SCREEN_EVALUATED,
        RoundStatus.SCREEN_PASSED,
        RoundStatus.PROVISIONAL,
        RoundStatus.CERT_GENERATED,
        RoundStatus.HIDDEN_EVALUATED,
        RoundStatus.CERTIFIED,
    ):
        store.transition(run["run_id"], status)
    promoted = store.promote(
        run_id=run["run_id"],
        new_champion_id="b",
        structure={**structure, "name": "two"},
        artifact=None,
        certification_receipt_sha256="hidden",
        decision_sha256="decision",
        artifact_scope="task_local",
    )
    assert promoted["artifact_sha256"] == incumbent["artifact_sha256"]
    assert promoted["artifact_scope"] == "task_local"
    assert store.artifact_versions("demo") == []


class FakeBackend:
    def __init__(self, usage: Usage):
        self.usage = usage
        self.directories: list[Path] = []

    def complete(self, *, working_directory: Path, **_: object) -> SimpleNamespace:
        self.directories.append(working_directory)
        return SimpleNamespace(text='{"answer":"ok"}', usage=self.usage)


def _one_call_loop() -> LoopStructure:
    return LoopStructure(
        name="one",
        organization="sequential",
        information_flow="one call",
        calls=(LoopCall("emit", "producer", "emit", ("task",), "answer"),),
        final_call_id="emit",
    )


def test_inner_loop_uses_isolated_call_workspace_and_enforces_output_budget(tmp_path: Path) -> None:
    backend = FakeBackend(Usage(input_tokens=2, output_tokens=1, model_calls=1))
    executor = InnerLoopExecutor(backend)  # type: ignore[arg-type]
    executor.execute(
        structure=_one_call_loop(),
        task="answer",
        champion_artifact="none",
        champion_metrics={},
        public_audit=[],
        hypothesis={},
        artifact_contract={"required_keys": ["answer"], "allowed_keys": ["answer"]},
        budget=Budget(1, 100, 100, 30, 1),
        working_directory=tmp_path / "valid",
    )
    assert backend.directories[0].name == "workspace"
    assert backend.directories[0].parent.parent.name == "calls"

    excessive = InnerLoopExecutor(FakeBackend(Usage(input_tokens=2, output_tokens=2, model_calls=1)))  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="sealed budget"):
        excessive.execute(
            structure=_one_call_loop(),
            task="answer",
            champion_artifact="none",
            champion_metrics={},
            public_audit=[],
            hypothesis={},
            artifact_contract={"required_keys": ["answer"], "allowed_keys": ["answer"]},
            budget=Budget(1, 100, 100, 30, 1),
            working_directory=tmp_path / "excessive",
        )


def test_deployment_artifact_is_selected_from_public_screening(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    artifact = {"answer": "public winner"}
    atomic_json(run_dir / "screening" / "generation" / "replicate-01" / "candidate" / "artifact.json", artifact)
    result = _arm("candidate", 1, 1.0, valid=True)
    PrimusOrchestrator._seal_public_deployment_artifact(
        run_dir=run_dir, results={"candidate": [result]}
    )
    assert json.loads((run_dir / "screening" / "deployment-artifact.json").read_text()) == artifact
    selection = json.loads((run_dir / "screening" / "deployment-selection.json").read_text())
    assert selection["hidden_evidence_used"] is False
