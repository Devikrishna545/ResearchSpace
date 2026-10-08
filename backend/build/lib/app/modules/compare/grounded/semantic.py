"""Source-limited semantic comparison for dimensions that need interpretation.

The model sees only validated facts and their source excerpts. Code, not the model,
decides which papers a relation is about (from the cited fact ids) and enforces:
a commonality needs evidence from every paper it names, and a direct contradiction
needs comparable conditions; otherwise it is downgraded.
"""

import logging
import re

from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.deterministic import PaperEvidence
from app.modules.compare.grounded.fact_types import DIMENSION_LABELS, SEMANTIC_DIMENSIONS
from app.modules.compare.grounded.llm import GroundedLLM
from app.modules.compare.grounded.validation import context_window
from app.platform.llm.prompts.loader import PromptLoader
from app.modules.compare.schemas.grounded import (
    APPARENT_CONTRADICTION, COMMONALITY, DIFFERENCE, DIRECT_CONTRADICTION, INSUFFICIENT, INSUFFICIENT_EVIDENCE,
    NOT_COMPARABLE, Finding,
)

logger = logging.getLogger(__name__)
SEMANTIC_PROMPT_VERSION = "grounded-semantic-v1"
RELATIONS = ("commonality_candidate", "difference", "direct_contradiction_candidate", "apparent_contradiction",
             "not_directly_comparable", "insufficient_evidence")
KIND_BY_RELATION = {"commonality_candidate": COMMONALITY, "difference": DIFFERENCE,
                    "direct_contradiction_candidate": DIRECT_CONTRADICTION, "apparent_contradiction": APPARENT_CONTRADICTION,
                    "not_directly_comparable": NOT_COMPARABLE, "insufficient_evidence": INSUFFICIENT}
SCHEMA = {
    "type": "object",
    "properties": {"relations": {"type": "array", "items": {"type": "object", "properties": {
        "relation": {"type": "string", "enum": list(RELATIONS)},
        "statement": {"type": "string"},
        "fact_ids": {"type": "array", "items": {"type": "string"}},
        "conditions": {"type": "string"},
    }, "required": ["relation", "statement", "fact_ids"]}}},
    "required": ["relations"],
}


