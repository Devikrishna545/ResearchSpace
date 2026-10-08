"""Independent reference-span/rubric metrics and calibration-only threshold sweeps."""

from __future__ import annotations

import math
import re
from collections import Counter
from statistics import mean, median

import numpy as np

from .chunking import Chunk
from .corpus import Document


def bind_cases(documents: list[Document], specification: dict) -> list[dict]:
    cases = []
    for case in specification["cases"]:
        groups = []
        for item in case["evidence"]:
            matches = [doc for doc in documents if item["title"].lower() in doc.title.lower()]
            if len(matches) != 1:
                raise ValueError(f"{case['id']}: source title is absent or ambiguous: {item['title']}")
            doc = matches[0]
            spans = [{"doc_id": doc.doc_id, "start": m.start(), "end": m.end()}
                     for m in re.finditer(item["pattern"], doc.text, re.I | re.S)]
            if not spans:
                raise ValueError(f"{case['id']}: reference evidence not found: {item['pattern']}")
            groups.append(spans)
        cases.append({**case, "gold_groups": groups})
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate question IDs.")
    return cases


def covered(span: dict, contexts: list[Chunk]) -> bool:
    intervals = sorted((max(c.start, span["start"]), min(c.end, span["end"]))
                       for c in contexts if c.doc_id == span["doc_id"] and
                       c.end > span["start"] and c.start < span["end"])
    cursor = span["start"]
    for left, right in intervals:
        if left > cursor:
            return False
        cursor = max(cursor, right)
    return cursor >= span["end"]


def relevance_metrics(case: dict, contexts: list[Chunk]) -> dict:
    groups = case["gold_groups"]
    if not groups:
        return {"evidence_recall": None, "mrr": None, "context_precision": None,
                "paper_recall": None}
    hits = [any(covered(span, contexts) for span in group) for group in groups]
    relevant = [any(c.doc_id == span["doc_id"] and c.end > span["start"] and c.start < span["end"]
                    for group in groups for span in group) for c in contexts]
    expected_docs = {span["doc_id"] for group in groups for span in group}
    return {
        "evidence_recall": mean(hits),
        "mrr": next((1 / (i + 1) for i, hit in enumerate(relevant) if hit), 0),
        "context_precision": mean(relevant) if relevant else 0,
        "paper_recall": len(expected_docs & {c.doc_id for c in contexts}) / len(expected_docs),
    }


def validate_answer(parsed: object, contexts: list[Chunk]) -> list[dict]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("claims"), list):
        raise ValueError("Answer does not contain a claims array.")
    if len(parsed["claims"]) > 5:
        raise ValueError("More than five generated claims.")
    claims = []
    for i, item in enumerate(parsed["claims"], 1):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError("Empty or malformed claim.")
        ids = item.get("cited_chunk_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(cid, str) for cid in ids):
            raise ValueError("Malformed citation list.")
        claims.append({"claim_id": f"c{i}", "text": item["text"],
                       "cited_chunk_ids": list(dict.fromkeys(ids))})
    return claims


def normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def answer_metrics(case: dict, claims: list[dict], contexts: list[Chunk]) -> dict:
    text = " ".join(claim["text"] for claim in claims)
    concept_hits = [bool(re.search(pattern, text, re.I | re.S)) for pattern in case["concepts"]]
    forbidden_hits = [bool(re.search(pattern, text, re.I | re.S)) for pattern in case.get("forbidden", [])]
    ids = {c.chunk_id for c in contexts}
    citations = [cid for claim in claims for cid in claim["cited_chunk_ids"]]
    if case.get("unanswerable"):
        correct = not claims
        coverage = None
    else:
        coverage = mean(concept_hits) if concept_hits else 0.0
        correct = bool(claims) and all(concept_hits) and not any(forbidden_hits)
    cited = [c for c in contexts if c.chunk_id in citations]
    gold_covered = relevance_metrics(case, cited)["evidence_recall"]
    return {
        "answer_rubric_coverage": coverage, "full_rubric_match": correct,
        "concept_hits": concept_hits, "forbidden_hits": forbidden_hits,
        "abstained": not claims, "claim_count": len(claims),
        "citation_count": len(citations),
        "citation_valid_count": sum(cid in ids for cid in citations),
        "citation_validity": mean(cid in ids for cid in citations) if citations else None,
        "cited_gold_coverage": gold_covered,
        "reference_supported_answer": bool(correct and claims and gold_covered == 1.0
                                           and all(cid in ids for cid in citations)),
    }


def review_metrics(claims: list[dict], contexts: list[Chunk], parsed: object,
                   similarities: dict[str, float]) -> dict:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("claims"), list):
        raise ValueError("Reviewer output has no claims array.")
    score = parsed.get("overall_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Invalid reviewer score.")
    findings = parsed["claims"]
    counts = Counter(row.get("claim_id") for row in findings if isinstance(row, dict))
    expected = {claim["claim_id"] for claim in claims}
    if set(counts) != expected or any(n != 1 for n in counts.values()):
        raise ValueError("Reviewer did not address every claim exactly once.")
    by_id = {row["claim_id"]: row for row in findings}
    context_by_id = {c.chunk_id: c for c in contexts}
    statuses = {"SUPPORTED", "PARTIAL", "UNSUPPORTED", "CONTRADICTED", "MISCITED"}
    supported = 0
    quotes_verified = 0
    detail = []
    for claim in claims:
        row = by_id[claim["claim_id"]]
        if row.get("status") not in statuses:
            raise ValueError("Invalid reviewer claim status.")
        quote = row.get("evidence_quote")
        if not isinstance(quote, str):
            raise ValueError("Reviewer quote must be text.")
        quote_valid = bool(quote.strip()) and any(
            cid in context_by_id and normalized(quote) in normalized(context_by_id[cid].text)
            for cid in claim["cited_chunk_ids"]
        )
        supported += row["status"] == "SUPPORTED"
        quotes_verified += quote_valid
        detail.append({**row, "quote_provenance_valid": quote_valid,
                       "min_citation_similarity": similarities.get(claim["claim_id"], -1)})
    return {
        "review_score": float(score), "review_verdict": parsed.get("verdict"),
        "review_claims": detail, "supported_claims": supported,
        "supported_claim_rate": supported / len(claims) if claims else 0,
        "quote_provenance_rate": quotes_verified / len(claims) if claims else 0,
        "min_citation_similarity": min(similarities.values(), default=-1),
    }


