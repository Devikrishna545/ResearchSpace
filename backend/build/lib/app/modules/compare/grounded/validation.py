"""Three independent fact checks: provenance (code), entity type (LLM), ownership + dimension (LLM).

A fact is usable for comparison only when all four statuses are 'pass'. Anything
else stays in the audit record and is excluded from deterministic comparison.
"""

import difflib
import re

from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.fact_types import FactType
from app.modules.compare.grounded.llm import GroundedLLM
from app.platform.llm.prompts.loader import PromptLoader

VALIDATE_PROMPT_VERSION = "grounded-validate-v1"
VALIDATION_BATCH = 5
FUZZY_QUOTE_RATIO = 0.92
VALUE_TOKEN_COVERAGE = 0.6
STOP = {"the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with", "by", "we", "our", "is", "are"}
NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)*")

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "answer": {"type": "string", "enum": ["yes", "no", "uncertain"]}, "reason": {"type": "string"},
    }, "required": ["id", "answer", "reason"]}}},
    "required": ["results"],
}
OWNERSHIP_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"},
        "belongs_to_this_paper": {"type": "string", "enum": ["yes", "no", "uncertain"]},
        "answers_dimension": {"type": "string", "enum": ["yes", "no", "uncertain"]},
        "reason": {"type": "string"},
    }, "required": ["id", "belongs_to_this_paper", "answers_dimension", "reason"]}}},
    "required": ["results"],
}


def canonical_text(text: str) -> str:
    text = (text or "").replace("\u00ad", "")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_in_source(quote: str, source: str) -> tuple[bool, str]:
    q, s = canonical_text(quote), canonical_text(source)
    if not q:
        return False, "empty_quote"
    if q in s:
        return True, "exact_quote"
    # PDF extraction drops or inserts spaces; the same characters in the same order still match.
    if len(q) >= 20 and re.sub(r"\s+", "", q) in re.sub(r"\s+", "", s):
        return True, "exact_quote_ignoring_whitespace"
    if len(q) < 20:
        return False, "quote_not_found"
    matcher = difflib.SequenceMatcher(None, s, q, autojunk=False)
    best = 0.0
    for block in matcher.get_matching_blocks():
        start = max(0, block.a - block.b)
        window = s[start:start + len(q)]
        best = max(best, difflib.SequenceMatcher(None, window, q, autojunk=False).ratio())
    return (True, f"fuzzy_quote:{best:.2f}") if best >= FUZZY_QUOTE_RATIO else (False, f"quote_not_found:{best:.2f}")


def value_in_source(value: str, quote: str, source: str) -> tuple[bool, str]:
    haystack = canonical_text(f"{quote} {source}")
    compact = re.sub(r"\s+", "", haystack)
    numbers = NUMBER.findall(value)
    if numbers and not all(n.replace(",", "") in compact.replace(",", "") for n in numbers):
        return False, "value_number_not_in_source"
    tokens = [t for t in re.findall(r"[a-z0-9]+", canonical_text(value)) if t not in STOP]
    if not tokens:
        return True, "value_has_no_content_tokens"
    present = sum(1 for t in tokens if t in haystack or t in compact)
    coverage = present / len(tokens)
    return (coverage >= VALUE_TOKEN_COVERAGE, f"value_token_coverage:{coverage:.2f}")


def context_window(source: str, quote: str, radius: int = 450) -> str:
    s = source or ""
    position = canonical_text(s).find(canonical_text(quote)[:60]) if quote else -1
    if position < 0:
        return s[: 2 * radius]
    # canonical_text collapses whitespace, so positions are approximate; widen the window.
    start = max(0, position - radius)
    return s[start:start + 2 * radius + len(quote)]


