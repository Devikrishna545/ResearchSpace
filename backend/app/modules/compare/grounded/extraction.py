"""Narrow typed-fact extraction: one paper, one fact type, only retrieved source excerpts."""

import logging
import re
from uuid import uuid4

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.fact_types import FACT_TYPES, FactType
from app.modules.compare.grounded.llm import GroundedLLM
from app.modules.compare.grounded.retrieval import Retriever
from app.modules.compare.grounded.validation import FactValidator
from app.modules.compare.orm.grounded import DocumentArtifact, EvidenceFact, PaperEvidenceBuild
from app.platform.llm.prompts.loader import PromptLoader
from app.db.retry import retry_sqlite_locked

logger = logging.getLogger(__name__)
EXTRACT_PROMPT_VERSION = "grounded-extract-v1"
EXCERPT_CHARS = 3500
CONTEXT_CHARS = 22000

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "value": {"type": "string"},
            "source_id": {"type": "string"},
            "quote": {"type": "string"},
            "owner": {"type": "string", "enum": ["this_paper", "cited_work", "unclear"]},
            "attributes": {"type": "object"},
        }, "required": ["value", "source_id", "quote", "owner"]}},
        "not_found": {"type": "boolean"},
    },
    "required": ["facts", "not_found"],
}


class JobCancelled(Exception):
    pass


def normalize_value(value: str) -> str:
    text = re.sub(r"[^\w\s.%+-]", " ", value.casefold())
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(the|a|an)\s+", "", text)


def excerpt_payload(artifacts: list[DocumentArtifact]) -> list[dict]:
    payload, used = [], 0
    for artifact in artifacts:
        text = artifact.text[:EXCERPT_CHARS]
        if used + len(text) > CONTEXT_CHARS:
            break
        used += len(text)
        payload.append({"source_id": artifact.id, "page": artifact.page_start, "section": artifact.section or "unknown",
                        "kind": artifact.kind, "status": artifact.extraction_status, "text": text})
    return payload


