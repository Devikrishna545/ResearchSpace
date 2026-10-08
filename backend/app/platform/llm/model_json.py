"""Shape-only normalization for JSON returned by small local models."""

import json
import re
from collections.abc import Mapping
from typing import Any

LIST_ALIASES = ("items", "findings", "results", "data", "output")


def _repair_json(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text.strip())


def extract_json(text: str):
    """Parse model output that may be fenced, wrapped in prose or carry trailing commas."""
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        candidates.append(fenced.group(1).strip())
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])
    last_error = None
    for candidate in candidates:
        try:
            return json.loads(_repair_json(candidate))
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not parse JSON response: {last_error}")


def field(obj: Mapping[str, Any], name: str, *aliases: str) -> Any:
    """Return an existing key without coercing its value or inventing a default."""
    for candidate in (name, *aliases):
        for key, value in obj.items():
            if isinstance(key, str) and key.casefold() == candidate.casefold():
                return value
    return None


def list_items(obj: Any, name: str, *, aliases: tuple[str, ...] = (), text_key: str | None = None) -> list[dict]:
    """Accept a bare list, a named list, or a single item; reject invalid content.

    Bare strings are converted to a named text field only when the caller
    explicitly specifies which field the text represents.
    """
    if isinstance(obj, list):
        values = obj
    elif isinstance(obj, dict):
        values = field(obj, name, *aliases)
        if values is None and len(obj) == 1:
            values = field(obj, *LIST_ALIASES)
        if isinstance(values, dict) and field(values, name, *aliases, *LIST_ALIASES) is not None:
            values = field(values, name, *aliases, *LIST_ALIASES)
        if values is None:
            return []
        if not isinstance(values, list):
            values = [values]
    else:
        raise ValueError(f"{name} JSON must be a list or an object containing a list")
    result = []
    for value in values:
        if isinstance(value, dict):
            result.append(value)
        elif isinstance(value, str) and text_key is not None and value.strip():
            result.append({text_key: value})
    return result
