from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import statistics
from typing import Any, Callable

from primus.config import DomainConfig, SystemConfig
from primus.domains.base import DomainAdapter
from primus.errors import ContractError, EvaluationError, IntegrityError
from primus.inner import GeneratedArtifact, InnerLoopExecutor
from primus.jsonutil import atomic_json, bytes_hash, content_hash, read_json, write_immutable_json
from primus.lock import ExclusiveLease
from primus.models import ArmResult, LoopStructure, PairedDecision, Usage
from primus.stats import cost_adjusted_score, judge_paired


class TournamentEvaluator:
    """Generate every arm first, freeze it, then open the evaluator."""

    def __init__(
        self,
        *,
        system: SystemConfig,
        config: DomainConfig,
        adapter: DomainAdapter,
        executor: InnerLoopExecutor,
    ):
        self.system = system
        self.config = config
        self.adapter = adapter
        self.executor = executor

    def run_split(
        self,
        *,
        run_id: str,
        round_index: int,
        split: str,
        structures: dict[str, LoopStructure],
        incumbent_payload: dict[str, Any],
        incumbent_metrics: dict[str, Any],
        public_audit: list[dict[str, Any]],
        hypothesis: dict[str, Any],
        working_directory: Path,
    ) -> tuple[dict[str, list[ArmResult]], dict[str, Any]]:
        """Compatibility wrapper for v1 callers; v2 uses run_stage explicitly."""
        if split not in {"development", "certification"}:
            raise ContractError(f"unknown split: {split}")
        reps = (
            self.config.evaluation.screening_replicates
            if split == "development"
            else self.config.evaluation.certification_replicates
        )
        return self.run_stage(
            run_id=run_id,
            round_index=round_index,
            split=split,
            stage="screening" if split == "development" else "certification",
            replicates=reps,
            structures=structures,
            incumbent_payload=incumbent_payload,
            incumbent_metrics=incumbent_metrics,
            public_audit=public_audit,
            hypothesis=hypothesis,
            working_directory=working_directory,
        )

    def run_stage(
        self,
        *,
        run_id: str,
        round_index: int,
        split: str,
        stage: str,
        replicates: int,
        structures: dict[str, LoopStructure],
        incumbent_payload: dict[str, Any],
        incumbent_metrics: dict[str, Any],
        public_audit: list[dict[str, Any]],
        hypothesis: dict[str, Any],
        working_directory: Path,
        effective_replicates: list[int] | None = None,
        on_presealed: Callable[[dict[str, Any]], None] | None = None,
        hypotheses: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, list[ArmResult]], dict[str, Any]]:
        if split not in {"development", "certification"}:
            raise ContractError(f"unknown split: {split}")
        if replicates < 1 or not structures:
            raise ContractError("a stage requires positive replicates and at least one arm")
        receipt_path = working_directory / "evaluation-receipt.json"
        if receipt_path.is_file():
            receipt = read_json(receipt_path)
            unsigned = {key: value for key, value in receipt.items() if key != "receipt_payload_sha256"}
            if content_hash(unsigned) != receipt.get("receipt_payload_sha256"):
                raise IntegrityError(f"resumed evaluation receipt changed: {receipt_path}")
            if receipt.get("stage") != stage or receipt.get("split") != split:
                raise IntegrityError(f"resumed stage identity changed: {receipt_path}")
            return self.load_results(receipt), receipt
        generated: dict[str, list[GeneratedArtifact]] = {name: [] for name in structures}
        selected_replicates = list(effective_replicates or [])
        if selected_replicates and len(selected_replicates) != replicates:
            raise ContractError("effective replicate count differs from stage replicate count")
        if not selected_replicates:
            selected_replicates = [(round_index - 1) * replicates + replicate for replicate in range(1, replicates + 1)]
        for replicate in range(1, replicates + 1):
            # Rotate through a task bank. A certification selection digest may be consumed once.
            effective = selected_replicates[replicate - 1]
            task = self.adapter.task_for(split, effective)
            anchor_text = (
                self.adapter.anchor_text(incumbent_payload, split, effective)
                if hasattr(self.adapter, "anchor_text")
                else self.adapter.artifact_text(incumbent_payload)
            )
            for arm, structure in structures.items():
                arm_dir = working_directory / "generation" / f"replicate-{replicate:02d}" / arm
                generated[arm].append(
                    self._generate_once(
                        structure=structure,
                        task=task,
                        champion_artifact=anchor_text,
                        champion_metrics=incumbent_metrics,
                        public_audit=public_audit if split == "development" else [],
                        hypothesis=(hypotheses or {}).get(arm, hypothesis),
                        working_directory=arm_dir,
                    )
                )

        taskset = self.adapter.taskset(split)
        selected_cases = [self.adapter.case_for(split, item) for item in selected_replicates]
        selection_digest = content_hash(
            {"base_taskset_sha256": content_hash(taskset), "split": split, "cases": selected_cases}
        )
        semantic_selection_digest = (
            self.adapter.semantic_selection_digest(split, selected_replicates)
            if hasattr(self.adapter, "semantic_selection_digest")
            else content_hash({
                "split": split,
                "cases": [
                    {key: value for key, value in case.items() if key != "id"}
                    for case in selected_cases
                ],
            })
        )
        preseal = {
            "schema_version": 1,
            "run_id": run_id,
            "split": split,
            "stage": stage,
            "taskset_selection_sha256": selection_digest,
            "semantic_selection_sha256": semantic_selection_digest,
            "base_taskset_sha256": content_hash(taskset),
            "effective_replicates": selected_replicates,
            "arms": {
                name: [
                    {
                        "replicate": index,
                        "artifact_sha256": artifact.artifact_sha256,
                        "structure_id": structures[name].structure_id,
                        "usage": artifact.usage.to_dict(),
                    }
                    for index, artifact in enumerate(items, 1)
                ]
                for name, items in generated.items()
            },
            "all_arms_generated_before_evaluation": True,
        }
        preseal["preseal_sha256"] = content_hash(preseal)
        write_immutable_json(working_directory / "pre-evaluation-seal.json", preseal)
        if on_presealed is not None:
            on_presealed(preseal)

        results: dict[str, list[ArmResult]] = {name: [] for name in structures}
        with ExclusiveLease(self.system.heavy_lock, owner=f"primus:{run_id}:{stage}"):
            for replicate, effective in enumerate(selected_replicates, 1):
                for arm, structure in structures.items():
                    generated_artifact = generated[arm][replicate - 1]
                    evaluation_dir = working_directory / "evaluation" / f"replicate-{replicate:02d}" / arm
                    outcome = self.adapter.evaluate(
                        payload=generated_artifact.payload,
                        split=split,
                        replicate=effective,
                        output_directory=evaluation_dir,
                    )
                    if outcome.failure_origin == "infrastructure":
                        raise EvaluationError(
                            f"{self.config.id} evaluator infrastructure failed: {outcome.failure_class or 'unknown'}"
                        )
                    case = self.adapter.case_for(split, effective)
                    results[arm].append(
                        ArmResult(
                            arm=arm,
                            replicate=replicate,
                            valid=outcome.valid,
                            score=outcome.score,
                            artifact_sha256=generated_artifact.artifact_sha256,
                            structure_sha256=content_hash(structure.to_dict()),
                            usage=generated_artifact.usage,
                            failure_class=outcome.failure_class,
                            evidence=outcome.evidence,
                            failure_origin=outcome.failure_origin,
                            raw_result_sha256=outcome.raw_result_sha256,
                            metrics=dict(outcome.metrics),
                            case_fingerprint=(
                                self.adapter.case_semantic_digest(split, effective)
                                if hasattr(self.adapter, "case_semantic_digest")
                                else content_hash({key: value for key, value in case.items() if key != "id"})
                            ),
                            case_family=str(case.get("family", "")) if split == "development" else "",
                        )
                    )
                    if split == "development":
                        atomic_json(
                            evaluation_dir / "public-feedback.json",
                            {
                                "failure_class": outcome.failure_class,
                                **outcome.public_feedback,
                            },
                        )
        receipt_results: list[dict[str, Any]] = []
        for arm, values in results.items():
            for item in values:
                value = item.to_dict()
                if split == "development":
                    feedback_path = working_directory / "evaluation" / f"replicate-{item.replicate:02d}" / arm / "public-feedback.json"
                    if feedback_path.is_file():
                        value.update(read_json(feedback_path))
                receipt_results.append(value)
        receipt = {
            "schema_version": 1,
            "run_id": run_id,
            "split": split,
            "stage": stage,
            "hidden": split == "certification",
            "preseal_sha256": preseal["preseal_sha256"],
            "taskset_selection_sha256": selection_digest,
            "semantic_selection_sha256": semantic_selection_digest,
            "results": receipt_results,
        }
        receipt["receipt_payload_sha256"] = content_hash(receipt)
        write_immutable_json(receipt_path, receipt)
        # Return the canonical on-disk representation so a resumed run is
        # byte-for-byte equivalent to the first successful execution.
        persisted_receipt = read_json(receipt_path)
        return self.load_results(persisted_receipt), persisted_receipt

    @staticmethod
    def load_results(receipt: dict[str, Any]) -> dict[str, list[ArmResult]]:
        results: dict[str, list[ArmResult]] = {}
        for raw in receipt.get("results", []):
            usage_raw = raw.get("usage", {})
            usage = Usage(**{key: int(usage_raw.get(key, 0)) for key in Usage.__dataclass_fields__})
            item = ArmResult(
                arm=str(raw["arm"]),
                replicate=int(raw["replicate"]),
                valid=bool(raw["valid"]),
                score=float(raw["score"]) if raw.get("score") is not None else None,
                artifact_sha256=str(raw["artifact_sha256"]),
                structure_sha256=str(raw["structure_sha256"]),
                usage=usage,
                failure_class=str(raw["failure_class"]) if raw.get("failure_class") is not None else None,
                evidence=tuple(str(item) for item in raw.get("evidence", ())),
                failure_origin=str(raw["failure_origin"]) if raw.get("failure_origin") is not None else None,
                raw_result_sha256=str(raw.get("raw_result_sha256", "")),
                metrics={str(key): float(value) for key, value in raw.get("metrics", {}).items()},
                case_fingerprint=str(raw.get("case_fingerprint", "")),
                case_family=str(raw.get("case_family", "")),
            )
            results.setdefault(item.arm, []).append(item)
        return results

    def decide(
        self,
        *,
        results: dict[str, list[ArmResult]],
        seed: str,
        certification: bool,
        minimum_effect: float | None = None,
    ) -> tuple[PairedDecision, dict[str, Any]]:
        incumbent = results["incumbent"]
        candidate = results["candidate"]
        decision = judge_paired(
            incumbent=incumbent,
            candidate=candidate,
            minimum_effect=self.config.evaluation.minimum_effect if minimum_effect is None else minimum_effect,
            confidence=self.config.evaluation.confidence,
            bootstrap_samples=self.config.evaluation.bootstrap_samples,
            seed=seed,
            require_confidence=certification,
            rescue_effect=float(getattr(self.config.evaluation, "quality_scale", 1.0)),
        )
        invalid_rate = sum(not item.valid for item in results["candidate"]) / len(results["candidate"])
        candidate_cost = sum(item.usage.effective_tokens for item in candidate)
        incumbent_cost = sum(item.usage.effective_tokens for item in incumbent)
        cost_reduction_ratio = (
            (incumbent_cost - candidate_cost) / incumbent_cost if incumbent_cost > 0 else 0.0
        )
        tolerance = float(getattr(self.config.evaluation, "quality_non_regression_tolerance", 0.0))
        pair_deltas: list[float] = []
        quality_non_regression = True
        for inc, cand in zip(incumbent, candidate, strict=True):
            if not cand.valid or cand.score is None:
                quality_non_regression = False
                continue
            if inc.valid and inc.score is not None:
                delta = float(cand.score) - float(inc.score)
                pair_deltas.append(delta)
                if delta < -tolerance:
                    quality_non_regression = False
        efficiency_passed = bool(
            bool(getattr(self.config.evaluation, "allow_efficiency_promotion", True))
            and quality_non_regression
            and not any(not item.valid for item in candidate)
            and cost_reduction_ratio >= float(getattr(self.config.evaluation, "minimum_cost_reduction_ratio", 0.15))
        )
        passed = decision.passed or efficiency_passed
        reasons = [] if passed else list(decision.reasons)
        if invalid_rate > self.config.evaluation.invalid_rate_tolerance:
            passed = False
            reasons.append("invalid_rate_tolerance_exceeded")
        promotion_path = None
        if passed:
            promotion_path = "quality" if decision.passed else "efficiency"
        summary = {
            "passed": passed,
            "certification": certification,
            "candidate_vs_incumbent": decision.to_dict(),
            "reasons": sorted(set(reasons)),
            "promotion_path": promotion_path,
            "multi_objective": True,
            "cost_adjusted": False,
            "efficiency": {
                "passed": efficiency_passed,
                "quality_non_regression": quality_non_regression,
                "quality_pair_median_delta": float(statistics.median(pair_deltas)) if pair_deltas else None,
                "cost_reduction_ratio": cost_reduction_ratio,
                "required_cost_reduction_ratio": float(getattr(self.config.evaluation, "minimum_cost_reduction_ratio", 0.15)),
            },
        }
        return decision, summary

    def _adjust(self, values: list[ArmResult]) -> list[ArmResult]:
        adjusted: list[ArmResult] = []
        for item in values:
            score = cost_adjusted_score(
                item,
                token_penalty_per_1k=self.config.evaluation.token_penalty_per_1k,
                call_penalty=self.config.evaluation.call_penalty,
            )
            adjusted.append(replace(item, score=score))
        return adjusted

    def _generate_once(self, *, working_directory: Path, **kwargs: Any) -> GeneratedArtifact:
        manifest_path = working_directory / "generation-manifest.json"
        artifact_path = working_directory / "artifact.json"
        if manifest_path.is_file() and artifact_path.is_file():
            manifest = read_json(manifest_path)
            payload = read_json(artifact_path)
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if bytes_hash(raw) != manifest.get("artifact_sha256"):
                raise IntegrityError(f"resumed generation artifact changed: {working_directory}")
            usage_raw = manifest.get("usage", {})
            usage = Usage(**{key: int(usage_raw.get(key, 0)) for key in Usage.__dataclass_fields__})
            return GeneratedArtifact(
                payload=payload,
                raw_bytes=raw,
                usage=usage,
                artifact_sha256=bytes_hash(raw),
                call_receipts=tuple(str(item) for item in manifest.get("call_receipts", ())),
            )
        return self.executor.execute(working_directory=working_directory, budget=self.config.budget, artifact_contract=self.config.artifact_contract, **kwargs)
