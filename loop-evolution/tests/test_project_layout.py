from __future__ import annotations

import hashlib
import json
from pathlib import Path

from loop_evolution.pipeline import EvolutionPipeline
from loop_evolution.platform.config import ProposalPolicy, RuntimePolicy


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "experiments" / "chess-tier5-clean" / "config.json"


def _resolve(base: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (base / path).resolve()


def test_chess_experiment_is_self_contained() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    base = CONFIG_PATH.parent
    paths = [
        config["initial_champion"]["artifact_path"],
        config["initial_champion"]["benchmark_receipt_path"],
        config["initial_champion"]["loop_structure_path"],
        config["proposal_policy_path"],
        config["execution_policy_path"],
        config["benchmark_case_dir"],
        config["benchmark_result_dir"],
        config["workspace_dir"],
    ]
    for raw in paths:
        assert _resolve(base, raw).exists(), raw


def test_active_architect_is_an_independent_sol_max_subagent() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    base = CONFIG_PATH.parent
    proposal_path = _resolve(base, config["proposal_policy_path"])
    execution_path = _resolve(base, config["execution_policy_path"])
    proposal = ProposalPolicy.load(proposal_path)
    execution = RuntimePolicy.load(execution_path)

    assert proposal_path.name == "sol-max-independent-structural-architect-1800s.json"
    assert proposal.model == "gpt-5.6-sol"
    assert proposal.reasoning_effort == "max"
    assert proposal.agent_mode == "independent_subagent"
    assert proposal.max_model_calls == 1
    assert execution.model == "gpt-5.6-luna"
    assert execution.reasoning_effort == "high"


def test_source_has_no_v3_lite_runtime_import() -> None:
    source = ROOT / "src"
    offenders = [
        path
        for path in source.rglob("*.py")
        if "ouroboros_v3lite" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_frozen_resource_hashes() -> None:
    resource_root = ROOT / "resources"
    manifest = json.loads((resource_root / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["resources"]:
        path = resource_root / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_active_champion_paths_belong_to_new_workspace() -> None:
    workspace = ROOT / "experiments" / "chess-tier5-clean" / "workspace"
    state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
    champion = state["champion"]
    paths = [
        Path(champion["engine"]["artifact_path"]),
        Path(champion["loop_structure"]["spec_path"]),
        Path(champion["loop_structure"]["execution_plan_path"]),
    ]
    for path in paths:
        assert path.is_relative_to(workspace)
        assert path.is_file()


def test_benchmark_cache_is_redirected_to_experiment_workspace() -> None:
    pipeline = EvolutionPipeline(CONFIG_PATH)
    expected = ROOT / "experiments" / "chess-tier5-clean" / "workspace" / "benchmark-results"
    assert pipeline.evaluator.scorer.result_cache_dir == expected


def test_active_clean_lineage_has_three_distinct_anchor_sources() -> None:
    pipeline = EvolutionPipeline(CONFIG_PATH)
    state = pipeline.store.migrate_to_matched_pairs()
    panel = pipeline._select_anchor_panel(state["champion"])
    assert [item["role"] for item in panel] == [
        "current_champion",
        "frozen_lineage_baseline",
        "recent_promotion_alternate",
    ]
    assert len({item["engine_source_sha256"] for item in panel}) == 3
