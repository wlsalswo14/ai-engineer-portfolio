from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE / "workspace"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_predeclared_bootstrap_contract_is_r0_only() -> None:
    contract = load(HERE / "campaign-contract.json")
    assert contract["display_round"] == 0
    assert contract["stop_after_display_round"] == 0
    assert contract["bootstrap"]["representatives_per_structure"] == 3
    assert [item["display_source_round"] for item in contract["bootstrap"]["structures"]] == [20, 24, 26, 30]
    assert contract["close_confirmation"]["trigger_absolute_median_difference_lte"] == 0.25
    assert contract["selection"]["primary"] == "highest-median-score"


def test_frozen_source_and_fixed_topology_seals() -> None:
    manifest = load(WORKSPACE / "source-manifest.json")
    assert manifest["fixture"] == {
        "seed": 20260605,
        "scale": 3,
        "trace_count": 9,
        "canonical_sha256": "793cbd7e5c04e896650ebc713fc29654fc63cf5fe1aaba15f6f6149d11795d87",
        "fixture_payload_persisted": False,
    }
    assert [item["call_count"] for item in manifest["historical_structures"]] == [1, 3, 3, 2]
    translation_seal = load(WORKSPACE / "translation-seal.json")
    assert translation_seal["architect_model"] == "gpt-5.6-sol"
    assert translation_seal["architect_reasoning_effort"] == "max"
    assert translation_seal["architect_service_tier"] == "fast"
    for display_round in (20, 24, 26, 30):
        translated = load(WORKSPACE / "translated-structures" / f"R{display_round}.json")
        assert translated["translation_audit"]["valid"] is True


def test_all_artifacts_share_anchor_and_model_receipts_are_exact() -> None:
    seal = load(WORKSPACE / "pre-evaluation-seal.json")
    assert len(seal["entries"]) == 13
    assert seal["model_boundary"] == {
        "architect_calls": 1,
        "architect_model": "gpt-5.6-sol",
        "architect_reasoning_effort": "max",
        "architect_service_tier": "fast",
        "anchor_calls": 1,
        "anchor_model": "gpt-5.6-luna",
        "anchor_reasoning_effort": "high",
        "topology_calls": 27,
        "topology_model": "gpt-5.6-luna",
        "topology_reasoning_effort": "high",
    }
    anchor_hashes = set()
    for display_round in (20, 24, 26, 30):
        for representative in (1, 2, 3):
            manifest = load(
                WORKSPACE
                / "bootstrap"
                / f"R{display_round}"
                / f"rep-{representative:02d}"
                / "generation-manifest.json"
            )
            anchor_hashes.add(manifest["anchor_sha256"])
            assert manifest["model"] == "gpt-5.6-luna"
            assert manifest["reasoning_effort"] == "high"
    assert anchor_hashes == {seal["shared_anchor_sha256"]}
    for entry in seal["entries"]:
        assert sha256(HERE / entry["artifact_path"]) == entry["artifact_sha256"]
        assert sha256(HERE / entry["seal_path"]) == entry["seal_sha256"]


def test_replay2_and_terminal_state() -> None:
    batch = load(WORKSPACE / "evaluation" / "evaluation-batch.json")
    assert batch["replay_count"] == 2
    for structure in batch["structure_summaries"]:
        assert len(structure["representatives"]) == 3
        assert all(rep["replay_deterministic"] for rep in structure["representatives"])
    if batch["close_confirmation_triggered"]:
        assert batch["confirmation_passed"] is True
        assert len(batch["confirmations"]) == 6
    state = load(WORKSPACE / "state.json")
    assert state["display_round"] == 0
    assert state["status"] == "stopped-after-bootstrap-r0"
    assert state["cache_r1_opened"] is False
    assert state["next_round_permitted"] is False
