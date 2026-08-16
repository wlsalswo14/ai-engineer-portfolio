from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from primus.backend import CodexBackend
from primus.errors import ContractError
from primus.jsonutil import atomic_json, bytes_hash, content_hash, parse_json_object, read_json
from primus.models import LoopCall, LoopStructure


def executable_structure_hash(value: LoopStructure) -> str:
    return content_hash({
        "organization": value.organization,
        "calls": [
            {
                "id": call.id,
                "role": call.role,
                "objective": call.objective,
                "inputs": list(call.inputs),
                "output_type": call.output_type,
            }
            for call in value.calls
        ],
        "final_call_id": value.final_call_id,
    })


@dataclass(frozen=True)
class StructuralProposal:
    observed_bottleneck: str
    hypothesis: str
    changed_factor: str
    predicted_observation: str
    falsifier: str
    protected_behavior: tuple[str, ...]
    exploration_operation: str
    research_sources: tuple[dict[str, str], ...]
    candidate: LoopStructure

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_bottleneck": self.observed_bottleneck,
            "hypothesis": self.hypothesis,
            "changed_factor": self.changed_factor,
            "predicted_observation": self.predicted_observation,
            "falsifier": self.falsifier,
            "protected_behavior": list(self.protected_behavior),
            "exploration_operation": self.exploration_operation,
            "research_sources": list(self.research_sources),
            "candidate_structure": self.candidate.to_dict(),
        }

    @property
    def digest(self) -> str:
        return content_hash(self.to_dict())


