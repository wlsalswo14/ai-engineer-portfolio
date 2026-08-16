from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from primus.backend import CodexBackend
from primus.config import DomainConfig, load_domain, load_system
from primus.domains.base import DomainAdapter, adapter_for
from primus.errors import ContractError, IntegrityError, LifecycleError, PrimusError
from primus.evaluation import TournamentEvaluator
from primus.evolution import (
    AdaptiveSearchPolicy,
    compile_experiment_lesson,
    load_experiment_lessons,
    rank_public_arms,
)
from primus.inner import InnerLoopExecutor
from primus.jsonutil import atomic_json, canonical_bytes, content_hash, read_json, write_immutable_json
from primus.models import LoopStructure, RoundStatus
from primus.outer import (
    ExternalArchitect,
    PublicFeedbackCompiler,
    StructuralProposal,
    generic_control,
    load_public_feedback,
)
from primus.store import PrimusStore


class PrimusOrchestrator:
    """Staged public screen -> independent hidden certification loop."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.system = load_system(self.root)
        self.store = PrimusStore(self.root)
        self.store.initialize()
        for domain in self.system.domains:
            config = load_domain(self.root, domain)
            self.store.reconcile_active_artifact_scope(domain, config.artifact_scope)
        self._backfill_semantic_hidden_consumption()

    def _backfill_semantic_hidden_consumption(self) -> None:
        """Make pre-v5 hidden uses count under their evaluator-meaningful identity."""
        for domain in self.system.domains:
            config = load_domain(self.root, domain)
            adapter = adapter_for(self.system, config)
            with self.store.connect() as connection:
                rounds = [dict(row) for row in connection.execute(
                    """SELECT run_id,round_index FROM rounds
                       WHERE domain=? AND hidden_receipt_sha256 IS NOT NULL""",
                    (domain,),
                )]
            for round_record in rounds:
                receipt_payload: dict[str, Any] = {}
                for receipt in self.store.receipts_for_run(str(round_record["run_id"])):
                    if receipt["kind"] == "hidden-certification":
                        receipt_payload = dict(read_json(self.root / receipt["object_path"]).get("payload", {}))
                        break
                semantic_digest = receipt_payload.get("semantic_selection_sha256")
                if semantic_digest is None:
                    start = (int(round_record["round_index"]) - 1) * config.evaluation.certification_replicates
                    replicates = list(range(start + 1, start + config.evaluation.certification_replicates + 1))
                    semantic_digest = adapter.semantic_selection_digest("certification", replicates)
                taskset_digest = str(
                    receipt_payload.get("taskset_selection_sha256") or semantic_digest
                )
                self.store.consume_hidden_selection(
                    semantic_selection_sha256=str(semantic_digest),
                    taskset_selection_sha256=taskset_digest,
                    domain=domain,
                    run_id=str(round_record["run_id"]),
                )

    def start(self, domain: str) -> dict[str, Any]:
        unfinished = self.store.latest_round(domain, unfinished_only=True)
        if unfinished:
            return self.resume(unfinished["run_id"])
        config = load_domain(self.root, domain)
        if not config.enabled:
            raise LifecycleError(f"domain is disabled: {domain}")
        latest = self.store.latest_round(domain)
        next_round = int(latest["round_index"]) + 1 if latest else 1
        start = (next_round - 1) * config.evaluation.certification_replicates
        replicates = list(range(start + 1, start + config.evaluation.certification_replicates + 1))
        semantic_digest = adapter_for(self.system, config).semantic_selection_digest(
            "certification", replicates
        )
        owner = self.store.hidden_selection_owner(
            domain=domain, semantic_selection_sha256=semantic_digest
        )
        if owner is not None:
            raise LifecycleError(
                f"hidden evidence is exhausted for {domain}; the same semantic selection was used by {owner}. "
                "Add a genuinely new certification case or suite before starting another round."
            )
        return self.resume(self.store.create_round(domain)["run_id"])

    def resume(self, run_id: str) -> dict[str, Any]:
        record = self.store.round(run_id)
        domain = record["domain"]
        config = load_domain(self.root, domain)
        if not config.enabled:
            raise LifecycleError(f"domain is disabled: {domain}")
        run_dir = self.root / "runs" / domain / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        incumbent_record = self.store.champion(domain, record["incumbent_id"])
        incumbent = self._structure(incumbent_record)
        adapter = adapter_for(self.system, config)
        incumbent_payload = self._artifact_payload(adapter, incumbent_record)
        public_feedback = load_public_feedback(self.root, domain)
        public_lessons = load_experiment_lessons(self.root, domain)
        architect_memory = [*public_feedback, *({"experiment_lesson": item} for item in public_lessons[-12:])]
        round_index = int(record["round_index"])
        metrics = dict(incumbent_record.get("source", {}).get("metrics", {}))
        evaluator = TournamentEvaluator(
            system=self.system,
            config=config,
            adapter=adapter,
            executor=InnerLoopExecutor(CodexBackend(self.system.executor_policy)),
        )

        if RoundStatus(record["status"]) == RoundStatus.CREATED:
            proposal = self._plan_proposal(
                domain=domain,
                run_id=run_id,
                round_index=round_index,
                run_dir=run_dir,
                config=config,
                incumbent=incumbent,
                incumbent_payload=incumbent_payload,
                incumbent_metrics=metrics,
                public_feedback=public_feedback,
                architect_memory=architect_memory,
                public_lessons=public_lessons,
                evaluator=evaluator,
            )
            proposal_receipt = self._append_receipt_once(
                domain=domain, run_id=run_id, kind="structural-proposal", payload=proposal.to_dict()
            )
            self.store.transition(
                run_id,
                RoundStatus.PLANNED,
                proposal_sha256=proposal.digest,
                candidate_structure_sha256=content_hash(proposal.candidate.to_dict()),
            )
            atomic_json(run_dir / "proposal-receipt-pointer.json", {"receipt_sha256": proposal_receipt})

        proposal = self._load_proposal(run_dir, config, incumbent)
        structures = {"incumbent": incumbent, "candidate": proposal.candidate}
        hypothesis = {
            "claim": proposal.hypothesis,
            "changed_factor": proposal.changed_factor,
            "exploration_operation": proposal.exploration_operation,
            "prediction": proposal.predicted_observation,
            "falsifier": proposal.falsifier,
            "protected_behavior": list(proposal.protected_behavior),
        }
        screen_dir = run_dir / "screening"
        certification_dir = run_dir / "certification"

        # Gate 1: cheap matched incumbent/candidate public screening only.
        status = RoundStatus(self.store.round(run_id)["status"])
        if status in {RoundStatus.PLANNED, RoundStatus.SCREEN_GENERATED}:
            _, receipt = evaluator.run_stage(
                run_id=run_id,
                round_index=round_index,
                split="development",
                stage="screening",
                replicates=config.evaluation.screening_replicates,
                structures={key: structures[key] for key in ("incumbent", "candidate")},
                incumbent_payload=incumbent_payload,
                incumbent_metrics=metrics,
                public_audit=public_feedback,
                hypothesis=hypothesis,
                working_directory=screen_dir,
                effective_replicates=self._development_replicates(
                    config=config, round_index=round_index, stage="screening"
                ),
                on_presealed=lambda _: self.store.transition(run_id, RoundStatus.SCREEN_GENERATED),
            )
            public_digest = self._append_receipt_once(
                domain=domain, run_id=run_id, kind="public-screening", payload=receipt
            )
            self.store.transition(run_id, RoundStatus.SCREEN_EVALUATED, public_receipt_sha256=public_digest)

        status = RoundStatus(self.store.round(run_id)["status"])
        if status == RoundStatus.SCREEN_EVALUATED:
            receipt = read_json(screen_dir / "evaluation-receipt.json")
            screen_results = evaluator.load_results(receipt)
            _, summary = evaluator.decide(
                results=screen_results,
                seed=f"{run_id}:screening",
                certification=False,
            )
            summary["stage"] = "screening"
            atomic_json(screen_dir / "decision.json", summary)
            public_digest = str(self.store.round(run_id)["public_receipt_sha256"])
            feedback = PublicFeedbackCompiler.compile(
                domain=domain, public_receipt=receipt, source_receipt_sha256=public_digest
            )
            write_immutable_json(self.root / "resources" / "public_audits" / domain / f"{run_id}.json", feedback)
            self.store.add_public_feedback(domain=domain, source_receipt_sha256=public_digest, payload=feedback)
            lesson = compile_experiment_lesson(
                domain=domain,
                run_id=run_id,
                proposal=proposal.to_dict(),
                public_receipt=receipt,
                public_decision=summary,
            )
            write_immutable_json(
                self.root / "resources" / "public_lessons" / domain / f"{run_id}.json",
                lesson,
            )
            self.store.add_experiment_lesson(domain=domain, run_id=run_id, payload=lesson)
            if not summary["passed"]:
                decision_digest = self._append_receipt_once(
                    domain=domain, run_id=run_id, kind="screening-falsification", payload=summary
                )
                return self.store.transition(run_id, RoundStatus.FALSIFIED, decision_sha256=decision_digest)
            if config.artifact_scope == "domain_lineage":
                self._seal_public_deployment_artifact(run_dir=run_dir, results=screen_results)
            self.store.transition(run_id, RoundStatus.SCREEN_PASSED)

        # A public winner proceeds directly to a fresh hidden incumbent/candidate match.
        status = RoundStatus(self.store.round(run_id)["status"])
        if status == RoundStatus.SCREEN_PASSED:
            if config.artifact_scope == "domain_lineage":
                screen_results = evaluator.load_results(read_json(screen_dir / "evaluation-receipt.json"))
                self._seal_public_deployment_artifact(run_dir=run_dir, results=screen_results)
            self.store.transition(run_id, RoundStatus.PROVISIONAL)

        # Gate 2: fresh incumbent/candidate generations on a one-use hidden selection.
        status = RoundStatus(self.store.round(run_id)["status"])
        if status in {RoundStatus.PROVISIONAL, RoundStatus.CERT_GENERATED}:
            def seal_certification(preseal: dict[str, Any]) -> None:
                self.store.consume_hidden_selection(
                    semantic_selection_sha256=str(preseal["semantic_selection_sha256"]),
                    taskset_selection_sha256=str(preseal["taskset_selection_sha256"]),
                    domain=domain,
                    run_id=run_id,
                )
                self.store.transition(run_id, RoundStatus.CERT_GENERATED)

            _, receipt = evaluator.run_stage(
                run_id=run_id,
                round_index=round_index,
                split="certification",
                stage="certification",
                replicates=config.evaluation.certification_replicates,
                structures={key: structures[key] for key in ("incumbent", "candidate")},
                incumbent_payload=incumbent_payload,
                incumbent_metrics=metrics,
                public_audit=[],
                hypothesis=hypothesis,
                working_directory=certification_dir,
                on_presealed=seal_certification,
            )
            hidden_digest = self._append_receipt_once(
                domain=domain, run_id=run_id, kind="hidden-certification", payload=receipt
            )
            self.store.transition(run_id, RoundStatus.HIDDEN_EVALUATED, hidden_receipt_sha256=hidden_digest)

        status = RoundStatus(self.store.round(run_id)["status"])
        if status == RoundStatus.HIDDEN_EVALUATED:
            cert_results = evaluator.load_results(read_json(certification_dir / "evaluation-receipt.json"))
            _, summary = evaluator.decide(
                results=cert_results,
                seed=f"{run_id}:certification",
                certification=True,
            )
            summary.update(
                stage="independent-hidden-certification",
                public_screening_receipt_sha256=self.store.round(run_id)["public_receipt_sha256"],
                hidden_evidence_not_returned_to_architect=True,
            )
            atomic_json(certification_dir / "decision.json", summary)
            decision_digest = self._append_receipt_once(
                domain=domain, run_id=run_id, kind="certification-decision", payload=summary
            )
            if not summary["passed"]:
                return self.store.transition(run_id, RoundStatus.FALSIFIED, decision_sha256=decision_digest)
            self.store.transition(run_id, RoundStatus.CERTIFIED, decision_sha256=decision_digest)
            artifact = None
            if config.artifact_scope == "domain_lineage":
                artifact = canonical_bytes(read_json(screen_dir / "deployment-artifact.json"))
            champion = self.store.promote(
                run_id=run_id,
                new_champion_id=f"{domain}-{proposal.candidate.structure_id}-{run_id}",
                structure=proposal.candidate.to_dict(),
                artifact=artifact,
                certification_receipt_sha256=str(self.store.round(run_id)["hidden_receipt_sha256"]),
                decision_sha256=decision_digest,
                artifact_scope=config.artifact_scope,
                artifact_lineage_id=str(incumbent_record.get("artifact_lineage_id") or "default"),
                deployment_source=(
                    "public-screening-selection" if config.artifact_scope == "domain_lineage"
                    else "task-local-harness-only"
                ),
            )
            self._periodic_control(
                evaluator=evaluator,
                config=config,
                run_id=run_id,
                round_index=round_index,
                proposal=proposal,
                incumbent_payload=incumbent_payload,
                metrics=metrics,
                public_feedback=public_feedback,
                hypothesis=hypothesis,
                run_dir=run_dir,
                domain=domain,
            )
            return champion
        return self.store.round(run_id)

    def _plan_proposal(
        self,
        *,
        domain: str,
        run_id: str,
        round_index: int,
        run_dir: Path,
        config: DomainConfig,
        incumbent: LoopStructure,
        incumbent_payload: dict[str, Any],
        incumbent_metrics: dict[str, Any],
        public_feedback: list[dict[str, Any]],
        architect_memory: list[dict[str, Any]],
        public_lessons: list[dict[str, Any]],
        evaluator: TournamentEvaluator,
    ) -> StructuralProposal:
        policy = AdaptiveSearchPolicy(
            cycle=config.exploration.mode_cycle,
            novelty_interval_rounds=config.exploration.novelty_interval_rounds,
            adaptive=config.exploration.adaptive,
        )
        primary = policy.choose(round_index=round_index, lessons=public_lessons)
        modes = policy.portfolio_modes(primary=primary, size=config.exploration.portfolio_size)
        architect = ExternalArchitect(
            CodexBackend(self.system.architect_policy, allow_web_search=True)
        )
        proposals: list[StructuralProposal] = []
        for index, mode in enumerate(modes, 1):
            directory = (
                run_dir / "proposal"
                if len(modes) == 1
                else run_dir / "portfolio" / f"candidate-{index:02d}"
            )
            proposals.append(
                architect.propose(
                    domain=domain,
                    incumbent=incumbent,
                    public_task=config.public_task.read_text(encoding="utf-8"),
                    public_feedback=architect_memory,
                    legacy_summaries=self._legacy_summaries(domain),
                    max_calls=config.budget.max_calls,
                    exploration_mode=mode,
                    minimum_research_sources=config.exploration.minimum_research_sources,
                    maximum_research_sources=config.exploration.maximum_research_sources,
                    working_directory=directory,
                )
            )
        if len(proposals) == 1:
            return proposals[0]

        arm_names = [f"candidate_{index:02d}" for index in range(1, len(proposals) + 1)]
        hypotheses = {
            arm: self._proposal_hypothesis(proposal)
            for arm, proposal in zip(arm_names, proposals, strict=True)
        }
        results, receipt = evaluator.run_stage(
            run_id=run_id,
            round_index=round_index,
            split="development",
            stage="portfolio-probe",
            replicates=config.exploration.probe_replicates,
            structures={
                arm: proposal.candidate
                for arm, proposal in zip(arm_names, proposals, strict=True)
            },
            incumbent_payload=incumbent_payload,
            incumbent_metrics=incumbent_metrics,
            public_audit=public_feedback,
            hypothesis={},
            hypotheses=hypotheses,
            effective_replicates=self._development_replicates(
                config=config, round_index=round_index, stage="portfolio-probe"
            ),
            working_directory=run_dir / "portfolio" / "probe",
        )
        ranking = rank_public_arms(results, arm_names)
        selected_arm = ranking[0]
        selected = proposals[arm_names.index(selected_arm)]
        probe_receipt = self._append_receipt_once(
            domain=domain,
            run_id=run_id,
            kind="public-portfolio-probe",
            payload=receipt,
        )
        manifest = {
            "schema_version": 1,
            "public_only": True,
            "candidate_proposal_sha256": {
                arm: proposal.digest
                for arm, proposal in zip(arm_names, proposals, strict=True)
            },
            "ranking": ranking,
            "selected_arm": selected_arm,
            "selected_proposal_sha256": selected.digest,
            "probe_receipt_sha256": probe_receipt,
            "selection_rule": "validity_then_public_quality_then_lower_generation_cost",
            "hidden_evidence_used": False,
        }
        write_immutable_json(run_dir / "portfolio" / "selection.json", manifest)
        write_immutable_json(run_dir / "proposal" / "proposal.json", selected.to_dict())
        return selected

    @staticmethod
    def _proposal_hypothesis(proposal: StructuralProposal) -> dict[str, Any]:
        return {
            "claim": proposal.hypothesis,
            "changed_factor": proposal.changed_factor,
            "exploration_operation": proposal.exploration_operation,
            "prediction": proposal.predicted_observation,
            "falsifier": proposal.falsifier,
            "protected_behavior": list(proposal.protected_behavior),
        }

    @staticmethod
    def _development_replicates(
        *, config: DomainConfig, round_index: int, stage: str
    ) -> list[int]:
        probe = config.exploration.probe_replicates if config.exploration.portfolio_size > 1 else 0
        screening = config.evaluation.screening_replicates
        start = (round_index - 1) * (probe + screening)
        if stage == "portfolio-probe":
            return list(range(start + 1, start + probe + 1))
        if stage == "screening":
            return list(range(start + probe + 1, start + probe + screening + 1))
        raise ContractError(f"unknown development stage: {stage}")

    @staticmethod
    def _seal_public_deployment_artifact(
        *, run_dir: Path, results: dict[str, list[Any]]
    ) -> None:
        valid = [
            item
            for item in results.get("candidate", [])
            if item.valid and item.score is not None
        ]
        if not valid:
            raise LifecycleError("publicly passed candidate has no deployable artifact")
        chosen = sorted(
            valid,
            key=lambda item: (
                -float(item.score),
                item.usage.effective_tokens,
                item.replicate,
                item.artifact_sha256,
            ),
        )[0]
        source = (
            run_dir
            / "screening"
            / "generation"
            / f"replicate-{chosen.replicate:02d}"
            / "candidate"
            / "artifact.json"
        )
        artifact = read_json(source)
        write_immutable_json(run_dir / "screening" / "deployment-artifact.json", artifact)
        write_immutable_json(
            run_dir / "screening" / "deployment-selection.json",
            {
                "schema_version": 1,
                "source_stage": "public-screening",
                "source_replicate": chosen.replicate,
                "artifact_sha256": chosen.artifact_sha256,
                "selection_rule": "highest_public_quality_then_lower_generation_cost",
                "hidden_evidence_used": False,
            },
        )

    def _periodic_control(
        self,
        *,
        evaluator: TournamentEvaluator,
        config: DomainConfig,
        run_id: str,
        round_index: int,
        proposal: StructuralProposal,
        incumbent_payload: dict[str, Any],
        metrics: dict[str, Any],
        public_feedback: list[dict[str, Any]],
        hypothesis: dict[str, Any],
        run_dir: Path,
        domain: str,
    ) -> None:
        interval = config.evaluation.control_interval_rounds
        if interval <= 0 or round_index % interval != 0:
            return
        control = generic_control(len(proposal.candidate.calls), proposal.candidate.calls[-1].output_type)
        try:
            _, receipt = evaluator.run_stage(
                run_id=run_id,
                round_index=round_index,
                split="development",
                stage="periodic-generic-control",
                replicates=config.evaluation.control_replicates,
                structures={"control": control},
                incumbent_payload=incumbent_payload,
                incumbent_metrics=metrics,
                public_audit=public_feedback,
                hypothesis=hypothesis,
                working_directory=run_dir / "periodic-control",
            )
            self._append_receipt_once(domain=domain, run_id=run_id, kind="periodic-generic-control", payload=receipt)
        except (PrimusError, OSError, ValueError) as exc:
            self._append_receipt_once(
                domain=domain,
                run_id=run_id,
                kind="periodic-control-unresolved",
                payload={"error": type(exc).__name__, "message": str(exc), "promotion_unchanged": True},
            )

    def _append_receipt_once(self, *, domain: str, run_id: str, kind: str, payload: dict[str, Any]) -> str:
        expected = content_hash(payload)
        for row in reversed(self.store.receipts_for_run(run_id)):
            if row["kind"] != kind:
                continue
            envelope = read_json(self.root / row["object_path"])
            if content_hash(envelope.get("payload")) != expected:
                raise IntegrityError(f"receipt kind already exists with different payload: {run_id}/{kind}")
            return str(row["receipt_sha256"])
        return self.store.append_receipt(domain=domain, run_id=run_id, kind=kind, payload=payload)

    @staticmethod
    def _load_proposal(run_dir: Path, config: DomainConfig, incumbent: LoopStructure) -> StructuralProposal:
        value = read_json(run_dir / "proposal" / "proposal.json")
        return ExternalArchitect._parse(
            {
                "observed_bottleneck": value["observed_bottleneck"],
                "hypothesis": value["hypothesis"],
                "changed_factor": value["changed_factor"],
                "predicted_observation": value["predicted_observation"],
                "falsifier": value["falsifier"],
                "protected_behavior": value["protected_behavior"],
                "exploration_operation": value["exploration_operation"],
                "research_sources": value["research_sources"],
                "candidate_structure": value["candidate_structure"],
            },
            max_calls=config.budget.max_calls,
            incumbent=incumbent,
            exploration_mode="open",
            minimum_research_sources=config.exploration.minimum_research_sources,
            maximum_research_sources=config.exploration.maximum_research_sources,
        )

    def _structure(self, champion: dict[str, Any]) -> LoopStructure:
        raw = self.store.object_bytes(champion["structure_object"], champion["structure_sha256"])
        structure = LoopStructure.from_dict(json.loads(raw))
        structure.validate(max_calls=load_domain(self.root, champion["domain"]).budget.max_calls)
        return structure

    def _artifact_payload(self, adapter: DomainAdapter, champion: dict[str, Any]) -> dict[str, Any]:
        raw = self.store.object_bytes(champion["artifact_object"], champion["artifact_sha256"])
        return adapter.decode_reference_artifact(raw)

    def _legacy_summaries(self, domain: str) -> list[dict[str, Any]]:
        directory = self.root / "registry" / "legacy" / domain
        result: list[dict[str, Any]] = []
        for path in sorted(directory.rglob("*.json")) if directory.is_dir() else []:
            value = read_json(path)
            if isinstance(value, dict):
                result.append({
                    "name": value.get("name"),
                    "changed_factor": value.get("changed_factor"),
                    "calls": len(value.get("calls", [])),
                    "structure_sha256": content_hash(value),
                })
        return result
