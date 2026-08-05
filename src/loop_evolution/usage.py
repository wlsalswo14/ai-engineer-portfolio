from __future__ import annotations

from typing import Any, Iterable


RAW_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "model_calls",
)


def empty_usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "effective_tokens": 0,
        "model_calls": 0,
    }


def normalize_usage(value: dict[str, Any] | None) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    raw = {field: max(0, int(source.get(field, 0) or 0)) for field in RAW_FIELDS}
    uncached = max(0, raw["input_tokens"] - raw["cached_input_tokens"])
    return {
        **raw,
        "uncached_input_tokens": uncached,
        "total_tokens": raw["input_tokens"] + raw["output_tokens"],
        "effective_tokens": uncached + raw["output_tokens"],
    }


def sum_usage(values: Iterable[dict[str, Any] | None]) -> dict[str, int]:
    total = {field: 0 for field in RAW_FIELDS}
    for value in values:
        normalized = normalize_usage(value)
        for field in RAW_FIELDS:
            total[field] += normalized[field]
    return normalize_usage(total)


def traces_usage(traces: list[dict[str, Any]] | None) -> dict[str, int]:
    return sum_usage(
        trace.get("usage")
        for trace in (traces or [])
        if isinstance(trace, dict)
    )


def attempt_usage(attempt: dict[str, Any]) -> dict[str, Any]:
    traces = attempt.get("execution_traces", {})
    incumbent = traces_usage(traces.get("incumbent", []))
    candidate = traces_usage(traces.get("candidate", []))
    return {
        "incumbent": incumbent,
        "candidate": candidate,
        "combined": sum_usage([incumbent, candidate]),
    }


def pair_usage(attempts: list[dict[str, Any]], *, accepted: bool) -> dict[str, Any]:
    per_attempt = [attempt_usage(attempt) for attempt in attempts]
    decision = per_attempt[-1] if per_attempt else {
        "incumbent": empty_usage(),
        "candidate": empty_usage(),
        "combined": empty_usage(),
    }
    invalid = per_attempt[:-1] if accepted else per_attempt
    return {
        "all_attempts": {
            "incumbent": sum_usage(item["incumbent"] for item in per_attempt),
            "candidate": sum_usage(item["candidate"] for item in per_attempt),
            "combined": sum_usage(item["combined"] for item in per_attempt),
        },
        "decision_attempt": decision,
        "decision_attempt_valid": accepted,
        "invalid_attempts": {
            "count": len(invalid),
            "incumbent": sum_usage(item["incumbent"] for item in invalid),
            "candidate": sum_usage(item["candidate"] for item in invalid),
            "combined": sum_usage(item["combined"] for item in invalid),
        },
        "per_attempt": [
            {"attempt": index, **usage}
            for index, usage in enumerate(per_attempt, start=1)
        ],
    }
