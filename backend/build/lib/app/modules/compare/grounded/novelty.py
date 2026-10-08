"""Authorized local literature corpus and conservative novelty-candidate assessment.

A pair of papers cannot establish novelty. Labels are relative to the available
corpus only, always shipped with a coverage disclosure, and never "proven novel".
"""

import logging
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.auth import owner_id
from app.db.session import SessionLocal
from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.evidence import document_embedding_text, query_embedding_text
from app.modules.compare.grounded.llm import GroundedLLM
from app.modules.compare.grounded.retrieval import cosine
from app.modules.compare.orm.grounded import LiteratureCorpusItem
from app.modules.papers.orm.paper import Paper
from app.platform.llm.prompts.loader import PromptLoader
from app.modules.compare.schemas.grounded import Finding
from app.db.retry import retry_sqlite_locked

logger = logging.getLogger(__name__)
NOVELTY_PROMPT_VERSION = "grounded-novelty-v1"
LABEL_BY_VERDICT = {"addressed": "already_addressed_in_retrieved_work", "partially_addressed": "partially_addressed_in_retrieved_work",
                    "not_addressed": "possibly_novel_in_available_corpus"}
SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["addressed", "partially_addressed", "not_addressed", "cannot_tell"]},
                   "item_ids": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}},
    "required": ["verdict", "item_ids", "reason"],
}
SEARCH_LIMITATIONS = [
    "Only the items in this local corpus were searched; relevant work outside it is not considered.",
    "Items are compared mostly by title and abstract; full texts are not searched unless they were uploaded.",
    "Retrieval ranks items by embedding similarity, which can miss work phrased differently.",
    "A model judged whether retrieved items address each gap; this is a candidate assessment, not proof.",
]


def dedupe_key(title: str, doi: str | None) -> str:
    if doi:
        return "doi:" + doi.strip().casefold()
    return "title:" + re.sub(r"[^a-z0-9]+", " ", (title or "").casefold()).strip()


class CorpusService:
    def __init__(self, embedder, embed_model: str):
        self.embedder = embedder
        self.embed_model = embed_model

    async def add_library_papers(self, corpus_id: str, paper_ids: list[str], permission: str, note: str | None, field: str | None) -> dict:
        async with SessionLocal() as session:
            papers = (await session.execute(select(Paper).where(Paper.id.in_(paper_ids), Paper.owner_id == owner_id()))).scalars().all()
        found = {p.id for p in papers}
        missing = [pid for pid in paper_ids if pid not in found]
        if missing:
            raise HTTPException(404, f"paper not found: {', '.join(missing)}")
        items = [{"paper_id": p.id, "title": p.title, "abstract": p.abstract, "year": p.year, "doi": p.doi, "field": field,
                  "item_metadata": {"venue": p.venue, "authors": (p.authors or [])[:10], "source": p.source},
                  "permission": permission, "permission_note": note} for p in papers]
        return await self._add(corpus_id, items)

    async def add_metadata(self, corpus_id: str, items: list[dict]) -> dict:
        return await self._add(corpus_id, [{**i, "paper_id": None, "item_metadata": {}} for i in items])

    async def _add(self, corpus_id: str, items: list[dict]) -> dict:
        texts = [document_embedding_text(i["title"], i.get("abstract") or i["title"]) for i in items]
        try:
            vectors = await self.embedder(texts, self.embed_model) if texts else []
        except Exception:
            logger.warning("Corpus embedding failed", exc_info=True)
            vectors = [None] * len(items)
        added, skipped = 0, 0
        owner = owner_id()
        for item, vector in zip(items, vectors):
            key = dedupe_key(item["title"], item.get("doi"))

            async def op(item=item, vector=vector, key=key):
                async with SessionLocal() as session:
                    exists = await session.scalar(select(LiteratureCorpusItem.id).where(
                        LiteratureCorpusItem.owner_id == owner, LiteratureCorpusItem.corpus_id == corpus_id,
                        LiteratureCorpusItem.dedupe_key == key))
                    if exists:
                        return False
                    session.add(LiteratureCorpusItem(
                        id=str(uuid4()), owner_id=owner, corpus_id=corpus_id, dedupe_key=key, paper_id=item.get("paper_id"),
                        title=item["title"], abstract=item.get("abstract"), year=item.get("year"), doi=item.get("doi"),
                        field=item.get("field"), item_metadata=item.get("item_metadata") or {}, artifact_refs=[],
                        permission=item["permission"], permission_note=item.get("permission_note"),
                        embedding_json=vector or None, embed_model=self.embed_model if vector else None))
                    try:
                        await session.commit()
                    except IntegrityError:
                        await session.rollback()
                        return False
                    return True
            if await retry_sqlite_locked(op):
                added += 1
            else:
                skipped += 1
        return {"added": added, "skipped_duplicates": skipped, "corpus": await self.coverage(corpus_id)}

    async def items(self, corpus_id: str) -> list[LiteratureCorpusItem]:
        async with SessionLocal() as session:
            return list((await session.execute(select(LiteratureCorpusItem).where(
                LiteratureCorpusItem.owner_id == owner_id(), LiteratureCorpusItem.corpus_id == corpus_id)
                .order_by(LiteratureCorpusItem.added_at.desc()))).scalars().all())

    async def remove(self, item_id: str) -> None:
        async with SessionLocal() as session:
            result = await session.execute(delete(LiteratureCorpusItem).where(
                LiteratureCorpusItem.id == item_id, LiteratureCorpusItem.owner_id == owner_id()))
            await session.commit()
        if not result.rowcount:
            raise HTTPException(404, "corpus item not found")

    async def coverage(self, corpus_id: str, items: list | None = None, excluded: int = 0) -> dict:
        items = items if items is not None else await self.items(corpus_id)
        years = [i.year for i in items if i.year]
        permissions: dict[str, int] = {}
        fields: dict[str, int] = {}
        for item in items:
            permissions[item.permission] = permissions.get(item.permission, 0) + 1
            if item.field:
                fields[item.field] = fields.get(item.field, 0) + 1
        return {"corpus_id": corpus_id, "size": len(items), "excluded_compared_papers": excluded,
                "with_abstract": sum(1 for i in items if i.abstract), "embedded": sum(1 for i in items if i.embed_model == self.embed_model),
                "year_range": [min(years), max(years)] if years else None, "fields": fields, "permissions": permissions,
                "search_limitations": SEARCH_LIMITATIONS}


