from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loop_evolution.common import atomic_json, read_json
from loop_evolution.pipeline import EvolutionPipeline


ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT = ROOT / "experiments" / "chess-tier5-clean"
WORKSPACE = EXPERIMENT / "workspace"
OUTPUT = Path(__file__).resolve().parent


def call_count(plan: object) -> int:
    structure = plan.structure
    return sum(len(stage["calls"]) for stage in structure["stages"])


def main() -> None:
    pipeline = EvolutionPipeline(EXPERIMENT / "config.json", force_complete_pairs=True)
    state = read_json(WORKSPACE / "state.json")
    capsule = read_json(WORKSPACE / "state-capsule.json")
    champion = dict(state["champion"])

    single_plan = pipeline._load_plan(
        WORKSPACE / "champions" / "p0001" / "loop-structure.json"
    )
    current_plan = pipeline._load_plan(
        WORKSPACE / "champions" / "p0030" / "loop-structure.json"
    )

    anchor_path = Path(champion["engine"]["artifact_path"])
    anchor_text = anchor_path.read_text(encoding="utf-8")
    anchor_metrics = dict(champion["metrics"])
    anchor = pipeline._anchor_descriptor(
        role="current_champion_common_anchor",
        artifact_path=anchor_path,
        metrics=anchor_metrics,
        origin=f"champion:{champion['package_id']}",
    )

    atomic_json(
        OUTPUT / "experiment-contract.json",
        {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "purpose": "one fresh matched direct comparison: single-call p0001 vs current p0030",
            "state_mutation_permitted": False,
            "promotion_or_champion_install_permitted": False,
            "pair_count": 1,
            "common_anchor": anchor,
            "incumbent": {
                "label": "single_call",
                "structure_id": single_plan.structure_id,
                "call_count": call_count(single_plan),
            },
            "candidate": {
                "label": "current_champion_loop",
                "structure_id": current_plan.structure_id,
                "call_count": call_count(current_plan),
            },
            "benchmark": "frozen chessbench100 Stockfish Tier-5 from active config",
            "execution_policy": str(pipeline.config["execution_policy_path"]),
        },
    )

    single_builtins = pipeline._builtins(
        plan=single_plan,
        anchor_metrics=anchor_metrics,
        capsule=capsule,
        anchor_text=anchor_text,
    )
    current_builtins = pipeline._builtins(
        plan=current_plan,
        anchor_metrics=anchor_metrics,
        capsule=capsule,
        anchor_text=anchor_text,
    )

    result = pipeline._run_pair(
        pair_index=1,
        root_dir=OUTPUT,
        anchor=anchor,
        incumbent_plan=single_plan,
        candidate_plan=current_plan,
        incumbent_builtins=single_builtins,
        candidate_builtins=current_builtins,
    )

    single_eval = dict(result["incumbent_evaluation"])
    current_eval = dict(result["candidate_evaluation"])
    summary = {
        "schema_version": 1,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": result["verdict"],
        "attempts_used": result["attempts_used"],
        "common_anchor": True,
        "single_call": {
            "structure_id": single_plan.structure_id,
            "call_count": call_count(single_plan),
            "evaluation": single_eval,
        },
        "current_champion_loop": {
            "structure_id": current_plan.structure_id,
            "call_count": call_count(current_plan),
            "evaluation": current_eval,
        },
        "delta_current_minus_single": {
            "elo": (
                float(current_eval["elo"]) - float(single_eval["elo"])
                if current_eval.get("elo") is not None
                and single_eval.get("elo") is not None
                else None
            ),
            "score_rate": (
                float(current_eval["score_rate"])
                - float(single_eval["score_rate"])
                if current_eval.get("score_rate") is not None
                and single_eval.get("score_rate") is not None
                else None
            ),
        },
        "token_usage": result.get("token_usage"),
        "source_pair_summary": str(
            (OUTPUT / "pairs" / "pair-01" / "pair-summary.json").resolve()
        ),
    }
    atomic_json(OUTPUT / "ab-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
