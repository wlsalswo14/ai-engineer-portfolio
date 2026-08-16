from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from primus.domains.base import DomainAdapter, EvaluationOutcome, files_payload
from primus.errors import EvaluationError
from primus.jsonutil import atomic_json, content_hash


class ChessAdapter(DomainAdapter):
    def case_semantic_payload(self, split: str, replicate: int) -> dict[str, Any]:
        case = self.case_for(split, replicate)
        metadata = case["metadata"]
        semantic_keys = (
            "adapter_version",
            "runner_sha256",
            "openings_sha256",
            "stockfish_sha256",
            "python_chess_version",
            "python_chess_source_tree_sha256",
            "tier_index",
            "candidate_movetime_ms",
            "candidate_response_grace_ms",
            "candidate_initial_handshake_timeout_ms",
            "candidate_new_game_ready_timeout_ms",
            "candidate_total_handshake_wall_cap_ms",
            "max_plies",
        )
        return {
            "family": case.get("family"),
            "scorer": case.get("scorer"),
            "metadata": {key: metadata.get(key) for key in semantic_keys},
        }

    def artifact_text(self, payload: dict[str, Any]) -> str:
        return files_payload(payload, only="engine.py")["engine.py"]

    def evaluate(
        self,
        *,
        payload: dict[str, Any],
        split: str,
        replicate: int,
        output_directory: Path,
    ) -> EvaluationOutcome:
        source = self.artifact_text(payload)
        output_directory.mkdir(parents=True, exist_ok=True)
        artifact = output_directory / "artifact.json"
        atomic_json(artifact, {"files": {"engine.py": source}})
        case = self.case_for(split, replicate)
        request = {
            "ouroboros_source": self.config.evaluator["ouroboros_source"],
            "case": case,
            "artifact_path": str(artifact.resolve()),
            "result_dir": str((output_directory / "benchmark").resolve()),
            "split": split,
        }
        request_path = output_directory / "worker-request.json"
        result_path = output_directory / "worker-result.json"
        atomic_json(request_path, request)
        completed = subprocess.run(
            [sys.executable, "-m", "primus.workers.chess_worker", str(request_path), str(result_path)],
            cwd=self.system.root,
            text=True,
            capture_output=True,
            timeout=int(self.config.evaluator.get("worker_wall_seconds", 1800)),
            env={**os.environ, "PYTHONPATH": str(self.system.root / "src")},
        )
        if completed.returncode != 0 or not result_path.is_file():
            raise EvaluationError(f"chess evaluator worker failed: {completed.stderr[-1200:]}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("failure_kind") in {"evaluator_contract_error", "evaluator_failure"}:
            raise EvaluationError(f"chess evaluator infrastructure failed: {result.get('failure_kind')}")
        valid = result.get("failure_kind") is None and isinstance(result.get("score"), (int, float))
        failure = None if valid else str(result.get("failure_kind") or "chess_evaluator_failure")
        public = {} if valid else {
            "public_bad_behavior": "The generated engine failed the public UCI, legality, timing, or source boundary.",
            "public_required_behavior": "Emit one standard-library-only legal UCI engine that answers every go request on time.",
            "public_check": "Run static source validation and the public UCI smoke sequence.",
        }
        evidence = tuple(str(item) for item in result.get("evidence", ())) if split == "development" else (
            f"chess-certification:{content_hash({'case': case.get('id'), 'result': result.get('result_digest')})}",
        )
        return EvaluationOutcome(
            valid=valid,
            score=float(result["score"]) if valid else None,
            failure_class=failure,
            evidence=evidence,
            public_feedback=public if split == "development" else {},
            raw_result_sha256=str(result.get("result_digest") or content_hash(result)),
            failure_origin=None if valid else "candidate",
            metrics={"score_rate": float(result["score"])} if valid else {},
        )