def passes(row: dict, review_threshold: float, similarity_threshold: float) -> bool:
    return bool(
        not row.get("error") and row.get("claim_count", 0)
        and row.get("review_verdict") == "APPROVED"
        and row.get("review_score", 0) >= review_threshold
        and row.get("supported_claim_rate") == 1
        and row.get("citation_validity") == 1
        and row.get("quote_provenance_rate") == 1
        and row.get("min_citation_similarity", -1) >= similarity_threshold
    )


def summary(rows: list[dict]) -> dict:
    positive = [r for r in rows if not r["unanswerable"]]
    negative = [r for r in rows if r["unanswerable"]]

    def average(key: str, selected: list[dict]) -> float | None:
        values = [r[key] for r in selected if r.get(key) is not None]
        return mean(values) if values else None

    claims = sum(r.get("claim_count", 0) for r in rows)
    elapsed = [r["answer_seconds"] + r.get("review_seconds", 0) + r.get("retrieval_seconds", 0)
               for r in rows if r.get("answer_seconds") is not None]
    return {
        "attempts": len(rows), "errors": sum(bool(r.get("error")) for r in rows),
        "answerable_questions": len(positive), "unanswerable_questions": len(negative),
        "evidence_recall": average("evidence_recall", positive),
        "mrr": average("mrr", positive),
        "context_precision": average("context_precision", positive),
        "answer_rubric_coverage": average("answer_rubric_coverage", positive),
        "full_rubric_match_rate": mean(bool(r.get("full_rubric_match")) for r in positive) if positive else None,
        "reference_supported_answer_rate": mean(bool(r.get("reference_supported_answer")) for r in positive) if positive else None,
        "correct_abstention_rate": mean(bool(r.get("abstained")) and not r.get("error") for r in negative) if negative else None,
        "citation_validity": sum(r.get("citation_valid_count", 0) for r in rows) /
            max(1, sum(r.get("citation_count", 0) for r in rows)),
        "claim_support_rate": sum(r.get("supported_claims", 0) for r in rows) / max(1, claims),
        "claims": claims, "strict_acceptance_rate": mean(passes(r, 0.9, 0.65) for r in rows) if rows else None,
        "median_answer_seconds": median([r["answer_seconds"] for r in rows if r.get("answer_seconds") is not None]) if elapsed else None,
        "median_review_seconds": median([r.get("review_seconds", 0) for r in rows]) if rows else None,
        "median_model_path_seconds": median(elapsed) if elapsed else None,
        "p95_model_path_seconds": float(np.percentile(elapsed, 95)) if elapsed else None,
    }


def threshold_sweep(rows: list[dict]) -> tuple[list[dict], dict]:
    calibration = [r for r in rows if r["split"] == "calibration"]
    results = []
    for review_threshold in (0.8, 0.85, 0.9, 0.95):
        for similarity_threshold in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
            accepted = [r for r in calibration if passes(r, review_threshold, similarity_threshold)]
            true = sum(bool(r.get("reference_supported_answer")) for r in accepted)
            results.append({"review_threshold": review_threshold, "similarity_threshold": similarity_threshold,
                            "accepted": len(accepted), "reference_supported": true,
                            "proxy_precision": true / len(accepted) if accepted else None,
                            "coverage": len(accepted) / len(calibration) if calibration else 0})
    eligible = [r for r in results if r["accepted"] >= 3 and r["proxy_precision"] == 1.0]
    if eligible:
        chosen = max(eligible, key=lambda r: (r["accepted"], r["review_threshold"], r["similarity_threshold"]))
        chosen = {**chosen, "selection": "maximum calibration coverage with zero proxy false acceptances and >=3 accepts"}
    else:
        chosen = {"review_threshold": 0.9, "similarity_threshold": 0.65,
                  "selection": "insufficient calibration support; retain reference thresholds, not a calibrated recommendation"}
    return results, chosen
