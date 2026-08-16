from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from primus.config import load_domain, load_system
from primus.domains.base import adapter_for
from primus.errors import IntegrityError
from primus.jsonutil import file_hash, read_json
from primus.models import LoopStructure
from primus.store import PrimusStore


def doctor(root: Path) -> list[str]:
    root = root.resolve()
    system = load_system(root)
    store = PrimusStore(root)
    store.initialize()
    checks: list[str] = []
    if shutil.which(system.architect_policy.codex_executable) is None:
        raise IntegrityError(f"Codex executable not found: {system.architect_policy.codex_executable}")
    checks.append("codex-launcher")
    for home in system.executor_policy.codex_home_pool:
        if not Path(home).is_dir():
            raise IntegrityError(f"CODEX_HOME is missing: {home}")
    checks.append(f"codex-home-pool:{len(system.executor_policy.codex_home_pool)}")
    for domain in system.domains:
        config = load_domain(root, domain)
        adapter = adapter_for(system, config)
        champion = store.champion(domain)
        structure = LoopStructure.from_dict(__import__("json").loads(store.object_bytes(
            champion["structure_object"], champion["structure_sha256"]
        )))
        structure.validate(max_calls=config.budget.max_calls)
        pointer = read_json(root / "registry" / "domains" / domain / "active.json")
        if pointer["champion_id"] != champion["champion_id"] or pointer["artifact_sha256"] != champion["artifact_sha256"]:
            raise IntegrityError(f"active pointer mismatch: {domain}")
        if champion.get("artifact_scope") != config.artifact_scope or pointer.get("artifact_scope") != config.artifact_scope:
            raise IntegrityError(f"artifact scope mismatch: {domain}")
        public = read_json(config.public_taskset)
        hidden = read_json(config.certification_taskset)
        public_ids = {str(item["id"]) for item in public["cases"]}
        hidden_ids = {str(item["id"]) for item in hidden["cases"]}
        if len(public_ids) != len(public["cases"]) or len(hidden_ids) != len(hidden["cases"]):
            raise IntegrityError(f"task IDs are not unique: {domain}")
        if public_ids & hidden_ids:
            raise IntegrityError(f"public/hidden task IDs overlap: {domain}")
        public_semantics = adapter.semantic_case_digests("development")
        hidden_semantics = adapter.semantic_case_digests("certification")
        if public_semantics & hidden_semantics:
            raise IntegrityError(f"public/hidden tasks overlap semantically: {domain}")
        selection_unit = str(hidden.get("selection_unit", "case"))
        horizon = max(4, len(hidden["cases"]))
        selection_digests = {
            adapter.semantic_selection_digest(
                "certification",
                [
                    offset + replicate
                    for replicate in range(1, config.evaluation.certification_replicates + 1)
                ],
            )
            for offset in range(horizon)
        }
        checks.append(
            f"domain:{domain}:active={champion['champion_id']}:calls={len(structure.calls)}:"
            f"artifact_scope={config.artifact_scope}:semantic_cases={len(hidden_semantics)}:"
            f"hidden_selection_capacity={len(selection_digests)}:{selection_unit}"
        )
    if "cache" in system.domains and load_domain(root, "cache").adapter == "cache":
        cache = load_domain(root, "cache")
        runner = Path(cache.evaluator["runner_path"])
        if not runner.is_file() or file_hash(runner) != cache.evaluator["runner_sha256"]:
            raise IntegrityError("cache evaluator digest mismatch")
        checks.append("cache-evaluator-pinned")
    if "chess" not in system.domains or load_domain(root, "chess").adapter != "chess":
        chess = None
    else:
        chess = load_domain(root, "chess")
    if chess is not None:
        checks.extend(_check_builtin_chess(chess))
    for path in (root / "registry" / "legacy").rglob("manifest.json"):
        manifest = read_json(path)
        if manifest.get("never_active") is not True:
            raise IntegrityError(f"legacy manifest can become active: {path}")
    checks.append("legacy-quarantined")
    checks.extend(store.audit())
    return checks


def _check_builtin_chess(chess: Any) -> list[str]:
    chess_tasksets = {
        "development": read_json(chess.public_taskset),
        "certification": read_json(chess.certification_taskset),
    }
    opening_fens: dict[str, set[str]] = {}
    opening_hashes: dict[str, str] = {}
    expected_ecos = {f"{letter}{number:02d}" for letter in "ABCDE" for number in range(0, 100, 10)}
    for split, taskset in chess_tasksets.items():
        cases = taskset["cases"]
        contracts = {
            (str(case["metadata"]["openings_path"]), str(case["metadata"]["openings_sha256"]))
            for case in cases
        }
        if len(contracts) != 1:
            raise IntegrityError(f"Chess {split} cases do not share one frozen opening contract")
        path_raw, expected_hash = next(iter(contracts))
        opening_path = Path(path_raw)
        if not opening_path.is_file() or file_hash(opening_path) != expected_hash:
            raise IntegrityError(f"Chess {split} opening digest mismatch")
        opening_rows = read_json(opening_path).get("openings", [])
        ecos = {str(row.get("eco")) for row in opening_rows}
        fens = {str(row.get("fen")) for row in opening_rows}
        if len(opening_rows) != 50 or ecos != expected_ecos or len(fens) != 50:
            raise IntegrityError(f"Chess {split} opening set is not a valid 50-decile bank")
        opening_fens[split] = fens
        opening_hashes[split] = expected_hash
    if opening_hashes["development"] == opening_hashes["certification"]:
        raise IntegrityError("Chess public and certification opening bytes are identical")
    if opening_fens["development"] & opening_fens["certification"]:
        raise IntegrityError("Chess public and certification opening FENs overlap")
    for case in chess_tasksets["certification"]["cases"][:1]:
        stockfish = Path(case["metadata"]["stockfish_path"])
        if not stockfish.is_file() or file_hash(stockfish) != case["metadata"]["stockfish_sha256"]:
            raise IntegrityError("Stockfish binary digest mismatch")
    return ["chess-evaluator-pinned", "chess-opening-split:50+50:disjoint"]


def status(root: Path) -> dict[str, Any]:
    root = root.resolve()
    system = load_system(root)
    store = PrimusStore(root)
    store.initialize()
    domains: dict[str, Any] = {}
    for domain in system.domains:
        champion = store.champion(domain)
        latest = store.latest_round(domain)
        domains[domain] = {
            "champion_id": champion["champion_id"],
            "structure_sha256": champion["structure_sha256"],
            "artifact_sha256": champion["artifact_sha256"],
            "artifact_scope": champion.get("artifact_scope"),
            "latest_round": latest,
        }
    return {"root": str(root.resolve()), "domains": domains}
