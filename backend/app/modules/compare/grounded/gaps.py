"""Candidate-gap analysis over validated facts, generated only after comparison."""

import re

from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.deterministic import PaperEvidence
from app.modules.compare.grounded.fact_types import GAP_CATEGORIES
from app.modules.compare.grounded.llm import GroundedLLM
from app.platform.llm.prompts.loader import PromptLoader
from app.modules.compare.schemas.grounded import CANDIDATE_GAP, Finding

GAP_PROMPT_VERSION = "grounded-gaps-v1"
GAP_FACT_TYPES = ("limitation", "future_work", "dataset", "population", "method", "baseline", "metric", "sample_size",
                  "train_test_split", "research_question", "assumption")
ALL_PAPERS = re.compile(r"\b(neither|both|all|none of|each of|across)\b", re.I)
COVERAGE_NOTE = "Based only on the selected papers; not a claim about the wider literature."
SCHEMA = {
    "type": "object",
    "properties": {
        "gaps": {"type": "array", "items": {"type": "object", "properties": {
            "description": {"type": "string"},
            "category": {"type": "string", "enum": list(GAP_CATEGORIES)},
            "fact_ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["description", "category", "fact_ids"]}},
        "no_gaps_reason": {"type": "string"},
    },
    "required": ["gaps"],
}


class GapAnalyzer:
    def __init__(self, llm: GroundedLLM, prompts: PromptLoader | None = None):
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.audit: list[dict] = []
        self.empty_reason: str | None = None

    async def candidates(self, papers: list[PaperEvidence], shown_findings: list[Finding]) -> list[Finding]:
        facts_by_id = {}
        payload = []
        for paper in papers:
            items = []
            for fact in paper.validated:
                if fact.fact_type in GAP_FACT_TYPES:
                    facts_by_id[fact.id] = (paper, fact)
                    items.append({"fact_id": fact.id, "type": fact.fact_type, "value": fact.value, "quote": fact.quote, "page": fact.page})
            payload.append({"label": paper.label, "title": paper.title, "facts": items})
        if not facts_by_id:
            self.empty_reason = "No validated facts were available to ground candidate gaps."
            return []
        result, _ = await self.llm.call(
            purpose="gaps", prompt_version=GAP_PROMPT_VERSION,
            system=self.prompts.render("grounded/gaps_system.jinja", categories=GAP_CATEGORIES),
            user=self.prompts.render("grounded/gaps_user.jinja", papers=payload,
                                     comparisons=[f.statement for f in shown_findings][:40]),
            list_names=("gaps", "candidate_gaps"), text_key="description", schema=SCHEMA, max_tokens=3072,
        )
        if not result.usable:
            self.empty_reason = f"Gap generation failed ({result.status}); no gaps are shown. This is not evidence that no gaps exist."
            return []
        out = []
        seen: set[str] = set()
        for index, item in enumerate(result.items, start=1):
            description = str(norm.get_key(item, "description", "gap", "text") or "").strip()
            key = re.sub(r"[^a-z0-9]+", " ", description.casefold()).strip()
            if key in seen:
                continue
            seen.add(key)
            category = norm.verdict_word(norm.get_key(item, "category", "type"), GAP_CATEGORIES, "")
            cited = norm.get_key(item, "fact_ids", "evidence", "facts")
            if isinstance(cited, dict):  # {"P1": [...], "P2": [...]} paper-label evidence maps
                cited = [x for v in cited.values() for x in (v if isinstance(v, list) else [v])]
            cited = [str(c) for c in (cited if isinstance(cited, list) else [cited] if cited else [])]
            known = [c for c in cited if c in facts_by_id]
            if not description or not category:
                self.audit.append({"description": description, "policy": "missing description or unknown category"})
                continue
            if not known:
                self.audit.append({"description": description, "policy": "no validated evidence cited"})
                continue
            by_paper: dict[str, list[str]] = {}
            for fact_id in known:
                by_paper.setdefault(facts_by_id[fact_id][0].paper_id, []).append(fact_id)
            required = [p.paper_id for p in papers] if ALL_PAPERS.search(description) else list(by_paper)
            out.append(Finding(
                finding_id=f"gap-{index:03d}", kind=CANDIDATE_GAP, dimension=category, category=category,
                statement=description, paper_ids=list(by_paper), fact_ids=known,
                source_ids=list(dict.fromkeys(s for c in known for s in facts_by_id[c][1].source_ids)),
                computed={"evidence_by_paper": by_paper, "required_papers": required}, evidence_status="pending",
                verification_status="pending", display_status="candidate", basis="interpretation",
                coverage_note=COVERAGE_NOTE,
            ))
        if not out:
            reason = str(norm.get_key(result.parsed, "no_gaps_reason") or "").strip() if isinstance(result.parsed, dict) else ""
            self.empty_reason = reason or "No candidate gap had validated evidence from each relevant paper."
        return out
