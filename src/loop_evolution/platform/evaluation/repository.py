from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loop_evolution.platform.domain import TaskCase


def _read_jsonl_records(path: Path) -> tuple[tuple[int, dict[str, Any]], ...]:
    """Read JSONL using LF only; Unicode line separators are valid inside JSON strings."""

    records: list[tuple[int, dict[str, Any]]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").split("\n"),
        start=1,
    ):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line.removesuffix("\r"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL in {path}:{line_number}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"benchmark JSONL record must be an object: {path}:{line_number}")
        records.append((line_number, payload))
    return tuple(records)


class BenchmarkRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, task_ids: tuple[str, ...] = ()) -> tuple[TaskCase, ...]:
        if not self.root.is_dir():
            raise FileNotFoundError(f"benchmark directory does not exist: {self.root}")
        selected = set(task_ids)
        cases: list[TaskCase] = []
        seen_ids: set[str] = set()
        for path in sorted(self.root.glob("*.jsonl")):
            for line_number, payload in _read_jsonl_records(path):
                metadata = dict(payload.get("metadata", {}))
                for key in ("fixture_dir", "hidden_tests_dir"):
                    if key in metadata:
                        configured = Path(str(metadata[key]))
                        metadata[key] = str(
                            configured.resolve()
                            if configured.is_absolute()
                            else (path.parent / configured).resolve()
                        )
                case = TaskCase(
                    task_id=str(payload["id"]),
                    family=str(payload["family"]),
                    request=str(payload["request"]),
                    expected=payload["expected"],
                    scorer=str(payload.get("scorer", "exact")),
                    critical=bool(payload.get("critical", False)),
                    metadata=metadata,
                )
                if not case.task_id or not case.family or not case.request:
                    raise ValueError(f"benchmark identity fields must be non-empty: {path}:{line_number}")
                if case.task_id in seen_ids:
                    raise ValueError(f"duplicate benchmark task ID: {case.task_id}")
                seen_ids.add(case.task_id)
                if not selected or case.task_id in selected:
                    cases.append(case)
        missing = selected - {case.task_id for case in cases}
        if missing:
            raise KeyError(f"benchmark tasks not found: {sorted(missing)}")
        return tuple(cases)