class ExternalArchitect:
    def __init__(self, backend: CodexBackend):
        self.backend = backend

    def propose(
        self,
        *,
        domain: str,
        incumbent: LoopStructure,
        public_task: str,
        public_feedback: list[dict[str, Any]],
        legacy_summaries: list[dict[str, Any]],
        max_calls: int,
        exploration_mode: str,
        minimum_research_sources: int,
        maximum_research_sources: int,
        working_directory: Path,
    ) -> StructuralProposal:
        schema = {
            "observed_bottleneck": "string",
            "hypothesis": "string",
            "changed_factor": "one falsifiable causal intervention, which may be a local edit or a new topology",
            "exploration_operation": "add|delete|replace|recombine|de_novo|research_transfer",
            "research_sources": [
                {
                    "title": "string",
                    "url": "https URL",
                    "kind": "paper|github|documentation|other",
                    "structural_insight": "abstract harness idea used; never copied solution code",
                    "license_or_terms": "license/terms note or not_applicable_idea_only",
                }
            ],
            "predicted_observation": "string",
            "falsifier": "string",
            "protected_behavior": ["string"],
            "candidate_structure": self._structure_schema(),
        }
        prompt = f"""You are the score-blind Primus structural architect for domain {domain}.
Propose one coherent candidate experiment. You are not restricted to changing an incumbent component: you may add or delete calls, replace one or several connected mechanisms, recombine abstract ideas from legacy structures, create a structurally distant topology from scratch, or transfer an abstract harness pattern found in papers/GitHub.
You may see public failures but no hidden tasks, traces, answers, or numeric certification scores. Never search for, inspect, or copy benchmark solutions, chess engines, policies, answer corpora, evaluator internals, or domain artifacts. External research may inform harness organization only; do not copy source code.
The candidate must be sequential, emit one final artifact, differ executably from the incumbent, and never use replicated candidates, best-of-N, benchmark hardcoding, or evaluator changes. It may have a different call count from the incumbent, within MAX CALLS. Primus will judge it directly against the incumbent; do not design or return an ablation. Copy the top-level changed_factor string exactly into candidate_structure.changed_factor. For each call after the first, reference earlier calls by their actual call IDs; never emit the literal placeholder `prior_call_id`.
Requested exploration mode for this round: {exploration_mode}. If it is not `open`, exploration_operation must match it. `add` and `delete` may operate on a call, edge, responsibility, evidence channel, state, or control mechanism; they do not require changing call count. A research_transfer round must perform live web research and cite {minimum_research_sources}..{maximum_research_sources} distinct sources, including at least one paper or GitHub repository. Other modes may cite up to {maximum_research_sources} sources or use none.
Return exactly one JSON object matching this schema:
{json.dumps(schema, ensure_ascii=False)}

MAX CALLS: {max_calls}
PUBLIC TASK CONTRACT:
{public_task}

INCUMBENT:
{json.dumps(incumbent.to_dict(), ensure_ascii=False)}

PUBLIC-ONLY AUDIT EXAMPLES:
{json.dumps(public_feedback, ensure_ascii=False)}

LEGACY STRUCTURE SUMMARIES (ideas only, never active):
{json.dumps(legacy_summaries[-24:], ensure_ascii=False)}
"""
        call_dir = working_directory / "architect-call"
        persisted_response = call_dir / "response.txt"
        persisted_receipt = call_dir / "receipt.json"
        response_web_search_calls: int
        if persisted_response.is_file() and persisted_receipt.is_file():
            response_text = persisted_response.read_text(encoding="utf-8")
            receipt = read_json(persisted_receipt)
            if receipt.get("response_sha256") != bytes_hash(response_text.encode("utf-8")):
                raise ContractError("persisted architect response digest mismatch")
            expected_policy = (
                self.backend.policy.model,
                self.backend.policy.reasoning_effort,
                self.backend.policy.service_tier,
            )
            actual_policy = (
                str(receipt.get("model")),
                str(receipt.get("reasoning_effort")),
                str(receipt.get("service_tier")),
            )
            if actual_policy != expected_policy:
                raise ContractError("persisted architect response policy mismatch")
            response_web_search_calls = int(receipt.get("web_search_calls", 0))
        else:
            response = self.backend.complete(
                role=f"score-blind {domain} structural architect",
                prompt=prompt,
                working_directory=call_dir / "workspace",
                receipt_dir=call_dir,
            )
            response_text = response.text
            response_web_search_calls = response.web_search_calls
        raw = parse_json_object(response_text)
        proposal = self._parse(
            raw,
            max_calls=max_calls,
            incumbent=incumbent,
            exploration_mode=exploration_mode,
            minimum_research_sources=minimum_research_sources,
            maximum_research_sources=maximum_research_sources,
        )
        if proposal.exploration_operation == "research_transfer" and response_web_search_calls < 1:
            raise ContractError("research_transfer completed without an evidenced live web-search call")
        atomic_json(working_directory / "proposal.json", proposal.to_dict())
        return proposal

    @staticmethod
    def _structure_schema() -> dict[str, Any]:
        return {
            "name": "string",
            "organization": "sequential",
            "information_flow": "string",
            "changed_factor": "string",
            "calls": [
                {
                    "id": "string",
                    "role": "string",
                    "objective": "string",
                    "inputs": ["task|champion_artifact|champion_metrics|public_audit|hypothesis|loop_structure|prior_call_id"],
                    "output_type": "analysis|artifact|engine|policy|patch|answer|tool_trace",
                }
            ],
            "final_call_id": "string",
        }

    @staticmethod
    def _parse(
        raw: dict[str, Any],
        *,
        max_calls: int,
        incumbent: LoopStructure,
        exploration_mode: str = "open",
        minimum_research_sources: int = 2,
        maximum_research_sources: int = 5,
    ) -> StructuralProposal:
        required = {
            "observed_bottleneck",
            "hypothesis",
            "changed_factor",
            "predicted_observation",
            "falsifier",
            "protected_behavior",
            "exploration_operation",
            "research_sources",
            "candidate_structure",
        }
        if set(raw) != required:
            raise ContractError(f"architect keys differ: {sorted(set(raw) ^ required)}")
        operation = str(raw["exploration_operation"]).strip()
        allowed_operations = {"add", "delete", "replace", "recombine", "de_novo", "research_transfer"}
        if operation not in allowed_operations:
            raise ContractError(f"invalid exploration operation: {operation}")
        if exploration_mode != "open" and operation != exploration_mode:
            raise ContractError(f"proposal operation {operation} does not match scheduled mode {exploration_mode}")
        sources_raw = raw["research_sources"]
        if not isinstance(sources_raw, list):
            raise ContractError("research_sources must be a list")
        source_keys = {"title", "url", "kind", "structural_insight", "license_or_terms"}
        sources: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for item in sources_raw:
            if not isinstance(item, dict) or set(item) != source_keys:
                raise ContractError("research source keys differ from the sealed schema")
            source = {key: str(item[key]).strip() for key in source_keys}
            if not all(source.values()) or not source["url"].startswith("https://"):
                raise ContractError("research sources require non-empty fields and an https URL")
            if source["url"] in seen_urls:
                raise ContractError("research source URLs must be distinct")
            seen_urls.add(source["url"])
            sources.append(source)
        if len(sources) > maximum_research_sources:
            raise ContractError("too many research sources")
        if operation == "research_transfer":
            if len(sources) < minimum_research_sources:
                raise ContractError("research transfer lacks the required source count")
            if not any(source["kind"] in {"paper", "github"} for source in sources):
                raise ContractError("research transfer requires at least one paper or GitHub source")

        changed_factor = str(raw["changed_factor"]).strip()
        candidate_raw = dict(raw["candidate_structure"])
        normalized_calls: list[dict[str, Any]] = []
        previous_call_id: str | None = None
        for raw_call in candidate_raw.get("calls", []):
            call = dict(raw_call)
            inputs = []
            for item in call.get("inputs", []):
                if item == "prior_call_id":
                    if previous_call_id is None:
                        raise ContractError("first call cannot use prior_call_id")
                    inputs.append(previous_call_id)
                else:
                    inputs.append(item)
            call["inputs"] = inputs
            normalized_calls.append(call)
            previous_call_id = str(call.get("id", ""))
        structure_factor = str(candidate_raw.get("changed_factor", "")).strip()
        candidate_raw["calls"] = normalized_calls
        candidate_raw["changed_factor"] = changed_factor
        provenance = {
            "exploration_operation": operation,
            "research_source_sha256": [content_hash(source) for source in sources],
            "external_ideas_only": True,
        }
        if structure_factor and structure_factor != changed_factor:
            provenance["architect_structure_changed_factor"] = structure_factor
        candidate = replace(
            LoopStructure.from_dict(candidate_raw),
            provenance={**dict(candidate_raw.get("provenance", {})), **provenance},
        )
        candidate.validate(max_calls=max_calls)
        if executable_structure_hash(candidate) == executable_structure_hash(incumbent):
            raise ContractError("candidate must differ executably from incumbent")
        if not changed_factor:
            raise ContractError("proposal changed_factor cannot be empty")
        return StructuralProposal(
            observed_bottleneck=str(raw["observed_bottleneck"]),
            hypothesis=str(raw["hypothesis"]),
            changed_factor=changed_factor,
            predicted_observation=str(raw["predicted_observation"]),
            falsifier=str(raw["falsifier"]),
            protected_behavior=tuple(str(item) for item in raw["protected_behavior"]),
            exploration_operation=operation,
            research_sources=tuple(sources),
            candidate=candidate,
        )