class FactExtractor:
    def __init__(self, llm: GroundedLLM, retriever: Retriever, validator: FactValidator, prompts: PromptLoader | None = None, check_cancel=None):
        self.llm = llm
        self.retriever = retriever
        self.validator = validator
        self.prompts = prompts or PromptLoader()
        self.check_cancel = check_cancel

    async def _cancel_point(self):
        if self.check_cancel and await self.check_cancel():
            raise JobCancelled()

    async def ensure_facts(self, build: PaperEvidenceBuild, artifacts: list[DocumentArtifact], paper_title: str,
                           fact_types: list[str] | None = None, progress=None) -> dict:
        """Extract and validate missing fact types for this build; reuse completed ones."""
        state = dict((build.doc_metadata or {}).get("extraction", {}))
        model = self.llm.tier.text_model
        for name in fact_types or list(FACT_TYPES):
            record = state.get(name) or {}
            # Facts are reused only if the same prompt and the same model produced them, so a
            # weak-tier extraction never becomes evidence for a stronger tier.
            if (record.get("prompt_version") == EXTRACT_PROMPT_VERSION and record.get("model") == model
                    and record.get("status") in {"done", "not_found", "partial"}):
                continue
            await self._cancel_point()
            fact_type = FACT_TYPES[name]
            try:
                status, count, parse_status = await self._extract_type(build, artifacts, paper_title, fact_type)
            except JobCancelled:
                raise
            except Exception:
                logger.warning("Extraction failed for %s/%s", build.paper_id, name, exc_info=True)
                status, count, parse_status = "failed", 0, norm.MODEL_ERROR
            state[name] = {"status": status, "count": count, "parse_status": parse_status, "prompt_version": EXTRACT_PROMPT_VERSION, "model": model}
            await self._save_state(build.id, state)
            if progress:
                await progress(f"{paper_title[:60]}: {fact_type.label} → {status}")
        return state

    async def _extract_type(self, build, artifacts, paper_title, fact_type: FactType):
        sources = await self.retriever.for_fact_type(artifacts, fact_type)
        if not sources:
            return "not_found", 0, "no_sources"
        system = self.prompts.render("grounded/extract_system.jinja")
        user = self.prompts.render("grounded/extract_user.jinja", fact_type=fact_type, paper_title=paper_title,
                                   excerpts=excerpt_payload(sources))
        result, model = await self.llm.call(
            purpose=f"extract:{fact_type.name}", prompt_version=EXTRACT_PROMPT_VERSION, system=system, user=user,
            list_names=("facts", fact_type.name, fact_type.label.lower()), text_key="value", schema=EXTRACTION_SCHEMA,
            paper_id=build.paper_id, max_tokens=4096,
        )
        if not result.usable:
            # Parser defects and model failures are recorded (llm_call_logs) and retried next run.
            return "failed", 0, result.status
        truncated = "truncated_output_salvaged" in result.notes
        by_id = {a.id: a for a in artifacts}
        candidates = []
        for item in result.items:
            value = norm.get_key(item, "value", "name", "text", fact_type.name)
            if value is None or not str(value).strip():
                continue
            source_id = norm.get_key(item, "source_id", "source", "id")
            if isinstance(source_id, list):
                source_id = source_id[0] if source_id else None
            attributes = norm.get_key(item, "attributes")
            owner = norm.verdict_word(norm.get_key(item, "owner"), ("this_paper", "cited_work", "unclear"), "unclear")
            artifact = by_id.get(str(source_id or "").strip())
            candidates.append({
                "value": str(value).strip()[:500], "source_id": str(source_id or "").strip(), "owner": owner,
                "quote": str(norm.get_key(item, "quote", "evidence", "excerpt") or "").strip()[:1500],
                "attributes": {k: v for k, v in attributes.items() if k in fact_type.attributes} if isinstance(attributes, dict) else {},
                "page": artifact.page_start if artifact else None, "section": artifact.section if artifact else None,
            })
        candidates = self._dedupe(candidates)
        if not candidates:
            await self._replace_facts(build, fact_type.name, [])
            return "not_found", 0, result.status
        rows = []
        for i, candidate in enumerate(candidates, start=1):
            rows.append(EvidenceFact(
                id=f"{build.paper_id}-v{build.version}-{fact_type.name}-{i:03d}-{uuid4().hex[:6]}", build_id=build.id,
                paper_id=build.paper_id, fact_type=fact_type.name, value=candidate["value"],
                normalized_value=normalize_value(candidate["value"])[:500], attributes=candidate["attributes"],
                source_ids=[candidate["source_id"]] if candidate["source_id"] else [], quote=candidate["quote"],
                page=candidate["page"], section=candidate["section"], extraction_status="candidate",
                provenance_validation="pending", type_validation="pending", ownership_validation="pending",
                dimension_validation="pending",
                validation_notes=[f"model_owner:{candidate['owner']}"], prompt_version=EXTRACT_PROMPT_VERSION,
                model_version=self.llm.model_version(model),
            ))
        await self._replace_facts(build, fact_type.name, rows)
        return ("partial" if truncated else "done"), len(rows), result.status

    async def validate_pending(self, build: PaperEvidenceBuild, artifacts: list[DocumentArtifact], paper_title: str, progress=None) -> set[str]:
        """Validate candidate facts type by type; already-validated facts are reused.

        Returns the fact types whose validation could not complete (model failure); their
        facts stay candidates and are retried on the next run.
        """
        by_id = {a.id: a for a in artifacts}
        pending = [f for f in await load_facts(build.id) if f.extraction_status == "candidate"]
        grouped: dict[str, list[EvidenceFact]] = {}
        for fact in pending:
            grouped.setdefault(fact.fact_type, []).append(fact)
        failed: set[str] = set()
        for name, facts in grouped.items():
            await self._cancel_point()
            await self.validator.validate(facts, by_id, FACT_TYPES[name], paper_title)
            await self._save_validation(facts)
            if any(f.extraction_status == "candidate" for f in facts):
                failed.add(name)
            if progress:
                validated = sum(f.extraction_status == "validated" for f in facts)
                await progress(f"{paper_title[:60]}: {FACT_TYPES[name].label} → {validated}/{len(facts)} validated")
        return failed

    async def _save_validation(self, facts: list[EvidenceFact]):
        async def op():
            async with SessionLocal() as session:
                for fact in facts:
                    await session.merge(fact)
                await session.commit()
        await retry_sqlite_locked(op)

    @staticmethod
    def _dedupe(candidates: list[dict]) -> list[dict]:
        seen: dict[tuple, dict] = {}
        for candidate in candidates:
            key = (normalize_value(candidate["value"]), candidate["source_id"])
            seen.setdefault(key, candidate)
        return list(seen.values())

    async def _replace_facts(self, build, fact_type: str, rows: list[EvidenceFact]):
        async def op():
            async with SessionLocal() as session:
                await session.execute(delete(EvidenceFact).where(EvidenceFact.build_id == build.id, EvidenceFact.fact_type == fact_type))
                session.add_all(rows)
                await session.commit()
        await retry_sqlite_locked(op)

    async def _save_state(self, build_id: str, state: dict):
        async def op():
            async with SessionLocal() as session:
                build = await session.get(PaperEvidenceBuild, build_id)
                if build is not None:
                    build.doc_metadata = {**(build.doc_metadata or {}), "extraction": state}
                    await session.commit()
        await retry_sqlite_locked(op)


async def load_facts(build_id: str) -> list[EvidenceFact]:
    async with SessionLocal() as session:
        return list((await session.execute(select(EvidenceFact).where(EvidenceFact.build_id == build_id)
                                           .order_by(EvidenceFact.fact_type, EvidenceFact.id))).scalars().all())
