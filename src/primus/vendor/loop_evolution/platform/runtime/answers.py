from __future__ import annotations

import json
import re

_FINAL_ANSWER_LINE = re.compile(
    r"^\s*(?:final\s+answer|answer|최종\s*답(?:변)?|정답)\s*[:：]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_final_answer(text: str) -> str:
    """Extract the scoring answer while raw collaboration text remains intact."""
    stripped = text.strip()
    if not stripped:
        return ""

    parsed = _json_object(stripped)
    if parsed is not None:
        for key in ("final_answer", "answer"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    marked_answers = _FINAL_ANSWER_LINE.findall(stripped)
    if marked_answers:
        return marked_answers[-1].strip().strip("`")

    non_empty_lines = tuple(line.strip() for line in stripped.splitlines() if line.strip())
    if len(non_empty_lines) == 1:
        return non_empty_lines[0].strip("`")
    return stripped


def _json_object(text: str) -> dict[str, object] | None:
    candidate = text
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None
