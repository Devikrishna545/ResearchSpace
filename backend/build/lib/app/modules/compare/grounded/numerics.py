"""Deterministic numeric, table and statistical analysis. The LLM may explain these values, never create them."""

import math
import re
from dataclasses import asdict, dataclass

import numpy as np

NUMBER = re.compile(r"(?P<sign>[-+\u2212]?)\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)\s*(?P<suffix>[kKmMbB](?![a-zA-Z])|thousand|million|billion)?\s*(?P<pct>%|percent|pp|percentage points?)?")
PLUS_MINUS = re.compile(r"(?:\u00b1|\+/-|\+-)\s*(\d+(?:\.\d+)?)")
SUFFIX = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}

HIGHER_BETTER = {"accuracy", "f1", "precision", "recall", "bleu", "rouge", "rouge-l", "rouge-1", "rouge-2", "auc", "roc-auc",
                 "map", "ndcg", "mrr", "exact match", "em", "top-1 accuracy", "top-5 accuracy", "meteor", "spearman", "pearson",
                 "r2", "iou", "miou", "dice", "success rate", "hit rate", "recall@k"}
LOWER_BETTER = {"perplexity", "error rate", "wer", "cer", "loss", "mse", "rmse", "mae", "latency", "fid", "eer", "top-1 error", "top-5 error"}
BOUNDED_METRICS = {"accuracy", "f1", "precision", "recall", "auc", "roc-auc", "map", "exact match", "em", "top-1 accuracy",
                   "top-5 accuracy", "error rate", "iou", "miou", "dice", "success rate", "hit rate", "top-1 error", "top-5 error"}
METRIC_ALIASES = {"acc": "accuracy", "f1 score": "f1", "f1-score": "f1", "f-measure": "f1", "f-score": "f1", "macro f1": "f1",
                  "ppl": "perplexity", "word error rate": "wer", "character error rate": "cer", "mean squared error": "mse",
                  "root mean squared error": "rmse", "mean absolute error": "mae", "area under the curve": "auc",
                  "mean average precision": "map", "exact-match": "exact match", "bleu score": "bleu", "rouge-l f1": "rouge-l"}


@dataclass
class ParsedNumber:
    value: float
    raw: str
    is_percent: bool = False
    unit: str | None = None
    plus_minus: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def parse_number(text) -> ParsedNumber | None:
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return ParsedNumber(value=float(text), raw=str(text))
    raw = str(text).strip()
    match = NUMBER.search(raw.replace("\u2212", "-"))
    if not match:
        return None
    value = float(match.group("num").replace(",", ""))
    if match.group("sign") in {"-", "\u2212"}:
        value = -value
    suffix = (match.group("suffix") or "").lower()
    if suffix:
        value *= SUFFIX[suffix]
    unit_text = raw[match.end():].strip()
    unit = re.match(r"([A-Za-z][A-Za-z\- ]{0,30})", unit_text)
    pm = PLUS_MINUS.search(raw)
    return ParsedNumber(value=value, raw=raw, is_percent=bool(match.group("pct")),
                        unit=singular(unit.group(1).strip().lower()) if unit else None,
                        plus_minus=float(pm.group(1)) if pm else None)


def singular(word: str) -> str:
    word = word.strip()
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def canonical_metric(name: str | None) -> str | None:
    if not name:
        return None
    text = re.sub(r"\s+", " ", str(name).casefold().strip().strip(".:"))
    text = re.sub(r"\s*\[%\]|\s*\(%\)|\s*%", "", text).strip()
    # "percent accuracy" and "accuracy (%)" name the same metric on the same scale.
    text = re.sub(r"^(percent|percentage)\s+", "", text)
    return METRIC_ALIASES.get(text, text)


def metric_direction(name: str | None) -> str:
    metric = canonical_metric(name)
    if metric in HIGHER_BETTER:
        return "higher_is_better"
    if metric in LOWER_BETTER:
        return "lower_is_better"
    return "unknown"


def _to_percent_scale(number: ParsedNumber, metric: str | None) -> float | None:
    if number.is_percent:
        return number.value
    if metric in BOUNDED_METRICS:
        if 0 <= number.value <= 1:
            return number.value * 100
        if 1 < number.value <= 100:
            return number.value  # printed on a 0-100 scale without a % sign
    return None


