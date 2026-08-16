from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from loop_evolution.batch import PROMOTION_RULE, PROTOCOL_ID
from loop_evolution.common import (
    atomic_json,
    canonical_json,
    clip_text,
    content_hash,
    file_hash,
    read_json,
)
from loop_evolution.plan import LoopPlan


class StateError(RuntimeError):
    pass


def _bootstrap_execution_plan(summary: str) -> LoopPlan:
    """Normalize the selected legacy R20 behavior into the current executable schema."""

    payload = {
        "schema_version": 1,
        "proposal_mode": "general",
        "hypothesis": {
            "observed_bottleneck": "Compatibility normalization of the selected legacy R20 champion.",
            "evidence_refs": ["champion legacy selected architecture and stored structure summary"],
            "causal_change": {
                "change_count": 1,
                "factor": "execution-schema normalization",
                "before": "legacy factorized R20 program schema",
                "after": "equivalent provisional-engine plus independent-witness first-join schema",
                "why_causal": "The matched runner needs an executable plan without changing the recorded behavior.",
            },
            "expected_effect": "Reproduce the recorded champion information flow from a common anchor.",
            "falsifier": "The normalized plan cannot emit a complete legal engine.",
            "behavioral_novelty": "No new behavior; this is a compatibility representation of the champion.",
            "strengths": ["preserves the two independent upstream perspectives"],
            "risks": ["legacy supervisor-only inputs are represented by the bounded current task contract"],
        },
        "structure": {
            "name": "legacy_r20_parallel_draft_contract_join",
            "organization": "collaboration",
            "information_flow": summary,
            "stages": [
                {
                    "id": "independent_parallel_work",
                    "mode": "parallel",
                    "calls": [
                        {
                            "id": "provisional_engine",
                            "role": "independent provisional engine developer",
                            "objective": (
                                "Starting from the anchor, produce a complete stronger legal UCI engine. "
                                "Develop and check the implementation without seeing the parallel witness."
                            ),
                            "inputs": ["task", "champion_engine", "champion_metrics"],
                            "output_type": "engine",
                        },
                        {
                            "id": "contract_witness",
                            "role": "independent contract and regression analyst",
                            "objective": (
                                "Without seeing the provisional engine, derive compact task-general correctness, "
                                "preservation, legality, timing, and verification obligations for the final developer."
                            ),
                            "inputs": ["task", "champion_engine", "champion_metrics"],
                            "output_type": "analysis",
                        },
                    ],
                },
                {
                    "id": "first_join",
                    "mode": "sequential",
                    "calls": [
                        {
                            "id": "final_engine",
                            "role": "evidence-conditioned final engine developer",
                            "objective": (
                                "Produce one complete legal UCI engine. Preserve the provisional engine when it "
                                "passes the independent obligations; otherwise make only coherent evidence-backed "
                                "repairs and check the final result."
                            ),
                            "inputs": [
                                "task",
                                "champion_engine",
                                "champion_metrics",
                                "provisional_engine",
                                "contract_witness",
                            ],
                            "output_type": "engine",
                        }
                    ],
                },
            ],
            "final_call_id": "final_engine",
        },
        "compliance": {
            "changes_model_or_effort": False,
            "changes_benchmark_or_promotion": False,
            "tunes_engine_hyperparameters_as_structure": False,
            "hardcodes_benchmark": False,
        },
    }
    return LoopPlan.from_payload(payload, expected_mode="general")


def _engine_source(artifact: dict[str, Any]) -> str:
    files = artifact.get("files")
    if not isinstance(files, dict) or set(files) != {"engine.py"}:
        raise StateError("champion artifact must contain only files.engine.py")
    source = files.get("engine.py")
    if not isinstance(source, str) or not source.strip():
        raise StateError("champion engine.py is empty")
    return source


def _receipt_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    result = receipt.get("result")
    summary = result.get("summary") if isinstance(result, dict) else None
    elo = summary.get("elo") if isinstance(summary, dict) else None
    if not isinstance(summary, dict) or not summary.get("valid") or not isinstance(elo, dict):
        raise StateError("benchmark receipt has no valid Elo summary")
    if "elo_difference" not in elo:
        raise StateError("benchmark receipt has no elo_difference")
    return summary


