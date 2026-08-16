from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from primus.backend import CodexBackend
from primus.domains.base import EvaluationOutcome
from primus.errors import ContractError, IntegrityError
from primus.evaluation import TournamentEvaluator
from primus.inner import GeneratedArtifact
from primus.jsonutil import atomic_json, bytes_hash, content_hash
from primus.models import LoopCall, LoopStructure, ModelPolicy, RoundStatus, Usage
from primus.outer import ExternalArchitect, PublicFeedbackCompiler
from primus.store import PrimusStore


def _loop(name: str) -> LoopStructure:
    return LoopStructure(
        name=name,
        organization="sequential",
        information_flow="one producer",
        calls=(LoopCall("emit", "producer", "emit answer", ("task",), "answer"),),
        final_call_id="emit",
        changed_factor=name,
    )


class FakeExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, *, structure: LoopStructure, working_directory: Path, **_: object) -> GeneratedArtifact:
        self.calls += 1
        payload = {"answer": structure.name, "tool_trace": []}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        usage = Usage(input_tokens=10, output_tokens=2, model_calls=1)
        atomic_json(working_directory / "artifact.json", payload)
        atomic_json(working_directory / "generation-manifest.json", {
            "artifact_sha256": bytes_hash(raw), "usage": usage.to_dict(), "call_receipts": []
        })
        return GeneratedArtifact(payload, raw, usage, bytes_hash(raw), ())


class FakeAdapter:
    def __init__(self, stage_root: Path, expected_manifests: int):
        self.stage_root = stage_root
        self.expected_manifests = expected_manifests
        self.evaluations = 0

    def artifact_text(self, payload: dict) -> str:
        return json.dumps(payload)

    def taskset(self, split: str) -> dict:
        return {"domain": "reasoning_tools", "split": split, "cases": [self.case_for(split, i) for i in range(1, 10)]}

    def task_for(self, split: str, replicate: int) -> str:
        return f"task-{split}-{replicate}"

    def case_for(self, split: str, replicate: int) -> dict:
        return {"id": f"{split}-{replicate}", "request": f"task-{replicate}"}

    def evaluate(self, *, payload: dict, split: str, replicate: int, output_directory: Path) -> EvaluationOutcome:
        assert len(list((self.stage_root / "generation").rglob("generation-manifest.json"))) == self.expected_manifests
        assert (self.stage_root / "pre-evaluation-seal.json").is_file()
        self.evaluations += 1
        score = 2.0 if payload["answer"] == "candidate" else 1.0
        return EvaluationOutcome(True, score, None, ("fake",), {}, content_hash(payload))


