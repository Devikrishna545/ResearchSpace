"""Assemble the immutable, page-linked grounded report snapshot."""

from app.modules.compare.grounded.deterministic import PaperEvidence
from app.modules.compare.grounded.fact_types import FACT_TYPES
from app.modules.compare.schemas.grounded import (
    APPARENT_CONTRADICTION, CANDIDATE_GAP, COMMONALITY, DIFFERENCE, DIRECT_CONTRADICTION, NOT_COMPARABLE,
    NUMERIC_COMPARISON, STATISTICAL_CHECK, Finding,
)

SECTION_KINDS = {
    "commonalities": {COMMONALITY},
    "differences": {DIFFERENCE, NOT_COMPARABLE},
    "contradictions": {DIRECT_CONTRADICTION, APPARENT_CONTRADICTION},
    "numerical": {NUMERIC_COMPARISON, STATISTICAL_CHECK},
    "candidate_gaps": {CANDIDATE_GAP},
}
SUMMARY_TYPES = ("research_question", "method", "dataset", "metric")
RELEASE_GATE = ("Findings are candidates or evidence-backed interpretations until faculty-reviewed evaluation "
                "thresholds are met; they are not verified academic conclusions.")
EXCERPT_LIMIT = 2000


def fact_dict(fact) -> dict:
    return {
        "fact_id": fact.id, "paper_id": fact.paper_id, "fact_type": fact.fact_type, "label": FACT_TYPES[fact.fact_type].label,
        "value": fact.value, "normalized_value": fact.normalized_value, "attributes": fact.attributes or {},
        "source_ids": fact.source_ids or [], "quote": fact.quote, "page": fact.page, "section": fact.section,
        "extraction_status": fact.extraction_status, "provenance_validation": fact.provenance_validation,
        "type_validation": fact.type_validation, "ownership_validation": fact.ownership_validation,
        "dimension_validation": fact.dimension_validation, "validation_notes": fact.validation_notes or [],
        "prompt_version": fact.prompt_version, "model_version": fact.model_version,
    }


def artifact_dict(artifact) -> dict:
    return {
        "source_id": artifact.id, "paper_id": artifact.paper_id, "kind": artifact.kind, "page": artifact.page_start,
        "section": artifact.section, "label": artifact.label, "caption": artifact.caption,
        "text": artifact.text[:EXCERPT_LIMIT], "truncated": len(artifact.text) > EXCERPT_LIMIT, "cells": artifact.cells,
        "has_image": bool(artifact.image_path), "extraction_status": artifact.extraction_status,
        "quality_flags": artifact.quality_flags or [],
    }


def build_report(papers: list[PaperEvidence], matrix: list[dict], findings: list[Finding], *, gaps_empty_reason: str | None,
                 novelty: dict, warnings: list[str], model_metadata: dict, tier: dict, audit: dict) -> dict:
    shown = [f for f in findings if f.display_status in {"shown", "shown_with_caveat"}]
    sections = {name: [f.model_dump(mode="json") for f in shown if f.kind in kinds] for name, kinds in SECTION_KINDS.items()}
    cited_sources = {s for f in shown for s in f.source_ids}
    ledger_sources = {s for p in papers for f in p.validated for s in f.source_ids}
    appendix = {}
    for paper in papers:
        for source_id in sorted(cited_sources | ledger_sources):
            artifact = paper.artifacts_by_id.get(source_id)
            if artifact is not None:
                appendix[source_id] = artifact_dict(artifact)
    paper_entries = []
    for paper in papers:
        build = paper.build
        summary = {t: [{"fact_id": f.id, "value": f.value, "page": f.page} for f in paper.validated if f.fact_type == t]
                   for t in SUMMARY_TYPES}
        paper_entries.append({
            "paper_id": paper.paper_id, "label": paper.label, "title": paper.title, "summary": summary,
            "build": {"build_id": build.id, "version": build.version, "text_source": build.text_source,
                      "page_count": build.page_count, "scanned": build.scanned, "quality_flags": build.quality_flags or [],
                      "parser_version": build.parser_version, "embed_model": build.embed_model,
                      "detected_metadata": (build.doc_metadata or {}).get("detected", {})},
            "extraction": paper.extraction_state,
            "fact_counts": {"validated": len(paper.validated),
                            "rejected": sum(f.extraction_status == "rejected" for f in paper.facts),
                            "uncertain": sum(f.extraction_status == "uncertain" for f in paper.facts)},
        })
    withheld = [f.model_dump(mode="json") for f in findings if f.display_status == "withheld"]
    coverage = [f.model_dump(mode="json") for f in findings if f.display_status == "coverage"]
    return {
        "report_kind": "grounded",
        "papers": paper_entries,
        "paper_labels": {p.label: p.title for p in papers},
        "paper_label_ids": {p.label: p.paper_id for p in papers},
        "builds": {p.paper_id: p.build.id for p in papers},
        "evidence_ledger": {p.paper_id: [fact_dict(f) for f in p.validated] for p in papers},
        "audit_record": {p.paper_id: [fact_dict(f) for f in p.facts if f.extraction_status != "validated"] for p in papers},
        "deterministic_table": matrix,
        "sections": sections,
        "candidate_gaps_empty_reason": None if sections["candidate_gaps"] else (gaps_empty_reason or "No candidate gap survived verification."),
        "novelty": novelty,
        "withheld": withheld,
        "withheld_count": len(withheld),
        "coverage": {"insufficient": coverage, "warnings": warnings,
                     "papers": {p.paper_id: {"quality_flags": p.build.quality_flags or [], "text_source": p.build.text_source,
                                             "scanned": p.build.scanned} for p in papers}},
        "evidence_appendix": appendix,
        "internal_audit": audit,
        "model_metadata": model_metadata,
        "tier": tier,
        "release_gate": RELEASE_GATE,
        "status_legend": {
            "DIRECTLY_EVIDENCED": "Stated in the cited source spans of every named paper.",
            "NUMERICALLY_VERIFIED": "Calculated or checked in code from source values.",
            "EVIDENCE_BACKED_INTERPRETATION": "An interpretation the verifier found supported by the cited spans.",
            "PARTIALLY_SUPPORTED": "Only part of the statement is supported; see the limitation note.",
        },
    }
