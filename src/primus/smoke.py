from __future__ import annotations

from pathlib import Path
from typing import Any

from primus.config import load_domain, load_system
from primus.domains.base import adapter_for
from primus.lock import ExclusiveLease
from primus.store import PrimusStore


def smoke(root: Path) -> dict[str, Any]:
    """Exercise every configured adapter that can provide a safe public sample."""
    root = root.resolve()
    system = load_system(root)
    store = PrimusStore(root)
    store.initialize()
    output = root / "runs" / "_smoke"
    result: dict[str, Any] = {}
    with ExclusiveLease(system.heavy_lock, owner="primus:smoke"):
        for domain in system.domains:
            config = load_domain(root, domain)
            adapter = adapter_for(system, config)
            champion = store.champion(domain)
            raw = store.object_bytes(champion["artifact_object"], champion["artifact_sha256"])
            reference = adapter.decode_reference_artifact(raw)
            payload = adapter.smoke_payload(reference)
            if payload is None:
                result[domain] = {
                    "skipped": True,
                    "reason": "task-local adapter has no public smoke payload",
                }
                continue
            outcome = adapter.evaluate(
                payload=payload,
                split="development",
                replicate=1,
                output_directory=output / domain,
            )
            result[domain] = {
                "valid": outcome.valid,
                "score": outcome.score,
                "failure_class": outcome.failure_class,
                "evidence": list(outcome.evidence),
            }
    evaluated = [
        value for value in result.values()
        if isinstance(value, dict) and "valid" in value
    ]
    result["ok"] = bool(evaluated) and all(bool(value["valid"]) for value in evaluated)
    return result
