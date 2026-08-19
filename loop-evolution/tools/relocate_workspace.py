from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


TEXT_SUFFIXES = frozenset({".json", ".jsonl"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _workspace_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _replace_path(text: str, source: Path, destination: Path) -> str:
    old = str(source.resolve())
    new = str(destination.resolve())
    # JSON escapes Windows separators, while JSONL may also contain ordinary
    # strings embedded in other serialized fields. Supporting both keeps the
    # relocation mechanical and preserves the original formatting.
    return text.replace(old.replace("\\", "\\\\"), new.replace("\\", "\\\\")).replace(
        old, new
    )


def _validate(path: Path, text: str) -> None:
    if path.suffix == ".json":
        json.loads(text)
        return
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL after relocation: {path}:{line_number}") from exc


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.relocating")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _mappings(old_project: Path, new_project: Path, old_v3: Path | None) -> list[tuple[Path, Path]]:
    mappings = [
        (
            old_project / "workspace",
            new_project / "experiments" / "chess-tier5" / "workspace",
        ),
        (old_project / "package_evolution", new_project / "src" / "loop_evolution"),
        (old_project / "config.json", new_project / "experiments" / "chess-tier5" / "config.json"),
        (old_project / "run.py", new_project / "run.py"),
    ]
    if old_v3 is not None:
        old_bootstrap = old_v3 / "workspace-chess-tier5-r6-r10-factorized-20260730" / "r20"
        mappings.extend(
            [
                (
                    old_bootstrap / "arms" / "candidate" / "control" / "benchmark-result-receipt.json",
                    new_project / "imports" / "v3-lite-r20" / "benchmark-result-receipt.json",
                ),
                (
                    old_bootstrap / "arms" / "candidate" / "final-output.json",
                    new_project / "imports" / "v3-lite-r20" / "final-output.json",
                ),
                (
                    old_bootstrap / "selected-experimental-architecture.json",
                    new_project / "imports" / "v3-lite-r20" / "loop-structure.json",
                ),
                (
                    old_v3 / "configs" / "sol-xhigh-structural-proposer-1800s.json",
                    new_project / "resources" / "policies" / "sol-xhigh-structural-proposer-1800s.json",
                ),
                (
                    old_v3 / "configs" / "luna-high-slot1-chessbench100-v1.json",
                    new_project / "resources" / "policies" / "luna-high-slot1-chessbench100-v1.json",
                ),
                (
                    old_v3 / "benchmarks" / "loopsy-chessbench100-windows-v1" / "screening",
                    new_project / "resources" / "benchmarks" / "chessbench100-tier5",
                ),
            ]
        )
    mappings.append((old_project, new_project))
    return sorted(mappings, key=lambda pair: len(str(pair[0])), reverse=True)


def _candidate_files(roots: Iterable[Path]) -> list[Path]:
    found: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        found.update(path for path in root.rglob("*") if path.is_file() and path.suffix in TEXT_SUFFIXES)
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(description="Relocate stored paths in a copied loop-evolution workspace.")
    parser.add_argument("--from-project", type=Path, required=True)
    parser.add_argument("--to-project", type=Path, required=True)
    parser.add_argument("--from-v3", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write changes; otherwise only report them.")
    args = parser.parse_args()

    new_project = args.to_project.resolve()
    workspace = new_project / "experiments" / "chess-tier5" / "workspace"
    mappings = _mappings(args.from_project.resolve(), new_project, args.from_v3.resolve() if args.from_v3 else None)
    files = _candidate_files((workspace,))
    before_digest = _workspace_digest(workspace)
    changed: list[dict[str, str]] = []

    for path in files:
        original = path.read_text(encoding="utf-8")
        updated = original
        for source, destination in mappings:
            updated = _replace_path(updated, source, destination)
        if updated == original:
            continue
        _validate(path, updated)
        changed.append(
            {
                "path": path.relative_to(new_project).as_posix(),
                "before_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                "after_sha256": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
            }
        )
        if args.apply:
            _atomic_text(path, updated)

    after_digest = _workspace_digest(workspace) if args.apply else None
    result = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "applied": args.apply,
        "from_project": str(args.from_project.resolve()),
        "to_project": str(new_project),
        "from_v3": str(args.from_v3.resolve()) if args.from_v3 else None,
        "workspace": str(workspace),
        "files_scanned": len(files),
        "files_changed": len(changed),
        "workspace_digest_before": before_digest,
        "workspace_digest_after": after_digest,
        "changes": changed,
    }
    if args.apply:
        manifest = new_project / "migration" / "relocation-v3-lite-r16.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        _atomic_text(manifest, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        result["manifest"] = str(manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