class PublicFeedbackCompiler:
    """R81-style public failures into pre-actor audit examples; hidden receipts are rejected."""

    @staticmethod
    def compile(*, domain: str, public_receipt: dict[str, Any], source_receipt_sha256: str | None = None) -> dict[str, Any]:
        if public_receipt.get("split") != "development" or public_receipt.get("hidden", False):
            raise ContractError("only public development evidence can become feedback")
        failures: list[dict[str, str]] = []
        seen_failures: set[tuple[str, str, str, str]] = set()

        def add_failure(value: dict[str, str]) -> None:
            identity = (
                value["failure_class"],
                value["bad_behavior"],
                value["required_behavior"],
                value["check"],
            )
            if identity not in seen_failures:
                seen_failures.add(identity)
                failures.append(value)

        for item in public_receipt.get("results", []):
            if item.get("arm") not in {None, "candidate"}:
                continue
            failure_class = item.get("failure_class")
            if not failure_class:
                continue
            add_failure({
                "failure_class": str(failure_class),
                "bad_behavior": str(item.get("public_bad_behavior", failure_class)),
                "required_behavior": str(item.get("public_required_behavior", "satisfy the public task contract")),
                "check": str(item.get("public_check", "rerun the public validator")),
            })
        by_arm_replicate = {
            (str(item.get("arm")), int(item.get("replicate", 0))): item
            for item in public_receipt.get("results", [])
        }
        replicates = sorted({replicate for arm, replicate in by_arm_replicate if arm == "candidate"})
        for replicate in replicates:
            incumbent = by_arm_replicate.get(("incumbent", replicate))
            candidate = by_arm_replicate.get(("candidate", replicate))
            if not incumbent or not candidate or not incumbent.get("valid") or not candidate.get("valid"):
                continue
            if incumbent.get("score") is None or candidate.get("score") is None:
                continue
            if float(candidate["score"]) <= float(incumbent["score"]):
                add_failure({
                    "failure_class": "public_relative_regression",
                    "bad_behavior": "the candidate failed to outperform the matched incumbent on a public case",
                    "required_behavior": "preserve incumbent strengths while producing a repeatable matched improvement",
                    "check": "rerun the public matched incumbent/candidate comparison",
                })
        value = {
            "schema_version": 1,
            "domain": domain,
            "public_only": True,
            "source_receipt_sha256": source_receipt_sha256 or content_hash(public_receipt),
            "audit_examples": failures[:12],
        }
        value["feedback_sha256"] = content_hash(value)
        return value

def generic_control(call_count: int, final_output_type: str) -> LoopStructure:
    calls: list[LoopCall] = []
    previous: str | None = None
    for index in range(1, call_count + 1):
        final = index == call_count
        call_id = "generic_final_producer" if final else f"generic_analysis_{index:02d}"
        inputs = ["task", "champion_artifact", "public_audit", "hypothesis", "loop_structure"]
        if previous:
            inputs.append(previous)
        calls.append(
            LoopCall(
                id=call_id,
                role="generic domain-bounded producer" if final else "generic domain-bounded analyst",
                objective=(
                    "Produce exactly one complete artifact satisfying the public contract using the preceding analysis."
                    if final
                    else "Analyze the task once, preserve the incumbent's valid behavior, and pass one concise actionable record forward."
                ),
                inputs=tuple(inputs),
                output_type=final_output_type if final else "analysis",
            )
        )
        previous = call_id
    return LoopStructure(
        name=f"Equal-Budget Generic {call_count}-Call Control",
        organization="sequential",
        information_flow="Generic analysis records followed by one final artifact producer.",
        calls=tuple(calls),
        final_call_id=calls[-1].id,
        changed_factor="equal-budget generic control",
        provenance={"control": True},
    )


def load_public_feedback(root: Path, domain: str) -> list[dict[str, Any]]:
    directory = root / "resources" / "public_audits" / domain
    if not directory.is_dir():
        return []
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        value = read_json(path)
        if value.get("public_only") is not True:
            raise ContractError(f"non-public feedback in public audit directory: {path}")
        for example in value.get("audit_examples", []):
            digest = content_hash(example)
            if digest not in seen:
                seen.add(digest)
                values.append(example)
    return values[-24:]
