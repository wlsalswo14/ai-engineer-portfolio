from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from primus.config import load_system
from primus.errors import LifecycleError
from primus.jsonutil import atomic_json, atomic_write, bytes_hash, file_hash, read_json, write_immutable
from primus.models import LoopCall, LoopStructure
from primus.store import PrimusStore


CHESS_PROMOTIONS = ("p0000", "p0001", "p0005", "p0007", "p0011", "p0018", "p0019", "p0024", "p0025", "p0027", "p0028")
CACHE_PROMOTIONS = ("r0", "r24", "r36", "r54", "r63", "r73", "r83")


def _normalize(source: dict[str, Any], *, origin: str) -> dict[str, Any]:
    body = dict(source.get("structure", source))
    mapping = {
        "champion_engine": "champion_artifact",
        "anchor_policy": "champion_artifact",
        "anchor_contract": "champion_metrics",
        "task_constraints": "champion_metrics",
        "state_capsule": "champion_metrics",
        "candidate_hypothesis": "hypothesis",
    }
    calls: list[dict[str, Any]] = []
    source_calls = body.get("calls") or [call for stage in body.get("stages", []) for call in stage.get("calls", [])]
    for item in source_calls:
        inputs: list[str] = []
        for raw in item.get("inputs", []):
            value = mapping.get(str(raw), str(raw))
            if value not in inputs:
                inputs.append(value)
        calls.append({
            "id": str(item["id"]),
            "role": str(item["role"]),
            "objective": str(item["objective"]),
            "inputs": inputs,
            "output_type": str(item["output_type"]),
        })
    changed = source.get("hypothesis", {}).get("causal_change", {}).get("factor", "legacy import")
    value = {
        "name": str(body["name"]),
        "organization": str(body.get("organization", "sequential")),
        "information_flow": str(body.get("information_flow", "")),
        "calls": calls,
        "final_call_id": str(body["final_call_id"]),
        "changed_factor": str(changed),
        "provenance": {"origin": origin, "source_structure_id": source.get("structure_id")},
    }
    return LoopStructure.from_dict(value).to_dict()


def _legacy_copy(source: Path, destination: Path) -> dict[str, Any]:
    data = source.read_bytes()
    write_immutable(destination / "structure.json", data)
    manifest = {
        "schema_version": 1,
        "legacy_only": True,
        "never_active": True,
        "source_path": str(source.resolve()),
        "source_sha256": bytes_hash(data),
    }
    atomic_json(destination / "manifest.json", manifest)
    return manifest


def migrate(root: Path, *, ouroboros: Path, archive: Path) -> dict[str, Any]:
    root, ouroboros, archive = root.resolve(), ouroboros.resolve(), archive.resolve()
    store = PrimusStore(root)
    store.initialize()
    _write_tasksets(root, ouroboros)
    chess_root = ouroboros / "experiments" / "chess-tier5-clean" / "workspace" / "champions"
    cache_root = ouroboros / "experiments" / "cache-transfer-league" / "workspace"
    migrated: dict[str, list[str]] = {"chess": [], "cache": [], "r81": [], "ecr": []}

    for champion in CHESS_PROMOTIONS:
        source = chess_root / champion / "loop-structure.json"
        if source.is_file():
            _legacy_copy(source, root / "registry" / "legacy" / "chess" / champion)
            migrated["chess"].append(champion)
    for champion in CACHE_PROMOTIONS:
        source = cache_root / f"champion-{champion}" / "structure.json"
        if source.is_file():
            _legacy_copy(source, root / "registry" / "legacy" / "cache" / champion)
            migrated["cache"].append(champion)

    # R81's two recorded meta-champions are retained as executable loop structures,
    # but never enter a Primus active pointer.
    registry = archive / "candidates" / "scorer_bench_meta_champions" / "registry.json"
    if registry.is_file():
        for item in read_json(registry).get("champions", []):
            champion = str(item["id"])
            source = archive / "candidates" / "scorer_bench_meta_champions" / champion / "code.py"
            if source.is_file():
                destination = root / "registry" / "legacy" / "r81" / champion
                write_immutable(destination / "structure.py", source.read_bytes())
                atomic_json(destination / "manifest.json", {
                    "schema_version": 1,
                    "legacy_only": True,
                    "never_active": True,
                    "outer_policy": item.get("outer_policy"),
                    "source_path": str(source.resolve()),
                    "source_sha256": file_hash(source),
                })
                migrated["r81"].append(champion)

    ecr_root = archive / "research" / "agentloop-harness-research" / "research" / "source" / "agent_structures_v3" / "harness_successors_v8"
    if ecr_root.is_dir():
        for source in sorted(ecr_root.glob("ecr*_preparation_v8.json")):
            destination = root / "registry" / "legacy" / "ecr" / source.stem
            _legacy_copy(source, destination)
            migrated["ecr"].append(source.stem)

    chess_source = chess_root / "p0030" / "loop-structure.json"
    chess_artifact = chess_root / "p0030" / "final-output.json"
    cache_source = cache_root / "champion-r92" / "structure.json"
    cache_artifact = cache_root / "champion-r92" / "policy.py"
    chess_structure = _normalize(read_json(chess_source), origin=str(chess_source.resolve()))
    cache_structure = _normalize(read_json(cache_source), origin=str(cache_source.resolve()))
    chess_structure["calls"][-1]["output_type"] = "engine"
    cache_structure["calls"][-1]["output_type"] = "policy"
    LoopStructure.from_dict(chess_structure).validate(max_calls=4)
    LoopStructure.from_dict(cache_structure).validate(max_calls=4)
    if not _has_active(store, "chess"):
        store.import_champion(
            domain="chess",
            champion_id="chess-inaugural-p0030-loop_bd806f05d36b6863",
            structure=chess_structure,
            artifact=chess_artifact.read_bytes(),
            active=True,
            source={
                "kind": "authoritative-import",
                "path": str(chess_source.resolve()),
                "source_structure_sha256": file_hash(chess_source),
                "metrics": {"elo_vs_stockfish_tier5": -105.297, "wins": 6, "draws": 58, "losses": 36},
            },
        )
    if not _has_active(store, "cache"):
        store.import_champion(
            domain="cache",
            champion_id="cache-inaugural-r92-23a2eb77605a",
            structure=cache_structure,
            artifact=cache_artifact.read_bytes(),
            active=True,
            source={
                "kind": "authoritative-import",
                "path": str(cache_source.resolve()),
                "source_structure_sha256": file_hash(cache_source),
                "source_policy_sha256": file_hash(cache_artifact),
                "metrics": {"cache_score": 85.318},
            },
        )
    _import_bootstrap_domains(store)
    report = {
        "schema_version": 2,
        "migrated": migrated,
        "active_domains": [
            store.champion(domain)["champion_id"] for domain in load_system(root).domains
        ],
    }
    atomic_json(root / "registry" / "migration-report.json", report)
    return report


