from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from primus.domains.base import DomainAdapter, EvaluationOutcome, files_payload
from primus.errors import ContractError, EvaluationError
from primus.jsonutil import atomic_json, content_hash


class CacheAdapter(DomainAdapter):
    def decode_reference_artifact(self, raw: bytes) -> dict[str, Any]:
        return {"files": {"policy.py": raw.decode("utf-8-sig")}}

    def case_semantic_payload(self, split: str, replicate: int) -> dict[str, Any]:
        case = self.case_for(split, replicate)
        return {
            "request": case.get("request"),
            "seed": case.get("seed"),
            "scale": case.get("scale", 3),
            "timeout_seconds": case.get("timeout_seconds", 3.0),
            "runner_sha256": self.config.evaluator.get("runner_sha256"),
        }

    def artifact_text(self, payload: dict[str, Any]) -> str:
        return files_payload(payload, only="policy.py")["policy.py"]

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
        policy = output_directory / "policy.py"
        policy.write_text(source, encoding="utf-8")
        case = self.case_for(split, replicate)
        request = {
            "runner_path": self.config.evaluator["runner_path"],
            "runner_sha256": self.config.evaluator["runner_sha256"],
            "policy_path": str(policy.resolve()),
            "seed": int(case["seed"]),
            "scale": int(case.get("scale", 3)),
            "timeout_seconds": float(case.get("timeout_seconds", 3.0)),
        }
        request_path = output_directory / "worker-request.json"
        result_path = output_directory / "worker-result.json"
        atomic_json(request_path, request)
        worker = self.system.root / "src" / "primus" / "workers" / "cache_worker.py"
        completed = subprocess.run(
            [sys.executable, "-I", str(worker), str(request_path), str(result_path)],
            cwd=self.system.root,
            text=True,
            capture_output=True,
            timeout=int(self.config.evaluator.get("worker_wall_seconds", 30)),
            env={**dict(__import__("os").environ), "PYTHONPATH": str(self.system.root / "src")},
        )
        if completed.returncode != 0 or not result_path.is_file():
            raise EvaluationError(f"cache evaluator worker failed: {completed.stderr[-1000:]}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        valid = bool(
            result.get("trace_count", 0) > 0
            and result.get("invalid_operation_count", 0) == 0
            and result.get("timeout_count", 0) == 0
            and not result.get("details", {}).get("static_reject")
            and not result.get("details", {}).get("runtime_error")
        )
        failure = None if valid else "cache_policy_invalid"
        public = {} if valid else {
            "public_bad_behavior": "The policy violated the public cache Policy contract or timed out.",
            "public_required_behavior": "Policy.access must return only legal evictions and preserve capacity invariants.",
            "public_check": "Run the public cache trace validator and static policy audit.",
        }
        return EvaluationOutcome(
            valid=valid,
            score=float(result["score"]) if valid else None,
            failure_class=failure,
            evidence=(f"cache-runner:{request['runner_sha256']}", f"cache-seed:{request['seed']}") if split == "development" else (f"cache-certification:{content_hash({'runner': request['runner_sha256'], 'split': split})}",),
            public_feedback=public if split == "development" else {},
            raw_result_sha256=content_hash(result),
            failure_origin=None if valid else "candidate",
            metrics={
                "cache_score": float(result["score"]),
                "invalid_operation_count": float(result.get("invalid_operation_count", 0)),
                "timeout_count": float(result.get("timeout_count", 0)),
            } if isinstance(result.get("score"), (int, float)) else {},
        )