class SemanticComparator:
    def __init__(self, llm: GroundedLLM, prompts: PromptLoader | None = None):
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.audit: list[dict] = []
        self._counter = 0

    def _id(self) -> str:
        self._counter += 1
        return f"sem-{self._counter:03d}"

    async def compare(self, papers: list[PaperEvidence], comparable_pairs: set[frozenset], check_cancel=None) -> list[Finding]:
        findings = []
        for dimension in SEMANTIC_DIMENSIONS:
            if check_cancel and await check_cancel():
                from app.modules.compare.grounded.extraction import JobCancelled
                raise JobCancelled()
            with_facts = [p for p in papers if p.facts_for(dimension)]
            missing = [p for p in papers if not p.facts_for(dimension)]
            if dimension != "method" and missing:
                findings.append(Finding(finding_id=self._id(), kind=INSUFFICIENT, dimension=dimension,
                                        statement=f"Insufficient evidence: no validated {DIMENSION_LABELS[dimension].lower()} for "
                                                  f"{', '.join(p.short for p in missing)}.",
                                        paper_ids=[p.paper_id for p in missing], evidence_status=INSUFFICIENT_EVIDENCE,
                                        verification_status="policy", display_status="coverage"))
            if len(with_facts) < 2:
                continue
            findings.extend(await self._dimension(dimension, with_facts, comparable_pairs, all_papers=papers))
        return findings

    async def _dimension(self, dimension: str, papers: list[PaperEvidence], comparable_pairs: set[frozenset],
                         all_papers: list[PaperEvidence] | None = None) -> list[Finding]:
        everyone = all_papers or papers
        by_label = {p.label.upper(): p.paper_id for p in everyone}
        facts_by_id, payload = {}, []
        for paper in papers:
            items = []
            for fact in paper.facts_for(dimension):
                source = paper.artifacts_by_id.get(fact.source_ids[0]) if fact.source_ids else None
                facts_by_id[fact.id] = (paper, fact)
                items.append({"fact_id": fact.id, "type": fact.fact_type, "value": fact.value, "quote": fact.quote,
                              "page": fact.page, "excerpt": context_window(source.text, fact.quote, 300) if source else ""})
            payload.append({"label": paper.label, "title": paper.title, "facts": items})
        result, _ = await self.llm.call(
            purpose=f"semantic:{dimension}", prompt_version=SEMANTIC_PROMPT_VERSION,
            system=self.prompts.render("grounded/semantic_system.jinja"),
            user=self.prompts.render("grounded/semantic_user.jinja", dimension=DIMENSION_LABELS[dimension], papers=payload),
            list_names=("relations", "comparisons"), text_key="statement", schema=SCHEMA,
        )
        if not result.usable:
            self.audit.append({"dimension": dimension, "status": result.status, "notes": result.notes})
            return []
        findings = []
        for item in result.items:
            relation = norm.verdict_word(norm.get_key(item, "relation", "type", "label"), RELATIONS, "insufficient_evidence")
            statement = str(norm.get_key(item, "statement", "text", "description") or "").strip()
            cited = norm.get_key(item, "fact_ids", "facts", "evidence")
            cited = [str(c) for c in (cited if isinstance(cited, list) else [cited] if cited else [])]
            known = [c for c in cited if c in facts_by_id]
            dropped = [c for c in cited if c not in facts_by_id]
            if not statement:
                continue
            paper_ids = list(dict.fromkeys(facts_by_id[c][0].paper_id for c in known))
            kind = KIND_BY_RELATION[relation]
            reason = None
            if dropped:
                self.audit.append({"dimension": dimension, "statement": statement, "dropped_fact_ids": dropped})
            if kind == INSUFFICIENT:
                continue
            if kind in {COMMONALITY, DIFFERENCE, DIRECT_CONTRADICTION, APPARENT_CONTRADICTION, NOT_COMPARABLE} and len(paper_ids) < 2:
                # A cross-paper relation needs direct support from every named paper.
                self.audit.append({"dimension": dimension, "statement": statement, "policy": "needs_evidence_from_each_paper",
                                   "cited_papers": paper_ids})
                continue
            if kind == DIRECT_CONTRADICTION:
                pairs = {frozenset(p) for p in _pairs(paper_ids)}
                if not pairs <= comparable_pairs:
                    kind = APPARENT_CONTRADICTION
                    reason = ("Downgraded from direct contradiction: the papers are not shown to share a dataset or "
                              "population, so conditions may differ. " + str(norm.get_key(item, "conditions") or "")).strip()
            findings.append(Finding(
                finding_id=self._id(), kind=kind, dimension=dimension, statement=statement, paper_ids=paper_ids,
                fact_ids=known, source_ids=list(dict.fromkeys(s for c in known for s in facts_by_id[c][1].source_ids)),
                evidence_status="pending", verification_status="pending", display_status="candidate",
                basis="interpretation", reason=reason,
                computed={"relation": relation, "required_papers": named_papers(statement, by_label, [p.paper_id for p in everyone], paper_ids)},
            ))
        return findings


ALL_PAPERS = re.compile(r"\b(both|all|neither|none of|each of|every)\b", re.I)
LABEL = re.compile(r"\bP(\d{1,2})\b")


def named_papers(statement: str, by_label: dict[str, str], all_ids: list[str], cited: list[str]) -> list[str]:
    """Papers a statement claims to cover: explicit P-labels, all papers for "both/all/neither", plus cited ones."""
    named = {by_label[f"P{n}"] for n in LABEL.findall(statement) if f"P{n}" in by_label}
    if ALL_PAPERS.search(statement):
        named |= set(all_ids)
    return sorted(named | set(cited))


def _pairs(ids: list[str]):
    return [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]