def compare_values(a: ParsedNumber, b: ParsedNumber, metric: str | None) -> dict:
    """Compare two reported values of the same metric under matching conditions."""
    metric = canonical_metric(metric)
    a_pct, b_pct = _to_percent_scale(a, metric), _to_percent_scale(b, metric)
    out = {"metric": metric, "direction": metric_direction(metric), "a": a.as_dict(), "b": b.as_dict()}
    if a_pct is not None and b_pct is not None:
        out["scale"] = "percent"
        out["a_value"], out["b_value"] = round(a_pct, 6), round(b_pct, 6)
        out["difference_percentage_points"] = round(a_pct - b_pct, 6)
        out["relative_change_percent"] = round((a_pct - b_pct) / b_pct * 100, 6) if b_pct else None
    elif (a.unit or None) == (b.unit or None) and a.is_percent == b.is_percent:
        out["scale"] = a.unit or "raw"
        out["a_value"], out["b_value"] = a.value, b.value
        out["difference"] = round(a.value - b.value, 6)
        out["relative_change_percent"] = round((a.value - b.value) / b.value * 100, 6) if b.value else None
    else:
        return {**out, "comparable": False, "reason": "values use different scales or units"}
    direction = out["direction"]
    if direction != "unknown" and out["a_value"] != out["b_value"]:
        a_better = out["a_value"] > out["b_value"] if direction == "higher_is_better" else out["a_value"] < out["b_value"]
        out["better"] = "a" if a_better else "b"
    elif out["a_value"] == out["b_value"]:
        out["better"] = "tie"
    out["comparable"] = True
    return out


def result_conditions_match(a_attr: dict, b_attr: dict, a_value: str, b_value: str) -> tuple[bool, list[str]]:
    """Require the same metric and dataset, and matching split/condition when both are stated."""
    from app.modules.compare.grounded.extraction import normalize_value

    reasons = []
    metric_a = canonical_metric(a_attr.get("metric")) or None
    metric_b = canonical_metric(b_attr.get("metric")) or None
    if not metric_a or not metric_b:
        reasons.append("metric not stated for both results")
    elif metric_a != metric_b:
        reasons.append(f"different metrics ({metric_a} vs {metric_b})")
    dataset_a, dataset_b = a_attr.get("dataset"), b_attr.get("dataset")
    if not dataset_a or not dataset_b:
        reasons.append("evaluation dataset not stated for both results")
    elif dataset_key(dataset_a) != dataset_key(dataset_b):
        reasons.append(f"different datasets ({dataset_a} vs {dataset_b})")
    for key in ("split", "condition"):
        if a_attr.get(key) and b_attr.get(key) and normalize_value(str(a_attr[key])) != normalize_value(str(b_attr[key])):
            reasons.append(f"different {key} ({a_attr[key]} vs {b_attr[key]})")
    return not reasons, reasons


GENERIC_WORDS = {"dataset", "datasets", "corpus", "corpora", "data", "benchmark", "set", "the", "collection"}