def _write_tasksets(root: Path, ouroboros: Path) -> None:
    tasksets = root / "config" / "tasksets"
    chess_case_path = ouroboros / "resources" / "benchmarks" / "chessbench100-tier5" / "cases.jsonl"
    chess_base = json.loads(chess_case_path.read_text(encoding="utf-8-sig").splitlines()[0])
    for split, tier in (("development", 4), ("certification", 5)):
        cases = []
        for index in range(1, 41):
            case = json.loads(json.dumps(chess_base))
            case["id"] = f"primus-chess-{split}-bank-{index:02d}"
            case["metadata"]["tier_index"] = tier
            case["metadata"]["benchmark_role"] = f"primus_{split}"
            cases.append(case)
        atomic_json(tasksets / f"chess-{split}.json", {
            "schema_version": 1, "domain": "chess", "split": split, "sealed": True,
            "selection_unit": "suite", "cases": cases
        })
    cache_request = (
        "Return exactly one JSON object {\"files\":{\"policy.py\":\"<complete source>\"}}. "
        "Implement class Policy with access(self, key, value=None) and legal deterministic eviction behavior. "
        "Use only the Python standard library; do not inspect evaluator code or hard-code traces."
    )
    for split, base in (("development", 11000), ("certification", 910000)):
        atomic_json(tasksets / f"cache-{split}.json", {
            "schema_version": 1,
            "domain": "cache",
            "split": split,
            "sealed": True,
            "cases": [
                {"id": f"primus-cache-{split}-{i:02d}", "request": cache_request, "seed": base + i * 7919, "scale": 3, "timeout_seconds": 4.0}
                for i in range(1, 61)
            ],
        })
    coding_specs = {
        "development": [
            ("fib", "Implement solution.py with fib(n). fib(0)=0, fib(1)=1; reject negative n with ValueError.", "from solution import fib\nassert [fib(i) for i in range(11)] == [0,1,1,2,3,5,8,13,21,34,55]\ntry: fib(-1)\nexcept ValueError: pass\nelse: raise AssertionError('negative')\n"),
            ("normalize", "Implement solution.py with normalize_words(text): lowercase Unicode words, collapse whitespace, and return them joined by one space.", "from solution import normalize_words\nassert normalize_words('  Hello   WORLD  ') == 'hello world'\nassert normalize_words('') == ''\n"),
            ("intervals", "Implement solution.py with merge_intervals(items), returning sorted merged closed intervals without mutating input.", "from solution import merge_intervals\nx=[(5,7),(1,3),(2,4),(9,9)]\nassert merge_intervals(x)==[(1,4),(5,7),(9,9)]\nassert x==[(5,7),(1,3),(2,4),(9,9)]\n"),
        ],
        "certification": [
            ("duration", "Implement solution.py with parse_duration(text), accepting integer components like 2h 3m 4s and returning total seconds; reject malformed input.", "from solution import parse_duration\nassert parse_duration('2h 3m 4s')==7384\nassert parse_duration('45m')==2700\nfor x in ('', '3x', '-1s'):\n try: parse_duration(x)\n except ValueError: pass\n else: raise AssertionError(x)\n"),
            ("toposort", "Implement solution.py with topo_sort(nodes, edges), deterministic lexical tie-breaking, and ValueError on cycles.", "from solution import topo_sort\nassert topo_sort(['c','a','b'], [('a','c'),('b','c')])==['a','b','c']\ntry: topo_sort(['a','b'], [('a','b'),('b','a')])\nexcept ValueError: pass\nelse: raise AssertionError('cycle')\n"),
            ("roman", "Implement solution.py with roman_to_int(text), canonical Roman numerals I..MMMCMXCIX only; invalid forms raise ValueError.", "from solution import roman_to_int\nassert roman_to_int('MCMXCIV')==1994\nassert roman_to_int('III')==3\nfor x in ('IIII','IC',''):\n try: roman_to_int(x)\n except ValueError: pass\n else: raise AssertionError(x)\n"),
            ("groups", "Implement solution.py with stable_groups(items, key), returning groups in first-key order and preserving item order.", "from solution import stable_groups\nx=['ant','ape','bat','bee','cat']\nassert stable_groups(x, lambda s:s[0])==[['ant','ape'],['bat','bee'],['cat']]\n"),
            ("checksum", "Implement solution.py with luhn_valid(text), allowing spaces and rejecting all malformed or one-digit inputs.", "from solution import luhn_valid\nassert luhn_valid('4539 1488 0343 6467') is True\nassert luhn_valid('8273 1232 7352 0569') is False\nassert luhn_valid('7') is False\nassert luhn_valid('12x') is False\n"),
        ],
    }
    fixtures = root / "resources" / "benchmarks" / "coding"
    for split, specs in coding_specs.items():
        cases = []
        expanded = specs * (10 if split == "development" else 12)
        for index, (name, request, tests) in enumerate(expanded, 1):
            fixture = fixtures / split / f"{index:02d}-{name}"
            atomic_write(fixture / "tests.py", tests.encode("utf-8"))
            cases.append({
                "id": f"primus-coding-{split}-{index:02d}-{name}",
                "request": request + " Return complete files as the required JSON artifact.",
                "fixture_dir": str(fixture.resolve()),
                "commands": [["python", "tests.py"]],
                "timeout_seconds": 30,
                "protected_sha256": {},
            })
        atomic_json(tasksets / f"coding-{split}.json", {
            "schema_version": 1, "domain": "coding", "split": split, "sealed": True, "cases": cases
        })
    for split, base in (("development", 300), ("certification", 7000)):
        cases = []
        for index in range(1, 61):
            a = base + 17 * index
            b = 11 + (index % 13)
            c = 3 + (index % 7)
            cases.append({
                "id": f"primus-reasoning-{split}-{index:02d}",
                "request": f"Compute exactly: ({a} * {b}) - ({c} ** 3). Return the decimal integer as answer and an empty tool_trace.",
                "grader": "exact",
                "expected": str(a * b - c ** 3),
                "allowed_tools": [],
            })
        atomic_json(tasksets / f"reasoning-{split}.json", {
            "schema_version": 1, "domain": "reasoning_tools", "split": split, "sealed": True, "cases": cases
        })


