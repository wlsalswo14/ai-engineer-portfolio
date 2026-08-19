from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from loop_evolution.platform.evaluation.chessbench import ChessBench100Scorer
from loop_evolution.platform.evaluation.repository import BenchmarkRepository
from loop_evolution.common import atomic_json, file_hash, read_json


class ExistingChessBench:
    """Adapter over the repository's already frozen ChessBench and result cache."""

    def __init__(self, case_dir: Path, *, result_cache_dir: Path | None = None) -> None:
        cases = BenchmarkRepository(case_dir).load()
        if len(cases) != 1 or cases[0].scorer != "chessbench_100":
            raise ValueError("benchmark_case_dir must contain exactly one ChessBench100 case")
        self.case = cases[0]
        self.scorer = ChessBench100Scorer(
            must_beat_score_rate=None,
            result_cache_dir=result_cache_dir,
        )

    @property
    def task(self) -> str:
        return self.case.request

    def evaluate(self, artifact_path: Path, *, evaluation_dir: Path) -> dict[str, Any]:
        output = artifact_path.read_text(encoding="utf-8")
        public_score, public_failure, public_evidence = self.scorer.verify_public(output)
        if public_failure is not None:
            result = {
                "valid": False,
                "failure_kind": public_failure,
                "public_score": public_score,
                "public_evidence": list(public_evidence),
                "elo": None,
            }
            atomic_json(evaluation_dir / "evaluation.json", result)
            return result

        score_rate, failure, evidence = self.scorer.score(self.case, output)
        receipt_ref = next((item for item in evidence if item.startswith("chessbench-result:")), "")
        receipt_path = Path(receipt_ref.removeprefix("chessbench-result:")) if receipt_ref else None
        if failure is not None or receipt_path is None or not receipt_path.is_file():
            result = {
                "valid": False,
                "failure_kind": failure or "missing_benchmark_receipt",
                "public_score": public_score,
                "public_evidence": list(public_evidence),
                "score_rate": score_rate,
                "evidence": list(evidence),
                "elo": None,
            }
            atomic_json(evaluation_dir / "evaluation.json", result)
            return result

        receipt = read_json(receipt_path)
        summary = receipt["result"]["summary"]
        elo = float(summary["elo"]["elo_difference"])
        valid_games = int(summary.get("valid_games", 100))
        candidate_failures = int(summary.get("candidate_failures", 0))
        evaluation_valid = bool(summary["valid"]) and valid_games == 100 and candidate_failures == 0
        local_receipt = evaluation_dir / "benchmark-result-receipt.json"
        local_receipt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(receipt_path, local_receipt)
        result = {
            "valid": evaluation_valid,
            "benchmark_valid": bool(summary["valid"]),
            "failure_kind": (
                None
                if evaluation_valid
                else f"benchmark_contract_failure:valid_games={valid_games},candidate_failures={candidate_failures}"
            ),
            "public_score": public_score,
            "public_evidence": list(public_evidence),
            "score_rate": float(score_rate),
            "wins": int(summary["wins"]),
            "draws": int(summary["draws"]),
            "losses": int(summary["losses"]),
            "elo": elo,
            "elo_error_95": float(summary["elo"].get("elo_error_95", 0.0)),
            "los": float(summary["elo"].get("los", 0.0)),
            "valid_games": valid_games,
            "candidate_failures": candidate_failures,
            "benchmark_receipt_path": str(local_receipt.resolve()),
            "source_benchmark_receipt_path": str(receipt_path.resolve()),
            "benchmark_receipt_sha256": file_hash(local_receipt),
            "evidence": list(evidence),
        }
        atomic_json(evaluation_dir / "evaluation.json", result)
        return result


def promoted_package(
    *,
    workspace: Path,
    round_index: int,
    plan: dict[str, Any],
    artifact_path: Path,
    evaluation: dict[str, Any],
    source_plan_path: Path,
) -> dict[str, Any]:
    champion_dir = workspace / "champions" / f"p{round_index:04d}"
    if champion_dir.exists():
        raise FileExistsError(champion_dir)
    champion_dir.mkdir(parents=True)
    local_artifact = champion_dir / "final-output.json"
    local_structure = champion_dir / "loop-structure.json"
    local_receipt = champion_dir / "benchmark-result-receipt.json"
    shutil.copy2(artifact_path, local_artifact)
    atomic_json(local_structure, plan)
    shutil.copy2(Path(evaluation["benchmark_receipt_path"]), local_receipt)

    artifact = read_json(local_artifact)
    source = artifact["files"]["engine.py"]
    source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    structure = plan["structure"]
    change = plan["hypothesis"]["causal_change"]
    call_count = sum(len(stage["calls"]) for stage in structure["stages"])
    package_id = f"package_{hashlib.sha256((plan['structure_id'] + source_sha).encode()).hexdigest()[:16]}"
    return {
        "package_id": package_id,
        "promoted_round": round_index,
        "label": f"round-{round_index}-{structure['name']}",
        "loop_structure": {
            "structure_id": plan["structure_id"],
            "organization": structure["organization"],
            "changed_factor": str(change["factor"]),
            "summary": str(structure["information_flow"]),
            "call_count": call_count,
            "spec_path": str(local_structure.resolve()),
            "source_spec_path": str(source_plan_path.resolve()),
            "execution_plan_path": str(local_structure.resolve()),
        },
        "engine": {
            "artifact_path": str(local_artifact.resolve()),
            "source_artifact_path": str(artifact_path.resolve()),
            "artifact_sha256": file_hash(local_artifact),
            "engine_source_sha256": source_sha,
        },
        "metrics": {
            "elo": float(evaluation["elo"]),
            "score_rate": float(evaluation["score_rate"]),
            "wins": int(evaluation["wins"]),
            "draws": int(evaluation["draws"]),
            "losses": int(evaluation["losses"]),
            "receipt_path": str(local_receipt.resolve()),
            "source_receipt_path": str(evaluation["source_benchmark_receipt_path"]),
        },
    }