class NoveltyAssessor:
    def __init__(self, llm: GroundedLLM, corpus: CorpusService, min_corpus: int, top_k: int, prompts: PromptLoader | None = None):
        self.llm = llm
        self.corpus = corpus
        self.min_corpus = min_corpus
        self.top_k = top_k
        self.prompts = prompts or PromptLoader()

    async def assess(self, corpus_id: str, gaps: list[Finding], compared_paper_ids: list[str], compared_dois: set[str]) -> dict:
        all_items = await self.corpus.items(corpus_id)
        items = [i for i in all_items if i.paper_id not in compared_paper_ids and (not i.doi or i.doi.casefold() not in compared_dois)]
        coverage = await self.corpus.coverage(corpus_id, items, excluded=len(all_items) - len(items))
        usable = [i for i in items if i.embedding_json and i.embed_model == self.corpus.embed_model]
        if len(usable) < self.min_corpus:
            for gap in gaps:
                gap.novelty = {"label": "insufficient_literature_coverage",
                               "reason": f"Only {len(usable)} searchable corpus items (minimum {self.min_corpus})."}
            return {"ran": True, "coverage": coverage, "status": "insufficient_literature_coverage"}
        for gap in gaps:
            gap.novelty = await self._assess_gap(gap, usable)
        return {"ran": True, "coverage": coverage, "status": "assessed"}

    async def _assess_gap(self, gap: Finding, items: list) -> dict:
        try:
            query = (await self.corpus.embedder([query_embedding_text(gap.statement)], self.corpus.embed_model))[0]
        except Exception:
            return {"label": "novelty_not_assessed", "reason": "Embedding the gap failed."}
        ranked = sorted(((cosine(query, i.embedding_json) or 0.0, i) for i in items), key=lambda x: -x[0])[: self.top_k]
        retrieved = [{"item_id": i.id, "title": i.title, "year": i.year, "abstract": (i.abstract or "")[:900],
                      "similarity": round(score, 4)} for score, i in ranked]
        result, _ = await self.llm.call(
            purpose="novelty", prompt_version=NOVELTY_PROMPT_VERSION,
            system=self.prompts.render("grounded/novelty_system.jinja"),
            user=self.prompts.render("grounded/novelty_user.jinja", gap=gap.statement, items=retrieved),
            single_object=True, schema=SCHEMA,
        )
        base = {"retrieved": len(retrieved), "top_items": retrieved[:5]}
        if not result.items:
            return {**base, "label": "novelty_not_assessed", "reason": f"Assessment failed ({result.status})."}
        item = result.items[0]
        verdict = norm.verdict_word(norm.get_key(item, "verdict"), ("addressed", "partially_addressed", "not_addressed", "cannot_tell"), "cannot_tell")
        cited = norm.get_key(item, "item_ids") or []
        valid_ids = {r["item_id"] for r in retrieved}
        cited = [str(c) for c in (cited if isinstance(cited, list) else [cited]) if str(c) in valid_ids]
        reason = str(norm.get_key(item, "reason") or "").strip()
        if verdict == "cannot_tell":
            return {**base, "label": "novelty_not_assessed", "reason": reason or "The model could not tell."}
        if verdict in {"addressed", "partially_addressed"} and not cited:
            return {**base, "label": "novelty_not_assessed", "reason": "The assessment did not cite retrieved work, so it was discarded."}
        return {**base, "label": LABEL_BY_VERDICT[verdict], "reason": reason,
                "cited_items": [r for r in retrieved if r["item_id"] in cited]}