class StateStore:
    def __init__(self, workspace: Path, config: dict[str, Any]) -> None:
        self.workspace = workspace
        self.config = config
        self.state_path = workspace / "state.json"
        self.capsule_path = workspace / "state-capsule.json"
        self.archive_index = workspace / "archive" / "rounds.jsonl"

    def _search_cycle_config(self) -> tuple[int, int, int]:
        cycle = dict(self.config.get("search_cycle", {}))
        local_limit = max(1, int(cycle.get("local_round_limit", 2)))
        emergent_limit = max(1, int(cycle.get("emergent_failure_limit", 2)))
        legacy_local = max(0, int(cycle.get("legacy_local_rounds_completed", 0)))
        return local_limit, emergent_limit, legacy_local

    def _development_config(self) -> tuple[float, int]:
        cycle = dict(self.config.get("search_cycle", {}))
        threshold = float(cycle.get("development_performance_ratio", 0.9))
        if not 0.0 < threshold <= 1.0:
            raise StateError("development_performance_ratio must be in (0, 1]")
        history_limit = max(1, int(cycle.get("counter_family_history_limit", 8)))
        return threshold, history_limit

    def _ensure_search_cycle(self, state: dict[str, Any]) -> dict[str, Any]:
        legacy_required = {"local_refinement_count", "emergent_failure_count"}
        development_required = {"development_candidate", "counter_family_history"}
        if legacy_required.union(development_required).issubset(state):
            return state
        local_limit, _, legacy_local = self._search_cycle_config()
        local_count = int(
            state.get("local_refinement_count", min(local_limit, legacy_local))
        )
        emergent_failures = int(state.get("emergent_failure_count", 0))
        old_mode = str(state.get("proposal_mode", "general"))
        mode = (
            "counter_hypothesis"
            if old_mode == "counter_hypothesis"
            else "emergent_exploration"
            if local_count >= local_limit
            else "general"
        )
        savepoint_dir = self.workspace / "savepoints"
        savepoint_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        savepoint = savepoint_dir / f"before-development-cycle-v3-{stamp}.json"
        atomic_json(
            savepoint,
            {
                "schema_version": 1,
                "reason": (
                    "adopt strengthened counter-hypothesis discovery followed by a bounded "
                    "two-general then two-emergent development cycle"
                ),
                "state": state,
                "state_sha256": content_hash(state),
            },
        )
        updated = {
            **state,
            "local_refinement_count": local_count,
            "emergent_failure_count": emergent_failures,
            "proposal_mode": mode,
            "development_candidate": None,
            "counter_family_history": list(state.get("counter_family_history", [])),
            "development_cycle_migration": {
                "local_refinement_count_seed": local_count,
                "emergent_failure_count_seed": emergent_failures,
                "savepoint_path": str(savepoint.resolve()),
            },
        }
        self.save(updated)
        self.append_archive(
            {
                "event": "development_cycle_migrated",
                "round": int(state["round_index"]),
                "local_refinement_count": local_count,
                "emergent_failure_count": emergent_failures,
                "proposal_mode": mode,
                "savepoint_path": str(savepoint.resolve()),
            }
        )
        return updated

    def advance_search_control(
        self,
        state: dict[str, Any],
        *,
        tested_mode: str,
        promoted: bool,
        batch_valid: bool = True,
        development_qualified: bool = False,
        development_candidate_update: dict[str, Any] | None = None,
        counter_family: str = "",
    ) -> dict[str, Any]:
        """Advance champion search or the bounded development mini-cycle."""

        local_limit, emergent_limit, _ = self._search_cycle_config()
        _, history_limit = self._development_config()
        local_count = int(state.get("local_refinement_count", 0))
        emergent_failures = int(state.get("emergent_failure_count", 0))
        active_development = state.get("development_candidate")
        counter_history = list(state.get("counter_family_history", []))

        if not batch_valid:
            return {
                "stagnation_count": int(state.get("stagnation_count", 0)),
                "local_refinement_count": local_count,
                "emergent_failure_count": emergent_failures,
                "proposal_mode": tested_mode,
                "development_candidate": active_development,
                "counter_family_history": counter_history,
            }

        if tested_mode == "counter_hypothesis" and counter_family.strip():
            counter_history = [*counter_history, counter_family.strip()][-history_limit:]

        if tested_mode == "general":
            local_count = min(local_limit, local_count + 1)
            emergent_failures = 0
            if active_development is not None and development_candidate_update is not None:
                active_development = development_candidate_update
            next_mode = (
                "emergent_exploration" if local_count >= local_limit else "general"
            )
        elif tested_mode == "emergent_exploration":
            if promoted:
                local_count = 0
                emergent_failures = 0
                next_mode = "general"
                active_development = None
                counter_history = []
            else:
                if active_development is not None and development_candidate_update is not None:
                    active_development = development_candidate_update
                emergent_failures = min(emergent_limit, emergent_failures + 1)
                next_mode = (
                    "counter_hypothesis"
                    if emergent_failures >= emergent_limit
                    else "emergent_exploration"
                )
                if emergent_failures >= emergent_limit:
                    active_development = None
        elif tested_mode == "counter_hypothesis":
            if promoted:
                local_count = 0
                emergent_failures = 0
                next_mode = "general"
                active_development = None
                counter_history = []
            elif development_qualified and development_candidate_update is not None:
                local_count = 0
                emergent_failures = 0
                next_mode = "general"
                active_development = development_candidate_update
            else:
                next_mode = "counter_hypothesis"
        else:
            raise StateError(f"unknown proposal mode: {tested_mode}")

        if promoted:
            active_development = None
            counter_history = []

        stagnation = 0 if promoted else int(state.get("stagnation_count", 0)) + 1
        return {
            "stagnation_count": stagnation,
            "local_refinement_count": local_count,
            "emergent_failure_count": emergent_failures,
            "proposal_mode": next_mode,
            "development_candidate": active_development,
            "counter_family_history": counter_history,
        }

    def initialize(
        self,
        *,
        artifact_path: Path,
        receipt_path: Path,
        loop_structure_path: Path,
        label: str,
    ) -> dict[str, Any]:
        if self.state_path.exists():
            raise StateError(f"workspace is already initialized: {self.state_path}")
        for path in (artifact_path, receipt_path, loop_structure_path):
            if not path.is_file():
                raise FileNotFoundError(path)

        artifact = read_json(artifact_path)
        source = _engine_source(artifact)
        source_sha = __import__("hashlib").sha256(source.encode("utf-8")).hexdigest()
        receipt = read_json(receipt_path)
        summary = _receipt_summary(receipt)
        if str(receipt.get("engine_sha256", "")) != source_sha:
            raise StateError("initial artifact engine hash does not match its benchmark receipt")
        elo_summary = summary["elo"]
        score_rate = summary.get("score_rate", elo_summary.get("score_rate"))
        if score_rate is None:
            raise StateError("benchmark receipt has no score_rate")

        structure = read_json(loop_structure_path)
        champion_dir = self.workspace / "champions" / "p0000"
        if champion_dir.exists():
            allowed_partial = {
                "final-output.json",
                "benchmark-result-receipt.json",
                "loop-structure.json",
            }
            unexpected = {item.name for item in champion_dir.iterdir()} - allowed_partial
            if unexpected:
                raise StateError(f"bootstrap directory contains unexpected partial files: {sorted(unexpected)}")
        champion_dir.mkdir(parents=True, exist_ok=True)
        local_artifact = champion_dir / "final-output.json"
        local_receipt = champion_dir / "benchmark-result-receipt.json"
        local_structure = champion_dir / "loop-structure.json"
        shutil.copy2(artifact_path, local_artifact)
        shutil.copy2(receipt_path, local_receipt)
        shutil.copy2(loop_structure_path, local_structure)

        selected = str(structure.get("selected_hypothesis", "legacy-r20"))
        hypotheses = structure.get("hypotheses", [])
        selected_item = next(
            (item for item in hypotheses if isinstance(item, dict) and item.get("id") == selected),
            {},
        )
        program = structure.get("program", {})
        call_count = sum(
            len(stage.get("calls", []))
            for stage in program.get("stages", [])
            if isinstance(stage, dict)
        )
        loop_id = f"loop_bootstrap_{content_hash(structure)[:16]}"
        package = {
            "package_id": f"package_{content_hash({'loop': loop_id, 'engine': source_sha})[:16]}",
            "promoted_round": 0,
            "label": label,
            "loop_structure": {
                "structure_id": loop_id,
                "organization": "collaboration" if call_count > 1 else "solo",
                "changed_factor": "legacy R20 factorized architecture bootstrap",
                "summary": str(
                    selected_item.get("program_summary")
                    or structure.get("hypothesis_signature")
                    or label
                ),
                "call_count": call_count,
                "spec_path": str(local_structure.resolve()),
                "source_spec_path": str(loop_structure_path.resolve()),
            },
            "engine": {
                "artifact_path": str(local_artifact.resolve()),
                "source_artifact_path": str(artifact_path.resolve()),
                "artifact_sha256": file_hash(local_artifact),
                "engine_source_sha256": source_sha,
            },
            "metrics": {
                "elo": float(summary["elo"]["elo_difference"]),
                "score_rate": float(score_rate),
                "wins": int(summary["wins"]),
                "draws": int(summary["draws"]),
                "losses": int(summary["losses"]),
                "receipt_path": str(local_receipt.resolve()),
                "source_receipt_path": str(receipt_path.resolve()),
            },
        }
        state = {
            "schema_version": 1,
            "round_index": 0,
            "champion": package,
            "stagnation_count": 0,
            "local_refinement_count": 0,
            "emergent_failure_count": 0,
            "proposal_mode": "general",
            "development_candidate": None,
            "counter_family_history": [],
            "recent_outcomes": [],
            "hypothesis_frontier": [],
            "conditional_lessons": [],
        }
        self.save(state)
        self.write_capsule(state)
        bootstrap = {
            "event": "bootstrap",
            "round": 0,
            "champion": package,
            "input_hashes": {
                "artifact": file_hash(artifact_path),
                "receipt": file_hash(receipt_path),
                "loop_structure": file_hash(loop_structure_path),
            },
        }
        self.append_archive(bootstrap)
        return state

    def load(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            raise StateError("workspace is not initialized; run init first")
        return read_json(self.state_path)

    def migrate_to_matched_pairs(self) -> dict[str, Any]:
        state = self._ensure_search_cycle(self.load())
        protocol = state.get("evaluation_protocol")
        if isinstance(protocol, dict) and protocol.get("id") == PROTOCOL_ID:
            self.write_capsule(state)
            return state

        if isinstance(protocol, dict) and protocol.get("id") == "matched-three-valid-pair-relative-v4":
            savepoint_dir = self.workspace / "savepoints"
            savepoint_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            savepoint = savepoint_dir / f"before-diverse-anchor-v5-{stamp}.json"
            atomic_json(
                savepoint,
                {
                    "schema_version": 1,
                    "reason": "adopt a precommitted three-anchor panel and token accounting",
                    "state": state,
                    "state_sha256": content_hash(state),
                },
            )
            updated = {
                **state,
                "evaluation_protocol": {
                    "id": PROTOCOL_ID,
                    "pair_count": 3,
                    "common_anchor_within_pair": True,
                    "diverse_anchor_panel": True,
                    "anchor_roles": [
                        "current_champion",
                        "frozen_lineage_baseline",
                        "recent_promotion_alternate",
                    ],
                    "anchor_refresh_rule": (
                        "freeze the panel per round; refresh current and alternate only after promotion"
                    ),
                    "pair_rule": "candidate Elo point estimate versus incumbent Elo point estimate",
                    "batch_rule": PROMOTION_RULE,
                    "representative_rule": "median-ranked candidate artifact, tie-broken by pair index",
                    "irreversible_rejection_early_stop": True,
                    "token_accounting": (
                        "separate Sol proposal and Luna internal-loop usage; include invalid retries"
                    ),
                },
                "anchor_protocol_migration": {
                    "from": "matched-three-valid-pair-relative-v4",
                    "to": PROTOCOL_ID,
                    "savepoint_path": str(savepoint.resolve()),
                },
            }
            self.write_capsule(updated)
            self.save(updated)
            self.append_archive(
                {
                    "event": "anchor_protocol_migrated",
                    "round": int(state["round_index"]),
                    "from_protocol": "matched-three-valid-pair-relative-v4",
                    "to_protocol": PROTOCOL_ID,
                    "savepoint_path": str(savepoint.resolve()),
                }
            )
            return updated

        if isinstance(protocol, dict) and protocol.get("id") == "matched-three-pair-v2":
            savepoint_dir = self.workspace / "savepoints"
            savepoint_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            savepoint = savepoint_dir / f"before-relative-promotion-v3-{stamp}.json"
            atomic_json(
                savepoint,
                {
                    "schema_version": 1,
                    "reason": "remove the legacy cross-protocol stored-anchor promotion gate",
                    "state": state,
                    "state_sha256": content_hash(state),
                },
            )
            updated = {
                **state,
                "evaluation_protocol": {
                    "id": PROTOCOL_ID,
                    "pair_count": 3,
                    "common_anchor_within_pair": True,
                    "diverse_anchor_panel": True,
                    "pair_rule": "candidate Elo point estimate versus incumbent Elo point estimate",
                    "batch_rule": (
                        "wins>losses, candidate median>incumbent median, "
                        "zero invalid candidate arms"
                    ),
                    "representative_rule": "median-ranked candidate artifact, tie-broken by pair index",
                    "irreversible_rejection_early_stop": True,
                },
                "promotion_contract_migration": {
                    "from": "matched-three-pair-v2",
                    "to": PROTOCOL_ID,
                    "savepoint_path": str(savepoint.resolve()),
                },
            }
            self.write_capsule(updated)
            self.save(updated)
            self.append_archive(
                {
                    "event": "promotion_contract_migrated",
                    "round": int(state["round_index"]),
                    "from_protocol": "matched-three-pair-v2",
                    "to_protocol": PROTOCOL_ID,
                    "savepoint_path": str(savepoint.resolve()),
                }
            )
            return updated

        savepoint_dir = self.workspace / "savepoints"
        savepoint_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        savepoint = savepoint_dir / f"before-matched-three-pair-v2-{stamp}.json"
        atomic_json(
            savepoint,
            {
                "schema_version": 1,
                "reason": "automatic non-destructive migration to matched-three-pair-v2",
                "state": state,
                "state_sha256": content_hash(state),
            },
        )

        champion = dict(state["champion"])
        loop = dict(champion["loop_structure"])
        plan_path_raw = loop.get("execution_plan_path")
        plan_path = Path(str(plan_path_raw)) if plan_path_raw else None
        if plan_path is None or not plan_path.is_file():
            normalized = _bootstrap_execution_plan(str(loop["summary"]))
            champion_dir = Path(champion["engine"]["artifact_path"]).parent
            plan_path = champion_dir / "execution-plan.json"
            atomic_json(plan_path, normalized.payload)
            loop["execution_plan_path"] = str(plan_path.resolve())
            loop["execution_structure_id"] = normalized.structure_id
        champion["loop_structure"] = loop

        legacy_recent = []
        for item in state.get("recent_outcomes", []):
            legacy_recent.append({**item, "evidence_scope": "legacy_single_artifact"})
        migrated = {
            **state,
            "schema_version": 2,
            "champion": champion,
            "recent_outcomes": legacy_recent,
            "evaluation_protocol": {
                "id": PROTOCOL_ID,
                "pair_count": 3,
                "common_anchor_within_pair": True,
                "diverse_anchor_panel": True,
                "pair_rule": "candidate Elo point estimate versus incumbent Elo point estimate",
                "batch_rule": PROMOTION_RULE,
                "representative_rule": "median-ranked candidate artifact, tie-broken by pair index",
                "irreversible_rejection_early_stop": True,
            },
            "migration": {
                "from_schema_version": state.get("schema_version", 1),
                "savepoint_path": str(savepoint.resolve()),
                "legacy_rounds_preserved_through": int(state["round_index"]),
            },
        }
        self.save(migrated)
        self.write_capsule(migrated)
        self.append_archive(
            {
                "event": "pipeline_migrated",
                "round": int(state["round_index"]),
                "protocol": "matched-three-pair-v2",
                "savepoint_path": str(savepoint.resolve()),
                "champion_package_preserved": champion["package_id"],
            }
        )
        return migrated

    def save(self, state: dict[str, Any]) -> None:
        atomic_json(self.state_path, state)

    def append_archive(self, record: dict[str, Any]) -> str:
        self.archive_index.parent.mkdir(parents=True, exist_ok=True)
        previous = ""
        if self.archive_index.is_file():
            lines = [line for line in self.archive_index.read_text(encoding="utf-8").splitlines() if line]
            if lines:
                previous = str(json.loads(lines[-1]).get("record_sha256", ""))
        body = {**record, "previous_record_sha256": previous}
        stored = {**body, "record_sha256": content_hash(body)}
        with self.archive_index.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(stored) + "\n")
        return str(stored["record_sha256"])

    def plan_seen(self, structure_id: str) -> bool:
        if not self.archive_index.is_file():
            return False
        for line in self.archive_index.read_text(encoding="utf-8").splitlines():
            if line and json.loads(line).get("candidate_structure_id") == structure_id:
                return True
        return False

    def write_capsule(self, state: dict[str, Any]) -> dict[str, Any]:
        limits = dict(self.config["capsule_limits"])
        field_limit = int(limits["field_characters"])
        champion = state["champion"]
        loop = champion["loop_structure"]
        local_limit, emergent_limit, _ = self._search_cycle_config()
        development_threshold, history_limit = self._development_config()
        development = state.get("development_candidate")
        development_started_round = (
            int(development.get("started_round", 0))
            if isinstance(development, dict)
            else 0
        )
        evaluation_protocol = dict(
            state.get(
                "evaluation_protocol",
                {"id": "legacy-single-artifact", "pair_count": 1},
            )
        )
        evaluation_protocol["development_assessment_extension"] = {
            "threshold_metric": "candidate_median_score_rate / incumbent_median_score_rate",
            "threshold": development_threshold,
            "exact_rule": "use all three valid pairs when the two-pair bounds straddle the threshold",
            "early_rule": (
                "after formal promotion is impossible, stop at two valid pairs when the best remaining "
                "case is below threshold or the worst remaining case already reaches threshold"
            ),
            "affects_formal_promotion_rule": False,
        }

        def bounded(value: Any) -> str:
            return clip_text(value, field_limit)

        def clip_entries(entries: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
            clipped: list[dict[str, Any]] = []
            for entry in entries[-maximum:]:
                clipped.append(
                    {
                        str(key): bounded(value)
                        if isinstance(value, str)
                        else value
                        for key, value in entry.items()
                        if key not in {"raw_output", "engine_source", "full_plan"}
                    }
                )
            return clipped

        capsule = {
            "schema_version": 1,
            "purpose": "bounded input for the next independent Sol max structural-architect subagent",
            "goal": bounded(self.config["goal"]),
            "forbidden_structural_hypotheses": [
                bounded(item) for item in self.config["forbidden_structural_hypotheses"]
            ],
            "current_champion": {
                "package_id": champion["package_id"],
                "loop_structure_id": loop["structure_id"],
                "organization": loop["organization"],
                "changed_factor": bounded(loop["changed_factor"]),
                "structure_summary": bounded(loop["summary"]),
                "call_count": loop["call_count"],
                "loop_structure_spec_path": loop["spec_path"],
                "execution_plan_path": loop.get("execution_plan_path", loop["spec_path"]),
                "engine_source_sha256": champion["engine"]["engine_source_sha256"],
                "elo": champion["metrics"]["elo"],
            },
            "development_candidate": (
                {
                    "lineage_id": bounded(development.get("lineage_id", "")),
                    "started_round": int(development.get("started_round", 0)),
                    "updated_round": int(development.get("updated_round", 0)),
                    "root_structure_id": bounded(
                        development.get("root_structure_id", "")
                    ),
                    "structure_id": bounded(development.get("structure_id", "")),
                    "structural_family": bounded(
                        development.get("structural_family", "")
                    ),
                    "organization": bounded(development.get("organization", "")),
                    "changed_factor": bounded(development.get("changed_factor", "")),
                    "structure_summary": bounded(
                        development.get("structure_summary", "")
                    ),
                    "execution_plan_path": development.get("execution_plan_path"),
                    "representative_engine_path": development.get(
                        "representative_engine_path"
                    ),
                    "representative_elo": development.get("representative_elo"),
                    "median_score_rate": development.get("median_score_rate"),
                    "relative_performance_ratio": development.get(
                        "relative_performance_ratio"
                    ),
                }
                if isinstance(development, dict)
                else None
            ),
            "evaluation_protocol": evaluation_protocol,
            "search_control": {
                "stagnation_count": state["stagnation_count"],
                "proposal_mode": state["proposal_mode"],
                "search_phase": (
                    "development" if isinstance(development, dict) else "champion"
                ),
                "local_refinement_count": int(state.get("local_refinement_count", 0)),
                "local_refinement_limit": local_limit,
                "local_rounds_count_promotion_too": True,
                "emergent_failure_count": int(state.get("emergent_failure_count", 0)),
                "emergent_failure_limit": emergent_limit,
                "emergent_capability_families_already_tested": [
                    bounded(item["emergent_capability_family"])
                    for item in list(state.get("recent_outcomes", []))
                    if item.get("proposal_mode") == "emergent_exploration"
                    and int(item.get("round", 0)) >= development_started_round
                    and str(item.get("emergent_capability_family", "")).strip()
                ][-emergent_limit:],
                "development_performance_ratio": development_threshold,
                "development_round_budget": {
                    "general": local_limit,
                    "emergent": emergent_limit,
                },
                "counter_families_already_tested": [
                    bounded(item)
                    for item in list(state.get("counter_family_history", []))[-history_limit:]
                ],
                "proposal_validation_max_attempts": max(
                    1, int(self.config.get("proposal_validation_max_attempts", 2))
                ),
                "phase_rule": (
                    "after two general and two distinct emergent valid rounds without promotion, "
                    "discard the active development lineage; keep generating structurally independent "
                    "counter hypotheses until one promotes or reaches the 90-percent development threshold; "
                    "then give that lineage exactly two general and two emergent valid rounds"
                ),
                "invalid_batches_consume_development_budget": False,
                "counter_mode_exit": "formal promotion or development qualification",
            },
            "recent_outcomes": clip_entries(
                list(state["recent_outcomes"]), int(limits["recent_outcomes"])
            ),
            "hypothesis_frontier": clip_entries(
                list(state["hypothesis_frontier"]), int(limits["hypothesis_frontier"])
            ),
            "promising_rejected": clip_entries(
                sorted(
                    [
                        item
                        for item in state["recent_outcomes"]
                        if not item.get("promoted")
                        and isinstance(
                            item.get("candidate_median_elo", item.get("candidate_elo")),
                            (int, float),
                        )
                    ],
                    key=lambda item: float(
                        item.get("median_delta")
                        if isinstance(item.get("median_delta"), (int, float))
                        else item.get("elo_delta", float("-inf"))
                    ),
                )[-2:],
                2,
            ),
            "conditional_lessons": [
                bounded(item)
                for item in list(state["conditional_lessons"])[-int(limits["conditional_lessons"]):]
            ],
            "targeted_archive": {
                "index_path": str(self.archive_index.resolve()),
                "rule": (
                    "Do not ingest the whole archive. Inspect only a specific cited round or hypothesis when needed."
                ),
            },
        }
        serialized = canonical_json(capsule)
        maximum = int(limits["total_characters"])
        target = max(0, maximum - 256)
        adaptive_limit = field_limit
        compactable_keys = (
            "recent_outcomes",
            "hypothesis_frontier",
            "promising_rejected",
            "conditional_lessons",
        )

        def compact_value(value: Any, limit: int) -> Any:
            if isinstance(value, str):
                return clip_text(value, limit)
            if isinstance(value, list):
                return [compact_value(item, limit) for item in value]
            if isinstance(value, dict):
                return {key: compact_value(item, limit) for key, item in value.items()}
            return value

        while len(serialized) > target and adaptive_limit > 80:
            adaptive_limit = max(80, int(adaptive_limit * 0.75))
            for key in compactable_keys:
                capsule[key] = compact_value(capsule[key], adaptive_limit)
            capsule["current_champion"]["changed_factor"] = clip_text(
                capsule["current_champion"]["changed_factor"], adaptive_limit
            )
            capsule["current_champion"]["structure_summary"] = clip_text(
                capsule["current_champion"]["structure_summary"], adaptive_limit
            )
            serialized = canonical_json(capsule)

        while len(serialized) > target:
            removable = next(
                (
                    capsule[key]
                    for key in (
                        "conditional_lessons",
                        "promising_rejected",
                        "hypothesis_frontier",
                        "recent_outcomes",
                    )
                    if isinstance(capsule[key], list) and len(capsule[key]) > 1
                ),
                None,
            )
            if removable is None:
                break
            removable.pop(0)
            serialized = canonical_json(capsule)

        if len(serialized) > maximum:
            raise StateError(
                f"bounded capsule exceeded configured maximum ({len(serialized)} > {maximum}); reduce schema limits"
            )
        capsule["adaptive_field_characters"] = adaptive_limit
        capsule["serialized_characters"] = len(serialized)
        capsule["content_sha256"] = content_hash(capsule)
        if len(canonical_json(capsule)) > maximum:
            raise StateError("capsule metadata exceeded configured maximum after adaptive compaction")
        atomic_json(self.capsule_path, capsule)
        return capsule

    def apply_batch_outcome(
        self,
        *,
        state: dict[str, Any],
        round_index: int,
        plan: dict[str, Any],
        batch: dict[str, Any],
        promoted_package: dict[str, Any] | None,
        development_candidate_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        promoted = promoted_package is not None
        change = plan["hypothesis"]["causal_change"]
        tested_mode = str(plan.get("proposal_mode", state["proposal_mode"]))
        emergent = plan["hypothesis"].get("emergent_capability", {})
        family_break = plan["hypothesis"].get("family_break", {})
        counter_family = (
            str(family_break.get("alternative_family", ""))
            if isinstance(family_break, dict)
            else ""
        )
        median_delta = batch.get("median_delta")
        full_batch_valid = (
            int(batch.get("completed_pair_count", 0)) == 3
            and int(batch.get("candidate_invalid_count", 0)) == 0
            and int(batch.get("incumbent_invalid_count", 0)) == 0
            and not bool(batch.get("inconclusive", False))
        )
        partial_assessment = batch.get("partial_development_assessment")
        partial_status = (
            str(partial_assessment.get("status", ""))
            if isinstance(partial_assessment, dict)
            else ""
        )
        bounded_decision_valid = (
            isinstance(partial_assessment, dict)
            and bool(partial_assessment.get("decisive"))
            and bool(partial_assessment.get("formal_promotion_already_impossible"))
            and int(batch.get("candidate_invalid_count", 0)) == 0
            and int(batch.get("incumbent_invalid_count", 0)) == 0
        )
        irreversible_rejection_valid = (
            bool(batch.get("irreversible_rejection_early_stop_applied"))
            and int(batch.get("completed_pair_count", 0)) >= 2
            and int(batch.get("candidate_invalid_count", 0)) == 0
            and int(batch.get("incumbent_invalid_count", 0)) == 0
        )
        # A clean 0-2 (or otherwise mathematically irreversible) ordinary
        # rejection is a valid structural trial even though pair 3 is skipped.
        # Not charging it to the search budget can trap the controller in the
        # local phase forever precisely because early adjudication worked.
        batch_valid = (
            full_batch_valid or bounded_decision_valid or irreversible_rejection_valid
        )
        development_threshold, _ = self._development_config()
        performance_ratio = (
            partial_assessment.get("relative_performance_lower")
            if partial_status
            in {"qualification_guaranteed", "development_improvement_guaranteed"}
            else batch.get("relative_performance_ratio")
        )
        development_qualified = (
            tested_mode == "counter_hypothesis"
            and not promoted
            and batch_valid
            and (
                partial_status == "qualification_guaranteed"
                or (
                    full_batch_valid
                    and isinstance(performance_ratio, (int, float))
                    and float(performance_ratio) >= development_threshold
                )
            )
            and development_candidate_snapshot is not None
        )
        active_development = state.get("development_candidate")
        development_update = None
        development_improved = False
        if development_qualified and development_candidate_snapshot is not None:
            development_update = {
                **development_candidate_snapshot,
                "lineage_id": f"development_{plan['structure_id']}",
                "started_round": round_index,
                "root_structure_id": plan["structure_id"],
            }
        elif (
            isinstance(active_development, dict)
            and batch_valid
            and development_candidate_snapshot is not None
            and isinstance(performance_ratio, (int, float))
        ):
            active_ratio = active_development.get("relative_performance_ratio")
            development_improved = not isinstance(active_ratio, (int, float)) or float(
                performance_ratio
            ) > float(active_ratio)
            if development_improved:
                development_update = {
                    **development_candidate_snapshot,
                    "lineage_id": active_development["lineage_id"],
                    "started_round": active_development["started_round"],
                    "root_structure_id": active_development["root_structure_id"],
                    "structural_family": (
                        development_candidate_snapshot.get("structural_family")
                        or active_development.get("structural_family", "")
                    ),
                }
        development_discarded = (
            isinstance(active_development, dict)
            and tested_mode == "emergent_exploration"
            and batch_valid
            and not promoted
            and int(state.get("emergent_failure_count", 0)) + 1
            >= self._search_cycle_config()[1]
        )
        if promoted:
            development_disposition = "promoted"
        elif development_qualified:
            development_disposition = "qualified"
        elif development_discarded:
            development_disposition = "discarded_after_budget"
        elif development_improved:
            development_disposition = "incumbent_improved"
        elif isinstance(active_development, dict):
            development_disposition = "incumbent_retained"
        else:
            development_disposition = "none"
        outcome = {
            "round": round_index,
            "structure_id": plan["structure_id"],
            "organization": plan["structure"]["organization"],
            "changed_factor": str(change["factor"]),
            "hypothesis": str(plan["hypothesis"]["expected_effect"]),
            "behavioral_novelty": str(plan["hypothesis"].get("behavioral_novelty", "")),
            "proposal_mode": tested_mode,
            "counter_family": counter_family,
            "emergent_capability_family": (
                str(emergent.get("capability_family", ""))
                if isinstance(emergent, dict)
                else ""
            ),
            "emergent_capability": (
                str(emergent.get("emergent_capability", ""))
                if isinstance(emergent, dict)
                else ""
            ),
            "evidence_scope": "matched_three_pair_batch",
            "completed_pair_count": batch["completed_pair_count"],
            "candidate_wins": batch["candidate_wins"],
            "candidate_losses": batch["candidate_losses"],
            "ties": batch["ties"],
            "candidate_median_elo": batch.get("candidate_median_elo"),
            "incumbent_median_elo": batch.get("incumbent_median_elo"),
            "candidate_median_score_rate": batch.get("candidate_median_score_rate"),
            "incumbent_median_score_rate": batch.get("incumbent_median_score_rate"),
            "relative_performance_ratio": performance_ratio,
            "relative_performance_bounds": partial_assessment,
            "development_performance_threshold": development_threshold,
            "development_qualified": development_qualified,
            "development_disposition": development_disposition,
            "valid_batch_consumed_search_budget": batch_valid,
            "full_batch_completed": full_batch_valid,
            "bounded_early_decision": bounded_decision_valid,
            "irreversible_rejection_early_decision": irreversible_rejection_valid,
            "anchor_elo": batch["anchor_elo"],
            "median_delta": median_delta,
            "representative_candidate_elo": batch.get("representative_candidate_elo"),
            "promoted": promoted,
            "failure_kind": (
                None
                if promoted
                else "matched_batch_did_not_satisfy_promotion"
                if batch_valid
                else "invalid_or_incomplete_batch_not_counted"
            ),
            "strengths": "; ".join(str(item) for item in plan["hypothesis"].get("strengths", [])),
            "weaknesses": "; ".join(str(item) for item in plan["hypothesis"].get("risks", [])),
        }
        limits = self.config["capsule_limits"]
        recent = [*state["recent_outcomes"], outcome][-int(limits["recent_outcomes"]):]
        frontier_entry = {
            "round": round_index,
            "factor": str(change["factor"]),
            "before": str(change["before"]),
            "after": str(change["after"]),
            "status": (
                "supported"
                if promoted
                else "development_qualified"
                if development_qualified
                else "development_lineage_discarded"
                if development_discarded
                else "development_incumbent_improved"
                if development_improved
                else "invalid_or_incomplete"
                if not batch_valid
                else "not_supported_in_tested_conditions"
            ),
            "evidence": (
                f"matched batch {batch['candidate_wins']}W/{batch['candidate_losses']}L/"
                f"{batch['ties']}T, median delta {median_delta}, candidate invalid count "
                f"{batch.get('candidate_invalid_count')}"
            ),
        }
        frontier = [*state["hypothesis_frontier"], frontier_entry][
            -int(limits["hypothesis_frontier"]):
        ]
        if promoted:
            lesson = (
                f"Under the round-{round_index} matched conditions, changing {change['factor']} from "
                f"{change['before']} to {change['after']} won {batch['candidate_wins']}-"
                f"{batch['candidate_losses']} with median Elo delta {median_delta} and promoted."
            )
        elif development_qualified:
            lesson = (
                f"Under the round-{round_index} matched conditions, the independent counter family "
                f"{counter_family!r} did not promote but retained {float(performance_ratio):.3f} of "
                f"the champion harness median score rate and entered bounded development."
            )
        elif development_discarded:
            lesson = (
                f"Under the round-{round_index} matched conditions, the active development lineage "
                "used its second valid emergent round without promotion and was removed from active "
                "development; counter-family discovery resumes."
            )
        else:
            lesson = (
                f"Under the round-{round_index} matched conditions, changing {change['factor']} from "
                f"{change['before']} to {change['after']} did not promote: "
                f"{batch['candidate_wins']}W/{batch['candidate_losses']}L/{batch['ties']}T, "
                f"candidate median {batch.get('candidate_median_elo')}, incumbent median "
                f"{batch.get('incumbent_median_elo')}. This is "
                "batch-level conditional evidence, not proof that every artifact from the structure fails."
            )
        search_control = self.advance_search_control(
            state,
            tested_mode=tested_mode,
            promoted=promoted,
            batch_valid=batch_valid,
            development_qualified=development_qualified,
            development_candidate_update=development_update,
            counter_family=counter_family,
        )
        lessons = [*state["conditional_lessons"], lesson][
            -int(limits["conditional_lessons"]):
        ]
        updated = {
            **state,
            "round_index": round_index,
            "champion": promoted_package or state["champion"],
            **search_control,
            "recent_outcomes": recent,
            "hypothesis_frontier": frontier,
            "conditional_lessons": lessons,
        }
        self.write_capsule(updated)
        self.save(updated)
        return updated