def test_all_stage_arms_are_sealed_before_evaluation_and_resume_is_idempotent(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    executor = FakeExecutor()
    adapter = FakeAdapter(stage, expected_manifests=6)
    evaluation = SimpleNamespace(
        token_penalty_per_1k=0.0,
        call_penalty=0.0,
        minimum_effect=0.0,
        confidence=0.9,
        bootstrap_samples=100,
        invalid_rate_tolerance=0.0,
    )
    config = SimpleNamespace(
        evaluation=evaluation,
        budget=SimpleNamespace(),
        artifact_contract={"required_keys": ["answer", "tool_trace"], "allowed_keys": ["answer", "tool_trace"]},
    )
    system = SimpleNamespace(heavy_lock=tmp_path / "heavy.lock")
    tournament = TournamentEvaluator(system=system, config=config, adapter=adapter, executor=executor)
    presealed = []
    results, receipt = tournament.run_stage(
        run_id="reasoning-r0001",
        round_index=1,
        split="development",
        stage="screening",
        replicates=3,
        structures={"incumbent": _loop("incumbent"), "candidate": _loop("candidate")},
        incumbent_payload={"answer": "anchor", "tool_trace": []},
        incumbent_metrics={},
        public_audit=[],
        hypothesis={},
        working_directory=stage,
        on_presealed=lambda value: presealed.append(value["preseal_sha256"]),
    )
    assert len(presealed) == 1
    assert executor.calls == 6 and adapter.evaluations == 6
    assert [item.score for item in results["candidate"]] == [2.0, 2.0, 2.0]
    resumed, resumed_receipt = tournament.run_stage(
        run_id="reasoning-r0001",
        round_index=1,
        split="development",
        stage="screening",
        replicates=3,
        structures={"incumbent": _loop("incumbent"), "candidate": _loop("candidate")},
        incumbent_payload={"answer": "anchor", "tool_trace": []},
        incumbent_metrics={}, public_audit=[], hypothesis={}, working_directory=stage,
    )
    assert executor.calls == 6 and adapter.evaluations == 6
    assert resumed_receipt == receipt and len(resumed["candidate"]) == 3


def test_existing_preseal_cannot_be_silently_rewritten(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir(parents=True)
    (stage / "pre-evaluation-seal.json").write_text('{"tampered":true}\n', encoding="utf-8")
    executor = FakeExecutor()
    adapter = FakeAdapter(stage, expected_manifests=6)
    evaluation = SimpleNamespace(
        token_penalty_per_1k=0.0,
        call_penalty=0.0,
        minimum_effect=0.0,
        confidence=0.9,
        bootstrap_samples=100,
        invalid_rate_tolerance=0.0,
    )
    config = SimpleNamespace(
        evaluation=evaluation,
        budget=SimpleNamespace(),
        artifact_contract={"required_keys": ["answer", "tool_trace"], "allowed_keys": ["answer", "tool_trace"]},
    )
    tournament = TournamentEvaluator(
        system=SimpleNamespace(heavy_lock=tmp_path / "heavy.lock"),
        config=config,
        adapter=adapter,
        executor=executor,
    )
    with pytest.raises(IntegrityError, match="immutable object differs"):
        tournament.run_stage(
            run_id="reasoning-r0001",
            round_index=1,
            split="development",
            stage="screening",
            replicates=3,
            structures={"incumbent": _loop("incumbent"), "candidate": _loop("candidate")},
            incumbent_payload={"answer": "anchor", "tool_trace": []},
            incumbent_metrics={},
            public_audit=[],
            hypothesis={},
            working_directory=stage,
        )


def test_new_lifecycle_goes_directly_from_public_win_to_provisional(tmp_path: Path) -> None:
    store = PrimusStore(tmp_path)
    store.initialize()
    store.import_champion(
        domain="cache", champion_id="a", structure=_loop("a").to_dict(), artifact=b"x", active=True, source={}
    )
    run = store.create_round("cache")
    store.transition(run["run_id"], RoundStatus.PLANNED)
    store.transition(run["run_id"], RoundStatus.SCREEN_GENERATED)
    store.transition(run["run_id"], RoundStatus.SCREEN_EVALUATED)
    with pytest.raises(Exception):
        store.transition(run["run_id"], RoundStatus.PROVISIONAL)
    store.transition(run["run_id"], RoundStatus.SCREEN_PASSED)
    with pytest.raises(Exception):
        store.transition(run["run_id"], RoundStatus.ABLATION_GENERATED)
    store.transition(run["run_id"], RoundStatus.PROVISIONAL)
    store.transition(run["run_id"], RoundStatus.CERT_GENERATED)
    store.transition(run["run_id"], RoundStatus.HIDDEN_EVALUATED)
    store.transition(run["run_id"], RoundStatus.CERTIFIED)
    assert store.round(run["run_id"])["status"] == "CERTIFIED"


def test_schema_v5_keeps_legacy_attribution_column_readable(tmp_path: Path) -> None:
    store = PrimusStore(tmp_path)
    store.initialize()
    with store.connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(rounds)")}
        version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert "attribution_receipt_sha256" in columns
    assert version == "5"


def test_research_transfer_can_create_a_nonlocal_topology() -> None:
    incumbent = _loop("incumbent")
    structure = {
        "name": "researched two-call topology",
        "organization": "sequential",
        "information_flow": "audit then produce",
        "changed_factor": "source-grounded audit before production",
        "calls": [
            {"id": "audit", "role": "auditor", "objective": "audit", "inputs": ["task"], "output_type": "analysis"},
            {"id": "emit", "role": "producer", "objective": "emit", "inputs": ["task", "audit"], "output_type": "answer"},
        ],
        "final_call_id": "emit",
    }
    raw = {
        "observed_bottleneck": "local search",
        "hypothesis": "a researched audit topology improves reliability",
        "changed_factor": "source-grounded audit before production",
        "predicted_observation": "fewer contract failures",
        "falsifier": "no matched improvement",
        "protected_behavior": ["one final answer"],
        "exploration_operation": "research_transfer",
        "research_sources": [{
            "title": "Example paper",
            "url": "https://arxiv.org/abs/0000.00000",
            "kind": "paper",
            "structural_insight": "separate audit from production",
            "license_or_terms": "not_applicable_idea_only",
        }],
        "candidate_structure": structure,
    }
    proposal = ExternalArchitect._parse(
        raw,
        max_calls=4,
        incumbent=incumbent,
        exploration_mode="research_transfer",
        minimum_research_sources=1,
        maximum_research_sources=3,
    )
    assert len(proposal.candidate.calls) == 2
    assert proposal.exploration_operation == "research_transfer"
    assert proposal.candidate.provenance["external_ideas_only"] is True


def test_web_search_is_enabled_only_for_the_architect_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    policy = ModelPolicy("gpt-5.6-sol", "max", "fast")
    offline = CodexBackend(policy)
    online = CodexBackend(policy, allow_web_search=True)
    monkeypatch.setattr(offline, "_launcher", lambda: ("codex",))
    monkeypatch.setattr(online, "_launcher", lambda: ("codex",))
    offline_command = offline._command(tmp_path)
    online_command = online._command(tmp_path)
    assert "--search" not in offline_command and 'web_search="disabled"' in offline_command
    assert "--search" in online_command and 'web_search="disabled"' not in online_command

    events = "\n".join([
        json.dumps({"type": "item.completed", "item": {"type": "web_search_call"}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}}),
        json.dumps({"type": "turn.completed", "usage": {}}),
    ])
    assert CodexBackend._parse(events, 0).web_search_calls == 1


def test_public_feedback_reports_relative_regression_without_leaking_scores() -> None:
    receipt = {
        "split": "development",
        "hidden": False,
        "results": [
            {"arm": "incumbent", "replicate": 1, "valid": True, "score": 10.0},
            {"arm": "candidate", "replicate": 1, "valid": True, "score": 9.0},
        ],
    }
    feedback = PublicFeedbackCompiler.compile(domain="chess", public_receipt=receipt)
    assert feedback["audit_examples"][0]["failure_class"] == "public_relative_regression"
    assert "10.0" not in json.dumps(feedback) and "9.0" not in json.dumps(feedback)


def test_candidate_must_differ_executably_from_incumbent() -> None:
    incumbent = _loop("incumbent")
    raw = {
        "observed_bottleneck": "no change",
        "hypothesis": "labels alone help",
        "changed_factor": "labels",
        "predicted_observation": "improvement",
        "falsifier": "no direct improvement",
        "protected_behavior": ["one answer"],
        "exploration_operation": "replace",
        "research_sources": [],
        "candidate_structure": {
            **incumbent.to_dict(include_id=False),
            "name": "relabeled candidate",
            "changed_factor": "labels",
        },
    }
    with pytest.raises(ContractError, match="differ executably"):
        ExternalArchitect._parse(raw, max_calls=4, incumbent=incumbent)


def test_architect_placeholders_and_factor_labels_are_deterministically_normalized() -> None:
    incumbent = _loop("incumbent")
    factor = "one authoritative state transition kernel"
    raw = {
        "observed_bottleneck": "parallel mutation paths",
        "hypothesis": "one kernel is safer",
        "changed_factor": factor,
        "predicted_observation": "fewer invalid transitions",
        "falsifier": "no direct improvement",
        "protected_behavior": ["one answer"],
        "exploration_operation": "replace",
        "research_sources": [],
        "candidate_structure": {
            "name": "two call kernel",
            "organization": "sequential",
            "information_flow": "analyze then emit",
            "changed_factor": "semantically equivalent but differently worded factor",
            "calls": [
                {"id": "analyze", "role": "analyst", "objective": "analyze", "inputs": ["task"], "output_type": "analysis"},
                {"id": "emit", "role": "producer", "objective": "emit", "inputs": ["task", "prior_call_id"], "output_type": "answer"},
            ],
            "final_call_id": "emit",
        },
    }
    proposal = ExternalArchitect._parse(raw, max_calls=4, incumbent=incumbent)
    assert proposal.candidate.changed_factor == factor
    assert proposal.candidate.calls[1].inputs == ("task", "analyze")
    assert proposal.candidate.provenance["architect_structure_changed_factor"].startswith("semantically")
