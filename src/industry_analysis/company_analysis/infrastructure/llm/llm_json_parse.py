"""Parse JSON objects from LLM text (fences, leading/trailing prose)."""

from __future__ import annotations

from typing import Any

import orjson


def _strip_code_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.split("\n")
    if len(lines) < 2:
        return s
    first = lines[0].strip()
    if not first.startswith("```"):
        return s
    body_lines = lines[1:]
    while body_lines and body_lines[-1].strip() == "```":
        body_lines.pop()
    return "\n".join(body_lines).strip()


def _extract_balanced_object(s: str) -> str | None:
    """Return substring from first ``{`` through matching ``}``, respecting strings."""
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    i = start
    while i < len(s):
        c = s[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
        i += 1
    return None


def parse_llm_json_object(raw: str) -> dict[str, Any]:
    """
    Parse a single JSON object from model output.

    Handles common drift: markdown fences, BOM, short preamble before ``{``.
    """
    text = raw.lstrip("\ufeff").strip()
    text = _strip_code_fence(text)
    try:
        parsed: Any = orjson.loads(text)
    except orjson.JSONDecodeError:
        candidate = _extract_balanced_object(text)
        if candidate is None:
            raise
        parsed = orjson.loads(candidate)
    if not isinstance(parsed, dict):
        msg = "Model JSON was not an object"
        raise ValueError(msg)
    return parsed
