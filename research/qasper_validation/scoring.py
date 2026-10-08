"""QASPER-compatible scoring, tested against the downloaded official evaluator."""

from __future__ import annotations

import re
import string
from collections import Counter

from chat_chunking.chunking import Chunk


def normalize(text: str) -> str:
    text = "".join(c for c in text.lower() if c not in string.punctuation)
    return " ".join(re.sub(r"\b(a|an|the)\b", " ", text).split())


def answer_f1(prediction: str, reference: str) -> float:
    predicted, expected = normalize(prediction).split(), normalize(reference).split()
    same = sum((Counter(predicted) & Counter(expected)).values())
    if not same:
        return 0.0
    precision, recall = same / len(predicted), same / len(expected)
    return 2 * precision * recall / (precision + recall)


def evidence_f1(predicted: list[str], expected: list[str]) -> float:
    if not predicted and not expected:
        return 1.0
    same = len(set(predicted) & set(expected))
    if not same:
        return 0.0
    precision, recall = same / len(predicted), same / len(expected)
    return 2 * precision * recall / (precision + recall)


def selected_units(contexts: list[Chunk], units: list[dict]) -> list[dict]:
    selected = []
    for unit in units:
        if any(c.doc_id == unit["doc_id"] and c.end > unit["start"] and c.start < unit["end"]
               for c in contexts):
            selected.append(unit)
    return selected


def score_case(case: dict, answer: str, contexts: list[Chunk], claims: list[dict],
               units: list[dict]) -> dict:
    predicted_answer = answer or "Unanswerable"
    citations = {cid for claim in claims for cid in claim["cited_chunk_ids"]}
    cited = [c for c in contexts if c.chunk_id in citations]
    evidence = selected_units(cited, units)
    retrieved = selected_units(contexts, units)
    predicted_ids = [u["unit_id"] for u in evidence]
    retrieved_ids = {u["unit_id"] for u in retrieved}
    refs = case["references"]
    # Missing mappings retain a distinct gold item and count as misses.
    gold_ids = [[uid or f"unmapped-{case['case_id']}-{i}-{j}"
                 for j, uid in enumerate(ref["evidence_units"])] for i, ref in enumerate(refs)]
    coverage = [len(retrieved_ids & set(ids)) / len(set(ids)) for ids in gold_ids if ids]
    valid_ids = {c.chunk_id for c in contexts}
    citation_ids = [cid for claim in claims for cid in claim["cited_chunk_ids"]]
    numerical = case.get("numeric_regex")
    numeric_pass = bool(re.search(numerical, answer, re.I)) if numerical else None
    if numerical:
        for forbidden in case.get("forbidden_numeric", []):
            if re.search(forbidden, answer, re.I):
                numeric_pass = False
    return {
        "answer_f1": max(answer_f1(predicted_answer, ref["answer"]) for ref in refs),
        "answer_exact_match": any(normalize(predicted_answer) == normalize(ref["answer"]) for ref in refs),
        "evidence_f1": max(evidence_f1([u["original"] for u in evidence], ref["evidence"]) for ref in refs),
        "text_evidence_f1": max(evidence_f1(
            [u["original"] for u in evidence if "FLOAT SELECTED" not in u["original"]],
            [e for e in ref["evidence"] if "FLOAT SELECTED" not in e]) for ref in refs),
        "retrieval_evidence_recall": max(coverage) if coverage else None,
        "predicted_evidence_unit_ids": predicted_ids,
        "citation_validity": sum(cid in valid_ids for cid in citation_ids) / len(citation_ids) if citation_ids else None,
        "citation_count": len(citation_ids), "claim_count": len(claims),
        "numeric_check_pass": numeric_pass,
        "abstained": not answer or normalize(answer) == "unanswerable",
        "unanswerable_reference_only": all(ref["type"] == "none" for ref in refs),
        "alignment_failure": bool(case.get("alignment_missing")),
    }


def validate_generated(value: object, allowed: set[str]) -> tuple[str, list[dict]]:
    if not isinstance(value, dict) or not isinstance(value.get("answer"), str):
        raise ValueError("Generated output lacks a short answer string.")
    raw = value.get("claims")
    if not isinstance(raw, list) or len(raw) > 5:
        raise ValueError("Invalid generated claim list.")
    claims = []
    for i, item in enumerate(raw, 1):
        if (not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip()
                or not isinstance(item.get("cited_chunk_ids"), list) or not item["cited_chunk_ids"]):
            raise ValueError("Malformed factual claim.")
        ids = item["cited_chunk_ids"]
        if not all(isinstance(cid, str) and cid in allowed for cid in ids):
            raise ValueError("Generated claim cites outside its supplied evidence.")
        claims.append({"claim_id": f"c{i}", "text": item["text"], "cited_chunk_ids": list(dict.fromkeys(ids))})
    if not claims and normalize(value["answer"]) not in {"", "unanswerable"}:
        raise ValueError("Non-abstaining answer has no supporting claim.")
    return value["answer"].strip(), claims
