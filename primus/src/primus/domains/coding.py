from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from primus.domains.base import DomainAdapter, EvaluationOutcome, files_payload
from primus.errors import ContractError
from primus.jsonutil import content_hash, ensure_within, file_hash


class CodingAdapter(DomainAdapter):
    def smoke_payload(self, reference_payload: dict[str, Any]) -> dict[str, Any] | None:
        configured = super().smoke_payload(reference_payload)
        if configured is not None:
            return configured
        request = str(self.case_for("development", 1).get("request", ""))
        if "fib(n)" not in request:
            return None
        return {"files": {"solution.py": (
            "def fib(n):\n"
            "    if n < 0:\n"
            "        raise ValueError(n)\n"
            "    a, b = 0, 1\n"
            "    for _ in range(n):\n"
            "        a, b = b, a + b\n"
            "    return a\n"
        )}}

    def case_semantic_payload(self, split: str, replicate: int) -> dict[str, Any]:
        case = self.case_for(split, replicate)
        fixture = Path(str(case["fixture_dir"])).resolve()
        files = {
            path.relative_to(fixture).as_posix(): file_hash(path)
            for path in sorted(fixture.rglob("*"))
            if path.is_file()
        }
        return {
            "request": case.get("request"),
            "commands": case.get("commands", []),
            "fixture_files": files,
            "protected_sha256": case.get("protected_sha256", {}),
            "timeout_seconds": case.get("timeout_seconds", 60),
        }

    def artifact_text(self, payload: dict[str, Any]) -> str:
        return json.dumps({"files": files_payload(payload)}, ensure_ascii=False, sort_keys=True)

    def evaluate(
        self,
        *,
        payload: dict[str, Any],
        split: str,
        replicate: int,
        output_directory: Path,
    ) -> EvaluationOutcome:
        files = files_payload(payload)
        case = self.case_for(split, replicate)
        fixture = Path(str(case["fixture_dir"])).resolve()
        if not fixture.is_dir():
            raise ContractError(f"coding fixture is missing: {fixture}")
        with tempfile.TemporaryDirectory(prefix="primus-coding-") as raw:
            workspace = Path(raw) / "workspace"
            shutil.copytree(fixture, workspace, symlinks=False)
            protected = {str(key): str(value) for key, value in case.get("protected_sha256", {}).items()}
            for name, content in files.items():
                target = ensure_within(workspace, workspace / name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            for name, digest in protected.items():
                target = ensure_within(workspace, workspace / name)
                if not target.is_file() or file_hash(target) != digest:
                    return self._failure(split, "protected_file_changed", "A protected repository file was changed.")
            commands = case.get("commands", [])
            passed = 0
            failures: list[str] = []
            clean_env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "NO_PROXY": "*",
            }
            for index, command in enumerate(commands, 1):
                if not isinstance(command, list) or not command:
                    raise ContractError("coding evaluator commands must be non-empty argv arrays")
                try:
                    completed = subprocess.run(
                        [str(item) for item in command],
                        cwd=workspace,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=float(case.get("timeout_seconds", 60)),
                        env=clean_env,
                        shell=False,
                    )
                except subprocess.TimeoutExpired:
                    failures.append(f"command_{index}:timeout")
                    continue
                if completed.returncode == 0:
                    passed += 1
                else:
                    failures.append(f"command_{index}:returncode_{completed.returncode}")
            valid = bool(commands)
            score = passed / len(commands) if commands else 0.0
            result = {"passed": passed, "commands": len(commands), "failures": failures, "score": score}
            output_directory.mkdir(parents=True, exist_ok=True)
            (output_directory / "redacted-result.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
            return EvaluationOutcome(
                valid=valid,
                score=score if valid else None,
                failure_class=None if not failures else "coding_tests_failed",
                evidence=(f"public-coding-case:{case['id']}",) if split == "development" else (f"coding-certification:{content_hash({'case': case['id'], 'result': result})}",),
                public_feedback={} if not failures or split != "development" else {
                    "public_bad_behavior": "The submitted files did not pass the public executable checks.",
                    "public_required_behavior": "Return complete files that satisfy every public test and preserve protected files.",
                    "public_check": ",".join(failures),
                },
                raw_result_sha256=content_hash(result),
                failure_origin=None,
                metrics={
                    "tests_passed": float(passed),
                    "tests_total": float(len(commands)),
                    "pass_rate": float(score),
                },
            )

    @staticmethod
    def _failure(split: str, failure: str, message: str) -> EvaluationOutcome:
        return EvaluationOutcome(
            valid=False,
            score=None,
            failure_class=failure,
            evidence=(),
            public_feedback={
                "public_bad_behavior": message,
                "public_required_behavior": "Preserve all protected repository behavior.",
                "public_check": "Verify protected SHA-256 manifests before running tests.",
            } if split == "development" else {},
            raw_result_sha256=content_hash({"failure": failure}),
            failure_origin="candidate",
            metrics={},
        )