def dataset_key(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", str(value).casefold())
    return " ".join(singular(w) for w in words if w not in GENERIC_WORDS) or " ".join(words)


def compare_counts(a: ParsedNumber, b: ParsedNumber) -> dict:
    out = {"a": a.as_dict(), "b": b.as_dict()}
    if (a.unit or None) != (b.unit or None):
        return {**out, "comparable": False, "reason": f"different units ({a.unit or 'unspecified'} vs {b.unit or 'unspecified'})"}
    out.update(comparable=True, unit=a.unit, difference=a.value - b.value,
               ratio=round(a.value / b.value, 6) if b.value else None)
    return out


def split_fractions(attrs: dict) -> dict | None:
    parts = {k: parse_number(attrs.get(k)) for k in ("train", "validation", "test")}
    known = {k: v for k, v in parts.items() if v is not None}
    if not known:
        return None
    if all(v.is_percent for v in known.values()):
        return {k: round(v.value / 100, 6) for k, v in known.items()}
    total = sum(v.value for v in known.values())
    if len(known) >= 2 and total > 0 and all(not v.is_percent for v in known.values()):
        return {k: round(v.value / total, 6) for k, v in known.items()}
    return None


def compare_splits(a: dict, b: dict) -> dict:
    fa, fb = split_fractions(a), split_fractions(b)
    scheme_a, scheme_b = a.get("scheme"), b.get("scheme")
    out = {"a": {k: a.get(k) for k in ("train", "validation", "test", "unit", "scheme")},
           "b": {k: b.get(k) for k in ("train", "validation", "test", "unit", "scheme")}}
    if fa is None or fb is None:
        return {**out, "comparable": False, "reason": "split proportions are not fully stated for both papers",
                "same_scheme": bool(scheme_a and scheme_b and scheme_a.casefold() == scheme_b.casefold())}
    shared = sorted(set(fa) & set(fb))
    return {**out, "comparable": bool(shared), "a_fractions": fa, "b_fractions": fb,
            "fraction_difference": {k: round(fa[k] - fb[k], 6) for k in shared}}


def check_statistics(attrs: dict) -> dict:
    """Validate reported p-values, thresholds, confidence intervals, SDs and test statistics."""
    checks = []
    p = parse_number(attrs.get("p_value"))
    raw_p = str(attrs.get("p_value") or "")
    threshold = parse_number(attrs.get("threshold"))
    if p is not None:
        valid = 0 <= p.value <= 1
        checks.append({"check": "p_value_range", "ok": valid, "value": p.value})
        if valid and threshold is not None:
            bound = "<" in raw_p or "\u2264" in raw_p
            checks.append({"check": "p_below_threshold", "ok": p.value <= threshold.value, "p": p.value,
                           "threshold": threshold.value, "reported_as_bound": bound})
    statistic = parse_number(attrs.get("statistic"))
    df = parse_number(attrs.get("df"))
    test = str(attrs.get("test") or "").casefold()
    if statistic is not None and p is not None and "<" not in raw_p and ">" not in raw_p:
        from scipy import stats

        recomputed = None
        if ("t-test" in test or test.startswith("t ") or test == "t") and df is not None and df.value > 0:
            recomputed = float(2 * stats.t.sf(abs(statistic.value), df.value))
        elif "z" in test.split() or "z-test" in test:
            recomputed = float(2 * stats.norm.sf(abs(statistic.value)))
        elif ("chi" in test) and df is not None and df.value > 0:
            recomputed = float(stats.chi2.sf(statistic.value, df.value))
        if recomputed is not None:
            tolerance = max(0.005, 0.1 * p.value)
            checks.append({"check": "p_value_recomputed", "ok": abs(recomputed - p.value) <= tolerance,
                           "reported": p.value, "recomputed": round(recomputed, 6), "test": test})
    lower, upper = parse_number(attrs.get("lower")), parse_number(attrs.get("upper"))
    point = parse_number(attrs.get("value"))
    kind = str(attrs.get("kind") or "").casefold()
    if lower is not None and upper is not None:
        ok = lower.value <= upper.value and (point is None or kind in {"sd", "std", "standard deviation", "se"}
                                              or lower.value <= point.value <= upper.value)
        checks.append({"check": "confidence_interval_order", "ok": ok, "lower": lower.value, "upper": upper.value,
                       "point": point.value if point else None})
    if point is not None and kind in {"sd", "std", "standard deviation", "se", "standard error"}:
        checks.append({"check": "dispersion_non_negative", "ok": point.value >= 0, "value": point.value})
    return {"checks": checks, "all_ok": all(c["ok"] for c in checks) if checks else None}


def cohens_d(mean_a: float, sd_a: float, n_a: int, mean_b: float, sd_b: float, n_b: int) -> float | None:
    if n_a < 2 or n_b < 2:
        return None
    pooled = math.sqrt(((n_a - 1) * sd_a ** 2 + (n_b - 1) * sd_b ** 2) / (n_a + n_b - 2))
    return (mean_a - mean_b) / pooled if pooled else None


def table_frame(cells: list[list[str]]):
    import pandas as pd

    if not cells or len(cells) < 2:
        return None
    width = max(len(r) for r in cells)
    grid = [list(r) + [""] * (width - len(r)) for r in cells]
    header = [h or f"col{i}" for i, h in enumerate(grid[0])]
    frame = pd.DataFrame(grid[1:], columns=pd.Index(header).astype(str))
    return frame


def numeric_cells(cells: list[list[str]]) -> list[float]:
    frame = table_frame(cells)
    if frame is None:
        return []
    values = []
    for column in frame.columns:
        for cell in frame[column].tolist():
            parsed = parse_number(cell)
            if parsed is not None:
                values.append(parsed.value)
    return values


def value_in_table(value: str, cells: list[list[str]] | None) -> bool | None:
    """Confirm an extracted numeric value is printed in the source table (None when not checkable)."""
    if not cells:
        return None
    number = parse_number(value)
    if number is None:
        return None
    printed = np.array(numeric_cells(cells), dtype=float)
    if printed.size == 0:
        return False
    return bool(np.any(np.isclose(printed, number.value, rtol=0, atol=1e-9)))
