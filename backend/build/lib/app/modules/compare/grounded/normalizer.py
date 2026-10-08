"""One response normalizer for every grounded LLM call.

It accepts the valid-but-unexpected JSON shapes documented in
evaluations/compare/DECISION.md and classifies the outcome so that parser
defects ("valid JSON in a shape we failed to map") are never counted as
model failures ("no usable JSON").
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

WRAPPER_KEYS = ("items", "findings", "results", "data", "output", "response", "answer")
NOT_FOUND_KEYS = ("not_found", "notfound", "none_found", "insufficient_evidence")
PAPER_LABEL = re.compile(r"^(?:P|Paper\s*)(\d{1,2})$", re.I)

# Outcome classes. Only PARSER_DEFECT blames our code; INVALID_JSON/EMPTY blame the model.
OK = "ok"
NORMALIZED = "normalized"
NOT_FOUND = "not_found"
EMPTY = "model_empty"
INVALID_JSON = "model_invalid_json"
PARSER_DEFECT = "parser_defect"
MODEL_ERROR = "model_error"


@dataclass
class NormalizedResult:
    items: list[dict] = field(default_factory=list)
    not_found: bool = False
    status: str = OK
    notes: list[str] = field(default_factory=list)
    parsed: Any = None

    @property
    def usable(self) -> bool:
        return self.status in {OK, NORMALIZED, NOT_FOUND}


def strip_reasoning(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I).strip()


def _repair(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text.strip())


def parse_json(raw: str) -> tuple[Any, list[str]]:
    """Parse fenced / prose-wrapped / trailing-comma JSON. Raises ValueError if impossible."""
    text = strip_reasoning(raw)
    notes = []
    candidates = [(text, None)]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        candidates.append((fenced.group(1).strip(), "fenced_json"))
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            candidates.append((text[start:end + 1], "embedded_json"))
    last = None
    for candidate, note in candidates:
        for body, repair_note in ((candidate, None), (_repair(candidate), "trailing_comma")):
            try:
                value = json.loads(body)
            except Exception as exc:
                last = exc
                continue
            notes.extend(n for n in (note, repair_note if body != candidate else None) if n)
            return value, notes
    salvaged = salvage_truncated(text)
    if salvaged is not None:
        return salvaged, ["truncated_output_salvaged"]
    raise ValueError(f"no parseable JSON: {last}")


def salvage_truncated(text: str) -> dict | None:
    """Recover the complete objects of the first array in output cut off by a token cap.

    Every recovered item is still validated downstream; the note marks the result partial.
    """
    match = re.search(r'"([A-Za-z_]+)"\s*:\s*\[', text)
    if not match:
        return None
    decoder = json.JSONDecoder()
    position, items = match.end(), []
    while True:
        while position < len(text) and text[position] in " \r\n\t,":
            position += 1
        if position >= len(text) or text[position] != "{":
            break
        try:
            item, position = decoder.raw_decode(text, position)
        except ValueError:
            break
        items.append(item)
    return {match.group(1): items} if items else None


def key_variants(name: str) -> list[str]:
    base = name.strip()
    variants = [base]
    if base.endswith("ies"):
        variants.append(base[:-3] + "y")
    elif base.endswith("s"):
        variants.append(base[:-1])
    else:
        variants.append(base + "s")
        if base.endswith("y"):
            variants.append(base[:-1] + "ies")
    return list(dict.fromkeys(v for v in variants if v))


def get_key(obj: dict, *names: str) -> Any:
    wanted = {v.casefold().replace(" ", "_").replace("-", "_") for n in names for v in key_variants(n)}
    for key, value in obj.items():
        if isinstance(key, str) and key.casefold().replace(" ", "_").replace("-", "_") in wanted:
            return value
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1"}
    return False


def _as_items(values: Any, text_key: str, notes: list[str]) -> list[dict]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
        notes.append("single_item_as_list")
    items = []
    for value in values:
        if isinstance(value, dict):
            items.append(value)
        elif isinstance(value, (str, int, float)) and str(value).strip():
            items.append({text_key: str(value).strip()})
            notes.append("bare_value_as_object")
    return items


def normalize(raw: str, list_names: Iterable[str], *, text_key: str = "value", allow_paper_labels: bool = False) -> NormalizedResult:
    """Map any recognised shape onto a flat list of item dicts.

    Items from top-level paper-label maps (``{"P1": [...], "P2": [...]}``) receive
    a ``_paper_label`` key so callers can enforce paper ownership.
    """
    names = [n for n in list_names if n]
    if raw is None or not str(raw).strip():
        return NormalizedResult(status=EMPTY, notes=["empty_output"])
    try:
        obj, notes = parse_json(str(raw))
    except ValueError as exc:
        return NormalizedResult(status=INVALID_JSON, notes=[str(exc)[:200]])
    result = NormalizedResult(parsed=obj, notes=list(notes))
    unwrap_depth = 0
    while isinstance(obj, dict) and unwrap_depth < 3:
        if any(_truthy(get_key(obj, k)) for k in NOT_FOUND_KEYS):
            result.not_found = True
        direct = get_key(obj, *names) if names else None
        if direct is not None:
            if isinstance(direct, dict) and get_key(direct, *names, *WRAPPER_KEYS) is not None:
                obj = direct
                result.notes.append("nested_named_wrapper")
                unwrap_depth += 1
                continue
            if names and not any(k in obj for k in names):
                result.notes.append("key_variant")
            result.items = _as_items(direct, text_key, result.notes)
            if direct == []:
                # A recognised key holding an empty list is an implicit "nothing found".
                result.not_found = True
                result.notes.append("empty_named_list")
            break
        labelled = {k: v for k, v in obj.items() if isinstance(k, str) and PAPER_LABEL.match(k.strip())}
        if allow_paper_labels and labelled:
            for label, values in labelled.items():
                if isinstance(values, dict):
                    inner = get_key(values, *names, *WRAPPER_KEYS)
                    values = inner if inner is not None else [values]
                for item in _as_items(values, text_key, result.notes):
                    result.items.append({**item, "_paper_label": "P" + PAPER_LABEL.match(label.strip()).group(1)})
            result.notes.append("paper_label_map")
            break
        wrapper = get_key(obj, *WRAPPER_KEYS)
        if wrapper is not None:
            result.notes.append("generic_wrapper")
            if isinstance(wrapper, dict):
                obj = wrapper
                unwrap_depth += 1
                continue
            result.items = _as_items(wrapper, text_key, result.notes)
            break
        # A single object carrying the item fields directly, e.g. {"value": "...", "quote": "..."}.
        if get_key(obj, text_key) is not None:
            result.items = [obj]
            result.notes.append("single_object_as_item")
        break
    if isinstance(obj, list):
        result.items = _as_items(obj, text_key, result.notes)
        result.notes.append("bare_list")
    if result.items:
        result.status = NORMALIZED if any(n not in {"fenced_json"} for n in result.notes) else OK
    elif result.not_found:
        result.status = NOT_FOUND
    elif obj in ({}, [], None) or (isinstance(obj, dict) and all(v in ([], {}, None, "") for v in obj.values())):
        result.status = EMPTY
    else:
        result.status = PARSER_DEFECT
    return result


def normalize_object(raw: str) -> NormalizedResult:
    """For single-object answers such as validator verdicts."""
    if raw is None or not str(raw).strip():
        return NormalizedResult(status=EMPTY, notes=["empty_output"])
    try:
        obj, notes = parse_json(str(raw))
    except ValueError as exc:
        return NormalizedResult(status=INVALID_JSON, notes=[str(exc)[:200]])
    for _ in range(2):
        if isinstance(obj, dict) and len(obj) == 1:
            inner = get_key(obj, *WRAPPER_KEYS, "verdict", "validation", "result")
            if isinstance(inner, dict):
                obj = inner
                notes.append("generic_wrapper")
                continue
        break
    if isinstance(obj, list) and len(obj) == 1 and isinstance(obj[0], dict):
        obj = obj[0]
        notes.append("single_item_list")
    if not isinstance(obj, dict):
        return NormalizedResult(status=PARSER_DEFECT, parsed=obj, notes=notes)
    if not obj:
        return NormalizedResult(status=EMPTY, parsed=obj, notes=notes)
    return NormalizedResult(items=[obj], status=NORMALIZED if notes else OK, parsed=obj, notes=notes)


def table_cells(value: Any) -> list[list[str]] | None:
    """Accept nested ``{"table": {"cells": ...}}``, ``{"cells": ...}``, ``{"rows": ...}`` or a bare grid."""
    for _ in range(3):
        if isinstance(value, dict):
            inner = get_key(value, "cells", "rows", "table", "grid", "data")
            if inner is None:
                return None
            value = inner
            continue
        break
    if not isinstance(value, list) or not value:
        return None
    grid = []
    for row in value:
        if isinstance(row, dict):
            row = list(row.values())
        if not isinstance(row, list):
            return None
        grid.append(["" if cell is None else str(cell).strip() for cell in row])
    return grid


def verdict_word(value: Any, allowed: Iterable[str], default: str = "uncertain") -> str:
    options = {a.casefold(): a for a in allowed}
    if isinstance(value, bool):
        value = "yes" if value else "no"
    text = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if text in options:
        return options[text]
    for key, original in options.items():
        if text.startswith(key):
            return original
    return default