class FactValidator:
    def __init__(self, llm: GroundedLLM, prompts: PromptLoader | None = None):
        self.llm = llm
        self.prompts = prompts or PromptLoader()

    def check_provenance(self, fact, artifacts_by_id: dict) -> None:
        notes = list(fact.validation_notes or [])
        artifact = artifacts_by_id.get(fact.source_ids[0]) if fact.source_ids else None
        if artifact is None:
            fact.provenance_validation = "fail"
            notes.append("source_id_unresolved")
        elif artifact.paper_id != fact.paper_id or artifact.build_id != fact.build_id:
            fact.provenance_validation = "fail"
            notes.append("source_belongs_to_other_paper")
        else:
            ok_quote, quote_note = quote_in_source(fact.quote, artifact.text)
            ok_value, value_note = value_in_source(fact.value, fact.quote if ok_quote else "", artifact.text)
            notes.extend([quote_note, value_note])
            fact.provenance_validation = "pass" if ok_quote and ok_value else "fail"
            # Attributes feed code comparisons, so each must be stated in the source too.
            kept = {}
            for key, raw in (fact.attributes or {}).items():
                if raw is None or isinstance(raw, (dict, list)) or not str(raw).strip():
                    continue
                if value_in_source(str(raw), fact.quote if ok_quote else "", artifact.text)[0]:
                    kept[key] = raw
                else:
                    notes.append(f"attribute_dropped:{key}")
            fact.attributes = kept
            if artifact.extraction_status in {"candidate", "ocr_candidate"}:
                notes.append(f"source_is_{artifact.extraction_status}")
            if (artifact.section or "").startswith("Related Work"):
                fact.ownership_validation = "fail"
                notes.append("source_in_related_work")
        if "model_owner:cited_work" in notes:
            fact.ownership_validation = "fail"
        fact.validation_notes = notes

    async def validate(self, facts: list, artifacts_by_id: dict, fact_type: FactType, paper_title: str) -> None:
        for fact in facts:
            self.check_provenance(fact, artifacts_by_id)
        # LLM checks run only on facts that are really in the source; the rest are already rejected.
        eligible = [f for f in facts if f.provenance_validation == "pass" and f.ownership_validation != "fail"]
        # Small batches keep each validator answer short and a single failure local.
        for start in range(0, len(eligible), VALIDATION_BATCH):
            batch = eligible[start:start + VALIDATION_BATCH]
            items = [{"id": f.id, "value": f.value, "quote": f.quote,
                      "context": context_window(artifacts_by_id[f.source_ids[0]].text, f.quote),
                      "section": f.section or "unknown", "page": f.page} for f in batch]
            await self._type_check(batch, items, fact_type, paper_title)
            await self._ownership_check(batch, items, fact_type, paper_title)
        for fact in facts:
            if fact.type_validation == "pending" and fact.provenance_validation == "fail":
                fact.type_validation = "skipped"
            if fact.ownership_validation == "pending" and fact.provenance_validation == "fail":
                fact.ownership_validation = "skipped"
            if fact.dimension_validation == "pending" and (fact.provenance_validation == "fail" or fact.ownership_validation == "fail"):
                fact.dimension_validation = "skipped"
            if fact.type_validation == "pending" and fact.ownership_validation == "fail":
                fact.type_validation = "skipped"
            statuses = (fact.provenance_validation, fact.type_validation, fact.ownership_validation, fact.dimension_validation)
            if any(s == "fail" for s in statuses):
                fact.extraction_status = "rejected"
            elif any(s == "pending" for s in statuses):
                # A validator call failed: keep the fact retryable instead of calling it uncertain.
                fact.extraction_status = "candidate"
            elif all(s == "pass" for s in statuses):
                fact.extraction_status = "validated"
            else:
                fact.extraction_status = "uncertain"

    async def _type_check(self, facts, items, fact_type: FactType, paper_title: str):
        result, _ = await self.llm.call(
            purpose=f"validate_type:{fact_type.name}", prompt_version=VALIDATE_PROMPT_VERSION,
            system=self.prompts.render("grounded/validate_type.jinja"),
            user=self.prompts.render("grounded/validate_type_user.jinja", fact_type=fact_type, paper_title=paper_title, items=items),
            list_names=("results", "validations"), text_key="answer", schema=VERDICT_SCHEMA, paper_id=facts[0].paper_id,
        )
        if not result.usable or (not result.items and not result.not_found):
            for fact in facts:
                fact.validation_notes = [*fact.validation_notes, f"type_validator_failed:{result.status}"]
            return
        answers = {str(norm.get_key(i, "id") or ""): i for i in result.items}
        for fact in facts:
            item = answers.get(fact.id)
            answer = norm.verdict_word(norm.get_key(item, "answer", "is_type", "valid") if item else None, ("yes", "no", "uncertain"))
            fact.type_validation = {"yes": "pass", "no": "fail"}.get(answer, "uncertain")
            fact.validation_notes = [*fact.validation_notes, f"type:{answer}:{str(norm.get_key(item, 'reason') or '')[:200] if item else 'no_verdict'}"]

    async def _ownership_check(self, facts, items, fact_type: FactType, paper_title: str):
        result, _ = await self.llm.call(
            purpose=f"validate_ownership:{fact_type.name}", prompt_version=VALIDATE_PROMPT_VERSION,
            system=self.prompts.render("grounded/validate_ownership.jinja"),
            user=self.prompts.render("grounded/validate_ownership_user.jinja", fact_type=fact_type, paper_title=paper_title, items=items),
            list_names=("results", "validations"), text_key="belongs_to_this_paper", schema=OWNERSHIP_SCHEMA, paper_id=facts[0].paper_id,
        )
        if not result.usable or (not result.items and not result.not_found):
            for fact in facts:
                fact.validation_notes = [*fact.validation_notes, f"ownership_validator_failed:{result.status}"]
            return
        answers = {str(norm.get_key(i, "id") or ""): i for i in result.items}
        for fact in facts:
            item = answers.get(fact.id)
            owner = norm.verdict_word(norm.get_key(item, "belongs_to_this_paper", "owner") if item else None, ("yes", "no", "uncertain"))
            dimension = norm.verdict_word(norm.get_key(item, "answers_dimension", "relevant") if item else None, ("yes", "no", "uncertain"))
            fact.ownership_validation = {"yes": "pass", "no": "fail"}.get(owner, "uncertain")
            fact.dimension_validation = {"yes": "pass", "no": "fail"}.get(dimension, "uncertain")
            fact.validation_notes = [*fact.validation_notes, f"ownership:{owner}", f"dimension:{dimension}:{str(norm.get_key(item, 'reason') or '')[:200] if item else 'no_verdict'}"]