def _import_bootstrap_domains(store: PrimusStore) -> None:
    for domain, output_type, artifact in (
        ("coding", "patch", {"files": {"solution.py": "# Bootstrap anchor. Replace with a task-complete implementation.\n"}}),
        ("reasoning_tools", "answer", {"answer": "bootstrap", "tool_trace": []}),
    ):
        final_id = f"{domain}_artifact_producer"
        structure = LoopStructure(
            name=f"{domain.replace('_', ' ').title()} Inaugural Evidence-Then-Artifact Dyad",
            organization="two-call sequential lineage",
            information_flow="One contract auditor fixes the obligations; one sole producer emits the complete artifact.",
            calls=(
                LoopCall(
                    id=f"{domain}_contract_auditor",
                    role="single domain contract auditor",
                    objective="Derive one concise, testable obligation record from the task and anchor without authoring the final artifact.",
                    inputs=("task", "champion_artifact", "public_audit", "hypothesis", "loop_structure"),
                    output_type="analysis",
                ),
                LoopCall(
                    id=final_id,
                    role="single complete artifact producer",
                    objective="Use the fixed obligation record to emit exactly one complete artifact satisfying the task contract.",
                    inputs=("task", "champion_artifact", "public_audit", "hypothesis", "loop_structure", f"{domain}_contract_auditor"),
                    output_type=output_type,
                ),
            ),
            final_call_id=final_id,
            changed_factor="bootstrap evidence-to-artifact separation",
            provenance={"kind": "Primus inaugural bootstrap"},
        ).to_dict()
        if _has_active(store, domain):
            continue
        store.import_champion(
            domain=domain,
            champion_id=f"{domain}-inaugural-bootstrap-v1",
            structure=structure,
            artifact=json.dumps(artifact, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            active=True,
            artifact_scope="task_local",
            source={"kind": "bootstrap", "metrics": {}},
        )


def _has_active(store: PrimusStore, domain: str) -> bool:
    try:
        store.champion(domain)
    except LifecycleError:
        return False
    return True
