from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from loop_evolution.agents import Architect, LoopExecutor, load_architect, load_executor
from loop_evolution.batch import (
    PAIR_COUNT,
    PROTOCOL_ID,
    judge_batch,
    pair_verdict,
    rejection_is_irreversible,
)
from loop_evolution.common import (
    atomic_json,
    canonical_json,
    content_hash,
    parse_json_object,
    read_json,
    resolve_path,
)
from loop_evolution.evaluator import ExistingChessBench, promoted_package
from loop_evolution.plan import LoopPlan, direct_control_plan
from loop_evolution.platform.runtime.answers import extract_final_answer
from loop_evolution.state import StateStore
from loop_evolution.usage import empty_usage, normalize_usage, pair_usage, sum_usage


class EvolutionPipeline:
    def __init__(
        self,
        config_path: Path,
        *,
        architect: Architect | None = None,
        executor: LoopExecutor | None = None,
        evaluator: ExistingChessBench | None = None,
    ) -> None:
        self.config_path = config_path.resolve()
        self.base = self.config_path.parent
        self.config = read_json(self.config_path)
        if self.config.get("schema_version") not in {1, 2}:
            raise ValueError("config schema_version must be 1 or 2")
        self.workspace = resolve_path(self.base, str(self.config["workspace_dir"]))
        self.store = StateStore(self.workspace, self.config)
        self._architect = architect
        self._executor = executor
        self._evaluator = evaluator

    @property
    def architect(self) -> Architect:
        if self._architect is None:
            path = resolve_path(self.base, str(self.config["proposal_policy_path"]))
            self._architect = load_architect(path)
        return self._architect

    @property
    def executor(self) -> LoopExecutor:
        if self._executor is None:
            path = resolve_path(self.base, str(self.config["execution_policy_path"]))
            self._executor = load_executor(path)
        return self._executor

    @property
    def evaluator(self) -> ExistingChessBench:
        if self._evaluator is None:
            path = resolve_path(self.base, str(self.config["benchmark_case_dir"]))
            cache_raw = self.config.get("benchmark_result_dir")
            cache_dir = resolve_path(self.base, str(cache_raw)) if cache_raw else None
            self._evaluator = ExistingChessBench(path, result_cache_dir=cache_dir)
        return self._evaluator

    def initialize(self) -> dict[str, Any]:
        initial = dict(self.config["initial_champion"])
        self.store.initialize(
            artifact_path=resolve_path(self.base, str(initial["artifact_path"])),
            receipt_path=resolve_path(self.base, str(initial["benchmark_receipt_path"])),
            loop_structure_path=resolve_path(self.base, str(initial["loop_structure_path"])),
            label=str(initial["label"]),
        )
        return self.store.migrate_to_matched_pairs()

    def migrate(self) -> dict[str, Any]:
        return self.store.migrate_to_matched_pairs()

    def status(self) -> dict[str, Any]:
        self.store.migrate_to_matched_pairs()
        return read_json(self.store.capsule_path)

    def abort_next_round(self, reason: str) -> dict[str, Any]:
        """Archive, without adjudication, the incomplete round after current state."""

        state = self.store.migrate_to_matched_pairs()
        round_index = int(state["round_index"]) + 1
        rounds_root = (self.workspace / "rounds").resolve()
        round_dir = (rounds_root / f"r{round_index:04d}").resolve()
        if round_dir.parent != rounds_root or not round_dir.is_dir():
            raise RuntimeError(f"there is no incomplete next round to abort: {round_dir}")
        if (round_dir / "round-summary.json").is_file():
            raise RuntimeError("refusing to abort a completed round")
        archive_root = (self.workspace / "archive" / "aborted-rounds").resolve()
        archive_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = archive_root / f"r{round_index:04d}-{stamp}"
        if target.exists():
            raise RuntimeError(f"abort archive target already exists: {target}")
        shutil.move(str(round_dir), str(target))
        record = {
            "event": "incomplete_round_aborted",
            "round": round_index,
            "completed_round_preserved": int(state["round_index"]),
            "champion_package_preserved": state["champion"]["package_id"],
            "reason": reason,
            "archive_path": str(target),
            "adjudicated": False,
        }
        record_sha = self.store.append_archive(record)
        return {**record, "archive_record_sha256": record_sha}

    def recover_round(self) -> dict[str, Any]:
        """Finalize archive/capsule metadata after a post-state-write interruption."""

        state = self.store.migrate_to_matched_pairs()
        round_index = int(state["round_index"])
        round_dir = self.workspace / "rounds" / f"r{round_index:04d}"
        summary_path = round_dir / "round-summary.json"
        if summary_path.is_file():
            self.store.write_capsule(state)
            return read_json(summary_path)
        batch_path = round_dir / "evaluation" / "batch-decision.json"
        plan_path = round_dir / "generation" / "normalized-plan.json"
        recent = list(state.get("recent_outcomes", []))
        if (
            not batch_path.is_file()
            or not plan_path.is_file()
            or not recent
            or int(recent[-1].get("round", -1)) != round_index
        ):
            raise RuntimeError("current state does not describe a recoverable completed round")
        batch = read_json(batch_path)
        plan = self._load_plan(plan_path)
        anchor_package = str(
            read_json(self.workspace / "rounds" / f"r{round_index - 1:04d}" / "round-summary.json").get(
                "champion_package_after", state["champion"]["package_id"]
            )
            if round_index > 1
            else state["champion"]["package_id"]
        )
        record = {
            "event": "matched_round_completed_recovered",
            "round": round_index,
            "protocol": PROTOCOL_ID,
            "anchor_package_before": anchor_package,
            "candidate_structure_id": plan.structure_id,
            "candidate_plan_path": str(plan_path.resolve()),
            "pair_summary_paths": [
                str((round_dir / "pairs" / f"pair-{index:02d}" / "pair-summary.json").resolve())
                for index in range(1, int(batch["completed_pair_count"]) + 1)
            ],
            "batch_decision": batch,
            "promoted": bool(batch["promoted"]),
            "champion_package_after": state["champion"]["package_id"],
            "stagnation_count_after": state["stagnation_count"],
            "local_refinement_count_after": state.get("local_refinement_count", 0),
            "emergent_failure_count_after": state.get("emergent_failure_count", 0),
            "proposal_mode_after": state["proposal_mode"],
            "recovery_reason": "state saved before bounded capsule/archive finalization",
        }
        record_sha = self.store.append_archive(record)
        summary = {**record, "archive_record_sha256": record_sha}
        atomic_json(summary_path, summary)
        self.store.write_capsule(state)
        return summary

    def reconcile_round(self, round_index: int, authoritative_record_sha256: str) -> dict[str, Any]:
        """Supersede a late orphan-process record without rewriting the append-only archive."""

        state = self.store.migrate_to_matched_pairs()
        archive_path = self.workspace / "archive" / "rounds.jsonl"
        records = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
        authoritative = next(
            (
                record
                for record in records
                if record.get("record_sha256") == authoritative_record_sha256
            ),
            None,
        )
        if authoritative is None or int(authoritative.get("round", -1)) != round_index:
            raise RuntimeError("authoritative archive record was not found for the requested round")
        superseded = [
            str(record["record_sha256"])
            for record in records
            if int(record.get("round", -1)) == round_index
            and record.get("record_sha256") != authoritative_record_sha256
            and record.get("event") != "round_record_superseded"
        ]
        existing_correction = next(
            (
                record
                for record in records
                if record.get("event") == "round_record_superseded"
                and int(record.get("round", -1)) == round_index
                and record.get("authoritative_record_sha256") == authoritative_record_sha256
                and list(record.get("superseded_record_sha256", [])) == superseded
            ),
            None,
        )
        if existing_correction is None:
            correction_sha = self.store.append_archive(
                {
                    "event": "round_record_superseded",
                    "round": round_index,
                    "authoritative_record_sha256": authoritative_record_sha256,
                    "superseded_record_sha256": superseded,
                    "reason": "late orphan process wrote results after the authoritative run completed",
                }
            )
        else:
            correction_sha = str(existing_correction["record_sha256"])
        round_dir = self.workspace / "rounds" / f"r{round_index:04d}"
        atomic_json(round_dir / "evaluation" / "batch-decision.json", authoritative["batch_decision"])
        summary = {
            **authoritative,
            "archive_record_sha256": authoritative_record_sha256,
            "reconciliation_record_sha256": correction_sha,
            "superseded_record_sha256": superseded,
        }
        atomic_json(round_dir / "round-summary.json", summary)
        self.store.write_capsule(state)
        return summary

    def readjudicate_relative_promotion(self, round_index: int) -> dict[str, Any]:
        """Promote a completed batch after removal of the legacy stored-anchor gate."""

        state = self.store.migrate_to_matched_pairs()
        if round_index != int(state["round_index"]):
            raise RuntimeError("only the current completed round can be readjudicated")
        round_dir = self.workspace / "rounds" / f"r{round_index:04d}"
        summary_path = round_dir / "round-summary.json"
        existing_summary = read_json(summary_path)
        if (
            existing_summary.get("event") == "matched_round_readjudicated"
            and existing_summary.get("promoted") is True
        ):
            return existing_summary

        pair_paths = [Path(path) for path in existing_summary["pair_summary_paths"]]
        pairs = [read_json(path) for path in pair_paths]
        batch = judge_batch(
            pairs=pairs,
            anchor_elo=float(existing_summary["batch_decision"]["anchor_elo"]),
            completed_early=len(pairs) < PAIR_COUNT,
        )
        if not batch["promoted"]:
            raise RuntimeError("the completed round does not satisfy the relative promotion contract")
        representative_pair = batch["representative_candidate_pair"]
        if not isinstance(representative_pair, int):
            raise RuntimeError("the winning batch has no representative candidate")

        savepoint_path = (
            self.workspace
            / "savepoints"
            / f"before-r{round_index:04d}-relative-readjudication.json"
        )
        atomic_json(
            savepoint_path,
            {
                "schema_version": 1,
                "reason": "readjudicate under the relative matched-three-pair promotion contract",
                "state": state,
                "round_summary": existing_summary,
                "state_sha256": content_hash(state),
            },
        )
        plan_path = round_dir / "generation" / "normalized-plan.json"
        plan = self._load_plan(plan_path)
        representative = pairs[representative_pair - 1]
        promoted = promoted_package(
            workspace=self.workspace,
            round_index=round_index,
            plan=plan.payload,
            artifact_path=Path(representative["candidate_artifact_path"]),
            evaluation=representative["candidate_evaluation"],
            source_plan_path=plan_path,
        )

        recent = []
        for outcome in state["recent_outcomes"]:
            if int(outcome.get("round", -1)) == round_index:
                recent.append(
                    {
                        **outcome,
                        "candidate_wins": batch["candidate_wins"],
                        "candidate_losses": batch["candidate_losses"],
                        "ties": batch["ties"],
                        "candidate_median_elo": batch["candidate_median_elo"],
                        "incumbent_median_elo": batch["incumbent_median_elo"],
                        "median_delta": batch["median_delta"],
                        "representative_candidate_elo": batch["representative_candidate_elo"],
                        "promoted": True,
                        "failure_kind": None,
                    }
                )
            else:
                recent.append(outcome)
        frontier = []
        for item in state["hypothesis_frontier"]:
            if int(item.get("round", -1)) == round_index:
                frontier.append(
                    {
                        **item,
                        "status": "supported",
                        "evidence": (
                            f"relative matched batch {batch['candidate_wins']}W/"
                            f"{batch['candidate_losses']}L/{batch['ties']}T, "
                            f"median delta {batch['median_delta']}"
                        ),
                    }
                )
            else:
                frontier.append(item)
        lesson_prefix = f"Under the round-{round_index} matched conditions"
        lessons = [
            lesson
            for lesson in state["conditional_lessons"]
            if not str(lesson).startswith(lesson_prefix)
        ]
        change = plan.payload["hypothesis"]["causal_change"]
        lessons.append(
            f"Under the round-{round_index} relative matched conditions, changing "
            f"{change['factor']} from {change['before']} to {change['after']} won "
            f"{batch['candidate_wins']}-{batch['candidate_losses']} with median Elo delta "
            f"{batch['median_delta']} and promoted."
        )
        search_control = self.store.advance_search_control(
            state,
            tested_mode=plan.proposal_mode,
            promoted=True,
        )
        updated = {
            **state,
            "champion": promoted,
            **search_control,
            "recent_outcomes": recent,
            "hypothesis_frontier": frontier,
            "conditional_lessons": lessons,
            "last_readjudication": {
                "round": round_index,
                "reason": "legacy stored-anchor gate removed from relative promotion contract",
                "savepoint_path": str(savepoint_path.resolve()),
            },
        }
        atomic_json(round_dir / "evaluation" / "batch-decision.json", batch)
        self.store.write_capsule(updated)
        self.store.save(updated)
        record = {
            "event": "matched_round_readjudicated",
            "round": round_index,
            "protocol": PROTOCOL_ID,
            "reason": "legacy stored-anchor gate removed from relative promotion contract",
            "supersedes_record_sha256": existing_summary.get("archive_record_sha256"),
            "anchor_package_before": existing_summary["anchor_package_before"],
            "candidate_structure_id": plan.structure_id,
            "candidate_plan_path": str(plan_path.resolve()),
            "pair_summary_paths": [str(path.resolve()) for path in pair_paths],
            "batch_decision": batch,
            "promoted": True,
            "champion_package_after": promoted["package_id"],
            "stagnation_count_after": updated["stagnation_count"],
            "local_refinement_count_after": updated["local_refinement_count"],
            "emergent_failure_count_after": updated["emergent_failure_count"],
            "proposal_mode_after": updated["proposal_mode"],
            "savepoint_path": str(savepoint_path.resolve()),
        }
        record_sha = self.store.append_archive(record)
        summary = {**record, "archive_record_sha256": record_sha}
        atomic_json(summary_path, summary)
        return summary

    def _round_dir(self, state: dict[str, Any]) -> Path:
        return self.workspace / "rounds" / f"r{int(state['round_index']) + 1:04d}"

    def propose(self) -> LoopPlan:
        state = self.store.migrate_to_matched_pairs()
        capsule = read_json(self.store.capsule_path)
        round_dir = self._round_dir(state)
        normalized_path = round_dir / "generation" / "normalized-plan.json"
        if normalized_path.is_file():
            plan = LoopPlan.from_payload(
                read_json(normalized_path), expected_mode=str(state["proposal_mode"])
            )
            plan.validate_search_context(capsule)
            return plan
        response_path = round_dir / "generation" / "architect-response.txt"
        receipt_path = round_dir / "generation" / "architect-receipt.json"
        if response_path.is_file() and receipt_path.is_file():
            payload = parse_json_object(
                extract_final_answer(response_path.read_text(encoding="utf-8"))
            )
            plan = LoopPlan.from_payload(payload, expected_mode=str(state["proposal_mode"]))
            plan.validate_search_context(capsule)
            if self.store.plan_seen(plan.structure_id):
                raise RuntimeError(f"exact candidate loop structure was already tested: {plan.structure_id}")
            atomic_json(normalized_path, plan.payload)
            return plan
        if round_dir.exists():
            unexpected = {item.name for item in round_dir.iterdir()} - {"generation"}
            if unexpected:
                raise RuntimeError(
                    f"round directory contains an incomplete evaluated attempt: {round_dir}"
                )
        round_dir.mkdir(parents=True, exist_ok=True)
        plan = self.architect.propose(capsule=capsule, round_dir=round_dir)
        plan.validate_search_context(capsule)
        if self.store.plan_seen(plan.structure_id):
            raise RuntimeError(f"exact candidate loop structure was already tested: {plan.structure_id}")
        return plan

    @staticmethod
    def _load_plan(path: Path) -> LoopPlan:
        payload = read_json(path)
        return LoopPlan.from_payload(
            payload, expected_mode=str(payload.get("proposal_mode", "general"))
        )

    @staticmethod
    def _engine_source_sha256(artifact_path: Path) -> str:
        payload = read_json(artifact_path)
        source = str(payload.get("files", {}).get("engine.py", ""))
        if not source:
            raise RuntimeError(f"anchor artifact has no engine.py: {artifact_path}")
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def _bootstrap_champion(self) -> dict[str, Any]:
        archive_path = self.workspace / "archive" / "rounds.jsonl"
        for line in archive_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("event") == "bootstrap" and isinstance(record.get("champion"), dict):
                return dict(record["champion"])
        raise RuntimeError("bootstrap champion is missing from the archive")

    def _anchor_descriptor(
        self,
        *,
        role: str,
        artifact_path: Path,
        metrics: dict[str, Any],
        origin: str,
    ) -> dict[str, Any]:
        resolved = artifact_path.resolve()
        return {
            "role": role,
            "anchor_id": f"anchor_{self._engine_source_sha256(resolved)[:16]}",
            "artifact_path": str(resolved),
            "engine_source_sha256": self._engine_source_sha256(resolved),
            "metrics": dict(metrics),
            "origin": origin,
        }

    def _select_anchor_panel(self, champion: dict[str, Any]) -> list[dict[str, Any]]:
        current = self._anchor_descriptor(
            role="current_champion",
            artifact_path=Path(champion["engine"]["artifact_path"]),
            metrics=dict(champion["metrics"]),
            origin=f"champion:{champion['package_id']}",
        )
        bootstrap = self._bootstrap_champion()
        frozen = self._anchor_descriptor(
            role="frozen_lineage_baseline",
            artifact_path=Path(bootstrap["engine"]["artifact_path"]),
            metrics=dict(bootstrap["metrics"]),
            origin=f"bootstrap:{bootstrap['package_id']}",
        )

        pool: list[dict[str, Any]] = []
        promoted_round = int(champion.get("promoted_round", 0))
        for round_index in range(promoted_round, 0, -1):
            for pair_index in range(1, PAIR_COUNT + 1):
                summary_path = (
                    self.workspace
                    / "rounds"
                    / f"r{round_index:04d}"
                    / "pairs"
                    / f"pair-{pair_index:02d}"
                    / "pair-summary.json"
                )
                if not summary_path.is_file():
                    continue
                summary = read_json(summary_path)
                artifact_raw = summary.get("candidate_artifact_path")
                evaluation = summary.get("candidate_evaluation")
                if not artifact_raw or not isinstance(evaluation, dict) or not evaluation.get("valid"):
                    continue
                descriptor = self._anchor_descriptor(
                    role="recent_promotion_alternate",
                    artifact_path=Path(str(artifact_raw)),
                    metrics=evaluation,
                    origin=f"round:{round_index}:pair:{pair_index}:candidate",
                )
                pool.append(descriptor)

        used = {current["engine_source_sha256"], frozen["engine_source_sha256"]}
        alternate = next(
            (item for item in pool if item["engine_source_sha256"] not in used),
            None,
        )
        if alternate is None:
            alternate = {**current, "role": "diversity_fallback", "origin": current["origin"]}
        return [current, frozen, alternate]

    def _anchor_panel(self, root_dir: Path, champion: dict[str, Any]) -> list[dict[str, Any]]:
        panel_path = root_dir / "evaluation" / "anchor-panel.json"
        if panel_path.is_file():
            payload = read_json(panel_path)
            anchors = payload.get("anchors")
            if not isinstance(anchors, list) or len(anchors) != PAIR_COUNT:
                raise RuntimeError("stored anchor panel is invalid")
            return [dict(item) for item in anchors]
        anchors = self._select_anchor_panel(champion)
        atomic_json(
            panel_path,
            {
                "schema_version": 1,
                "policy": "current champion + frozen lineage baseline + recent promotion alternate",
                "refresh_rule": "panel is frozen per round; current and alternate change only after promotion",
                "common_anchor_within_pair": True,
                "distinct_anchor_count": len({item["engine_source_sha256"] for item in anchors}),
                "anchors": anchors,
            },
        )
        return anchors

    def _builtins(
        self,
        *,
        plan: LoopPlan,
        anchor_metrics: dict[str, Any],
        capsule: dict[str, Any],
        anchor_text: str,
    ) -> dict[str, str]:
        return {
            "task": self.evaluator.task,
            "champion_engine": anchor_text,
            "champion_metrics": canonical_json(anchor_metrics),
            "state_capsule": canonical_json(capsule),
            "candidate_hypothesis": canonical_json(plan.hypothesis),
            "loop_structure": canonical_json(plan.structure),
        }

    def _run_arm(
        self,
        *,
        plan: LoopPlan,
        arm_dir: Path,
        builtins: dict[str, str],
    ) -> dict[str, Any]:
        evaluation_path = arm_dir / "evaluation" / "evaluation.json"
        artifact_path = arm_dir / "artifact" / "final-output.json"
        if evaluation_path.is_file():
            evaluation = read_json(evaluation_path)
            return {
                "artifact_path": str(artifact_path.resolve()) if artifact_path.is_file() else None,
                "evaluation": evaluation,
                "execution_traces": [],
                "reused": True,
            }

        inputs_dir = arm_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        (inputs_dir / "anchor-engine.txt").write_text(
            builtins["champion_engine"], encoding="utf-8"
        )
        atomic_json(
            inputs_dir / "arm-contract.json",
            {
                "structure_id": plan.structure_id,
                "task": builtins["task"],
                "official_benchmark_is_postrun_only": True,
                "allowed_development_evidence": [
                    "syntax",
                    "UCI handshake",
                    "legal move behavior",
                    "perft",
                    "determinism",
                    "timeouts",
                    "task-general regression checks",
                ],
            },
        )
        try:
            candidate, traces = self.executor.execute(
                plan=plan,
                round_dir=arm_dir,
                builtins=builtins,
            )
            artifact_path = Path(candidate["artifact_path"])
            evaluation = self.evaluator.evaluate(
                artifact_path,
                evaluation_dir=arm_dir / "evaluation",
            )
        except (ValueError, json.JSONDecodeError) as exc:
            traces = []
            evaluation = {
                "valid": False,
                "failure_kind": f"invalid_arm_output:{type(exc).__name__}",
                "failure_detail": str(exc),
                "elo": None,
            }
            atomic_json(evaluation_path, evaluation)
        return {
            "artifact_path": str(artifact_path.resolve()) if artifact_path.is_file() else None,
            "evaluation": evaluation,
            "execution_traces": traces,
            "reused": False,
        }

    def _run_pair(
        self,
        *,
        pair_index: int,
        root_dir: Path,
        anchor: dict[str, Any],
        incumbent_plan: LoopPlan,
        candidate_plan: LoopPlan,
        incumbent_builtins: dict[str, str],
        candidate_builtins: dict[str, str],
    ) -> dict[str, Any]:
        pair_dir = root_dir / "pairs" / f"pair-{pair_index:02d}"
        summary_path = pair_dir / "pair-summary.json"
        if summary_path.is_file():
            return read_json(summary_path)

        order = ["incumbent", "candidate"] if pair_index % 2 else ["candidate", "incumbent"]
        max_attempts = max(1, int(self.config.get("invalid_pair_max_attempts", 3)))
        attempt_summaries: list[str] = []
        for attempt_index in range(1, max_attempts + 1):
            attempt_dir = pair_dir / "attempts" / f"attempt-{attempt_index:02d}"
            attempt_summary_path = attempt_dir / "attempt-summary.json"
            if attempt_summary_path.is_file():
                attempt_summary = read_json(attempt_summary_path)
            else:
                arms = self._recover_interrupted_attempt(attempt_dir)
                recovered_interruption = arms is not None
                if arms is None:
                    arms = {}
                    for arm in order:
                        arms[arm] = self._run_arm(
                            plan=incumbent_plan if arm == "incumbent" else candidate_plan,
                            arm_dir=attempt_dir / arm,
                            builtins=(
                                incumbent_builtins if arm == "incumbent" else candidate_builtins
                            ),
                        )
                verdict = pair_verdict(
                    arms["incumbent"]["evaluation"], arms["candidate"]["evaluation"]
                )
                attempt_summary = {
                    "schema_version": 1,
                    "pair": pair_index,
                    "attempt": attempt_index,
                    "execution_order": order,
                    "common_anchor": True,
                    "anchor": anchor,
                    "incumbent_structure_id": incumbent_plan.structure_id,
                    "candidate_structure_id": candidate_plan.structure_id,
                    "incumbent_artifact_path": arms["incumbent"]["artifact_path"],
                    "candidate_artifact_path": arms["candidate"]["artifact_path"],
                    "incumbent_evaluation": arms["incumbent"]["evaluation"],
                    "candidate_evaluation": arms["candidate"]["evaluation"],
                    "verdict": verdict.as_dict(),
                    "execution_traces": {
                        "incumbent": arms["incumbent"]["execution_traces"],
                        "candidate": arms["candidate"]["execution_traces"],
                    },
                    "recovered_interruption": recovered_interruption,
                }
                atomic_json(attempt_summary_path, attempt_summary)
            attempt_summaries.append(str(attempt_summary_path.resolve()))
            if str(attempt_summary["verdict"]["verdict"]) != "invalid":
                attempt_payloads = [read_json(Path(path)) for path in attempt_summaries]
                summary = {
                    **attempt_summary,
                    "schema_version": 4,
                    "attempts_used": attempt_index,
                    "max_attempts": max_attempts,
                    "attempt_summary_paths": attempt_summaries,
                    "invalid_attempts_exhausted": False,
                    "token_usage": pair_usage(attempt_payloads, accepted=True),
                }
                atomic_json(summary_path, summary)
                return summary

        attempt_payloads = [read_json(Path(path)) for path in attempt_summaries]
        summary = {
            **attempt_summary,
            "schema_version": 4,
            "attempts_used": max_attempts,
            "max_attempts": max_attempts,
            "attempt_summary_paths": attempt_summaries,
            "invalid_attempts_exhausted": True,
            "token_usage": pair_usage(attempt_payloads, accepted=False),
        }
        atomic_json(summary_path, summary)
        return summary

    def _recover_interrupted_attempt(
        self, attempt_dir: Path
    ) -> dict[str, dict[str, Any]] | None:
        if not attempt_dir.is_dir() or not any(attempt_dir.rglob("*")):
            return None
        arms: dict[str, dict[str, Any]] = {}
        for arm in ("incumbent", "candidate"):
            arm_dir = attempt_dir / arm
            evaluation_path = arm_dir / "evaluation" / "evaluation.json"
            artifact_path = arm_dir / "artifact" / "final-output.json"
            receipts = sorted((arm_dir / "execution" / "calls").glob("*.receipt.json"))
            evaluation = (
                read_json(evaluation_path)
                if evaluation_path.is_file()
                else {
                    "valid": False,
                    "failure_kind": "interrupted_partial_arm",
                    "elo": None,
                    "valid_games": 0,
                    "candidate_failures": 1,
                }
            )
            arms[arm] = {
                "artifact_path": str(artifact_path.resolve()) if artifact_path.is_file() else None,
                "evaluation": evaluation,
                "execution_traces": [read_json(path) for path in receipts],
                "reused": True,
            }
        return arms

    def _run_matched_batch(
        self,
        *,
        root_dir: Path,
        champion: dict[str, Any],
        incumbent_plan: LoopPlan,
        candidate_plan: LoopPlan,
        capsule: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        anchors = self._anchor_panel(root_dir, champion)
        pairs: list[dict[str, Any]] = []
        completed_early = False
        for pair_index in range(1, PAIR_COUNT + 1):
            anchor = anchors[pair_index - 1]
            anchor_text = Path(anchor["artifact_path"]).read_text(encoding="utf-8")
            incumbent_builtins = self._builtins(
                plan=incumbent_plan,
                anchor_metrics=dict(anchor["metrics"]),
                capsule=capsule,
                anchor_text=anchor_text,
            )
            candidate_builtins = self._builtins(
                plan=candidate_plan,
                anchor_metrics=dict(anchor["metrics"]),
                capsule=capsule,
                anchor_text=anchor_text,
            )
            pair = self._run_pair(
                pair_index=pair_index,
                root_dir=root_dir,
                anchor=anchor,
                incumbent_plan=incumbent_plan,
                candidate_plan=candidate_plan,
                incumbent_builtins=incumbent_builtins,
                candidate_builtins=candidate_builtins,
            )
            pairs.append(pair)
            verdicts = [
                pair_verdict(item["incumbent_evaluation"], item["candidate_evaluation"])
                for item in pairs
            ]
            invalid_pair = verdicts[-1].verdict == "invalid"
            if invalid_pair or (
                len(pairs) < PAIR_COUNT and rejection_is_irreversible(verdicts)
            ):
                completed_early = True
                break
        batch = judge_batch(
            pairs=pairs,
            anchor_elo=float(champion["metrics"]["elo"]),
            completed_early=completed_early,
        )
        batch["anchor_policy"] = "three precommitted diverse anchors; common within each pair"
        batch["anchor_panel"] = [
            {
                "pair": index,
                "anchor_id": anchor["anchor_id"],
                "role": anchor["role"],
                "origin": anchor["origin"],
                "engine_source_sha256": anchor["engine_source_sha256"],
                "elo": anchor["metrics"].get("elo"),
            }
            for index, anchor in enumerate(anchors, start=1)
        ]
        batch["distinct_anchor_count"] = len(
            {anchor["engine_source_sha256"] for anchor in anchors}
        )
        return pairs, batch

    def _write_round_token_accounting(
        self, *, round_dir: Path, pairs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        proposal_receipt = round_dir / "generation" / "architect-receipt.json"
        attempt_receipts = sorted(
            (round_dir / "generation" / "attempts").glob(
                "attempt-*/architect-receipt.json"
            )
        )
        if attempt_receipts:
            proposal_attempts = [
                normalize_usage(read_json(path).get("usage")) for path in attempt_receipts
            ]
            proposal = sum_usage(proposal_attempts)
            proposal_invalid = sum_usage(proposal_attempts[:-1])
        else:
            proposal = (
                normalize_usage(read_json(proposal_receipt).get("usage"))
                if proposal_receipt.is_file()
                else empty_usage()
            )
            proposal_invalid = empty_usage()
        pair_ledgers = [
            {
                "pair": int(pair["pair"]),
                "anchor_id": pair.get("anchor", {}).get("anchor_id"),
                "anchor_role": pair.get("anchor", {}).get("role"),
                **pair.get("token_usage", {}),
            }
            for pair in pairs
        ]
        incumbent = sum_usage(
            item.get("all_attempts", {}).get("incumbent") for item in pair_ledgers
        )
        candidate = sum_usage(
            item.get("all_attempts", {}).get("candidate") for item in pair_ledgers
        )
        internal = sum_usage([incumbent, candidate])
        invalid = sum_usage(
            item.get("invalid_attempts", {}).get("combined") for item in pair_ledgers
        )
        ledger = {
            "schema_version": 1,
            "accounting_rule": (
                "total=input+output; effective=(input-cached_input)+output; "
                "reasoning_output is a subset of output and is not added again"
            ),
            "proposal_sol_xhigh": proposal,
            "proposal_invalid_spend": proposal_invalid,
            "internal_loop_luna_high": {
                "incumbent": incumbent,
                "candidate": candidate,
                "combined": internal,
                "invalid_retry_spend": invalid,
            },
            "round_total": sum_usage([proposal, internal]),
            "pairs": pair_ledgers,
        }
        path = round_dir / "evaluation" / "token-accounting.json"
        atomic_json(path, ledger)
        return {**ledger, "path": str(path.resolve())}

    def run_round(self) -> dict[str, Any]:
        state = self.store.migrate_to_matched_pairs()
        plan = self.propose()
        return self._execute_plan_round(
            state=state,
            plan=plan,
            event="matched_round_completed",
        )

    def run_fixed_round(self, plan_path: Path) -> dict[str, Any]:
        """Audit one pre-existing challenger plan without invoking the architect."""

        state = self.store.migrate_to_matched_pairs()
        payload = read_json(plan_path.resolve())
        plan = LoopPlan.from_payload(
            payload,
            expected_mode=str(payload.get("proposal_mode", state["proposal_mode"])),
        )
        round_dir = self._round_dir(state)
        normalized_path = round_dir / "generation" / "normalized-plan.json"
        if normalized_path.is_file():
            existing = LoopPlan.from_payload(
                read_json(normalized_path), expected_mode=plan.proposal_mode
            )
            if existing.structure_id != plan.structure_id:
                raise RuntimeError("fixed round already contains a different candidate plan")
            plan = existing
        else:
            atomic_json(normalized_path, plan.payload)
        return self._execute_plan_round(
            state=state,
            plan=plan,
            event="fixed_challenger_requalification_completed",
        )

    def _execute_plan_round(
        self,
        *,
        state: dict[str, Any],
        plan: LoopPlan,
        event: str,
    ) -> dict[str, Any]:
        round_index = int(state["round_index"]) + 1
        round_dir = self._round_dir(state)
        if self.store.plan_seen(plan.structure_id):
            raise RuntimeError(f"exact candidate loop structure was already tested: {plan.structure_id}")

        champion = state["champion"]
        incumbent_plan = self._load_plan(
            Path(champion["loop_structure"]["execution_plan_path"])
        )
        capsule = read_json(self.store.capsule_path)
        pairs, batch = self._run_matched_batch(
            root_dir=round_dir,
            champion=champion,
            incumbent_plan=incumbent_plan,
            candidate_plan=plan,
            capsule=capsule,
        )
        token_accounting = self._write_round_token_accounting(
            round_dir=round_dir, pairs=pairs
        )
        atomic_json(round_dir / "evaluation" / "batch-decision.json", batch)

        promoted = None
        representative_pair = batch.get("representative_candidate_pair")
        if batch["promoted"] and isinstance(representative_pair, int):
            representative = pairs[representative_pair - 1]
            promoted = promoted_package(
                workspace=self.workspace,
                round_index=round_index,
                plan=plan.payload,
                artifact_path=Path(representative["candidate_artifact_path"]),
                evaluation=representative["candidate_evaluation"],
                source_plan_path=round_dir / "generation" / "normalized-plan.json",
            )

        updated = self.store.apply_batch_outcome(
            state=state,
            round_index=round_index,
            plan=plan.payload,
            batch=batch,
            promoted_package=promoted,
        )
        record = {
            "event": event,
            "round": round_index,
            "protocol": PROTOCOL_ID,
            "anchor_package_before": champion["package_id"],
            "incumbent_structure_id": champion["loop_structure"]["structure_id"],
            "candidate_structure_id": plan.structure_id,
            "candidate_plan_path": str(
                (round_dir / "generation" / "normalized-plan.json").resolve()
            ),
            "pair_summary_paths": [
                str((round_dir / "pairs" / f"pair-{index:02d}" / "pair-summary.json").resolve())
                for index in range(1, len(pairs) + 1)
            ],
            "batch_decision": batch,
            "token_accounting_path": token_accounting["path"],
            "token_usage": {
                "proposal_sol_xhigh": token_accounting["proposal_sol_xhigh"],
                "proposal_invalid_spend": token_accounting["proposal_invalid_spend"],
                "internal_loop_luna_high": token_accounting["internal_loop_luna_high"],
                "round_total": token_accounting["round_total"],
            },
            "promoted": promoted is not None,
            "champion_package_after": updated["champion"]["package_id"],
            "stagnation_count_after": updated["stagnation_count"],
            "local_refinement_count_after": updated["local_refinement_count"],
            "emergent_failure_count_after": updated["emergent_failure_count"],
            "proposal_mode_after": updated["proposal_mode"],
        }
        record_sha = self.store.append_archive(record)
        summary = {**record, "archive_record_sha256": record_sha}
        atomic_json(round_dir / "round-summary.json", summary)
        return summary

    def calibrate_direct(self) -> dict[str, Any]:
        state = self.store.migrate_to_matched_pairs()
        champion = state["champion"]
        calibration_index = len(list((self.workspace / "calibrations").glob("direct-*"))) + 1
        root_dir = self.workspace / "calibrations" / f"direct-{calibration_index:04d}"
        incumbent_plan = self._load_plan(
            Path(champion["loop_structure"]["execution_plan_path"])
        )
        direct = direct_control_plan()
        pairs, comparison = self._run_matched_batch(
            root_dir=root_dir,
            champion=champion,
            incumbent_plan=incumbent_plan,
            candidate_plan=direct,
            capsule=read_json(self.store.capsule_path),
        )
        result = {
            "schema_version": 1,
            "protocol": "SAME_MODEL_DIRECT_LUNA_CALIBRATION_V1",
            "champion_structure_id": champion["loop_structure"]["structure_id"],
            "direct_structure_id": direct.structure_id,
            "pair_count": len(pairs),
            "comparison_orientation": "candidate fields are Direct; incumbent fields are champion harness",
            "comparison": comparison,
            "affects_evolutionary_champion": False,
        }
        atomic_json(root_dir / "calibration-summary.json", result)
        self.store.append_archive(
            {
                "event": "direct_calibration_completed",
                "round": int(state["round_index"]),
                "calibration_summary_path": str(
                    (root_dir / "calibration-summary.json").resolve()
                ),
                "champion_package_preserved": champion["package_id"],
            }
        )
        return result
