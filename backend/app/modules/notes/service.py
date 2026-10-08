from __future__ import annotations
import logging
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.modules.notes.agent import NotesAgent
from app.db.session import SessionLocal
from app.core.auth import owner_id
from app.platform.llm.model_router import ModelRouter
from app.platform.llm.ollama_client import get_ollama_client
from app.modules.papers.orm.chunk import Chunk
from app.modules.notes.orm import Note
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.chat.schemas.chat import EvidenceSet, ScoredChunk
from app.db.retry import retry_sqlite_locked

logger = logging.getLogger(__name__)

SECTION_CUES = ("abstract", "introduction", "method", "experiment", "evaluation", "dataset", "result", "limitation", "conclusion", "future")


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _select_informative_chunks(chunks: list[ScoredChunk], char_budget: int = 9000) -> list[ScoredChunk]:
    """Bound the note prompt to the model context window.

    Keeps the opening chunks (title/abstract) then prefers chunks whose text looks
    like a substantive section. Passing
    every chunk overflows num_ctx and makes small local models emit degenerate notes.
    """
    selected, seen = [], set()
    for chunk in chunks[:2]:
        selected.append(chunk)
        seen.add(chunk.chunk_id)
    for chunk in chunks:
        haystack = f"{chunk.section or ''}\n{chunk.text}".lower()
        if chunk.chunk_id not in seen and any(cue in haystack for cue in SECTION_CUES):
            selected.append(chunk)
            seen.add(chunk.chunk_id)
    for chunk in chunks:
        if chunk.chunk_id not in seen:
            selected.append(chunk)
            seen.add(chunk.chunk_id)

    packed, used = [], 0
    for chunk in selected:
        if used + len(chunk.text) > char_budget:
            break
        packed.append(chunk)
        used += len(chunk.text)
    return packed or chunks[:2]


class NoteService:
    def __init__(self, agent: NotesAgent | None = None, settings=None):
        if agent is not None:
            self.agent = agent
        elif settings is not None:
            llm = get_ollama_client()
            self.agent = NotesAgent(llm=llm, router=ModelRouter(settings))
        else:
            self.agent = NotesAgent()

    async def auto_generate(self, space_id: str, paper_id: str, refresh: bool = False) -> Note:
        async with SessionLocal() as session:
            await self._validate_space_paper(session, space_id, paper_id)
            existing = await session.scalar(select(Note).where(Note.space_id == space_id, Note.paper_id == paper_id, Note.source == "auto").limit(1))
            if existing and not refresh:
                return existing
            paper = await session.get(Paper, paper_id)
            rows = (await session.execute(select(Chunk).where(Chunk.paper_id == paper_id).order_by(Chunk.ordinal))).scalars().all()
        chunks = [ScoredChunk(chunk_id=row.id, paper_id=row.paper_id, text=row.text, section=row.section, page=row.page, source=paper.title if paper else None, metadata={"ordinal": row.ordinal}) for row in rows]
        chunks = _select_informative_chunks(chunks)
        try:
            structured = await self.agent.generate(paper.title if paper else paper_id, chunks)
        except Exception:
            logger.warning("Auto note generation degraded to deterministic fallback", exc_info=True)
            structured = NotesAgent()._fallback(paper.title if paper else paper_id, chunks)
        content = self._render_markdown(paper.title if paper else paper_id, structured)

        async def op():
            async with SessionLocal() as session:
                note = await session.scalar(select(Note).where(Note.space_id == space_id, Note.paper_id == paper_id, Note.source == "auto").limit(1))
                if note:
                    note.content = content
                else:
                    note = Note(id=str(uuid4()), space_id=space_id, paper_id=paper_id, content=content, source="auto")
                    session.add(note)
                await session.commit()
                return note
        return await retry_sqlite_locked(op)

    async def create(
        self,
        space_id: str,
        paper_id: str | None,
        content: str,
        chunk_id: str | None = None,
        anchor_quote: str | None = None,
        anchor_start: int | None = None,
        anchor_end: int | None = None,
        color: str | None = None,
    ) -> Note:
        async def op():
            async with SessionLocal() as session:
                if not content and not anchor_quote:
                    raise HTTPException(status_code=422, detail="content or anchor_quote is required")
                target_paper_id = paper_id
                if target_paper_id:
                    await self._validate_space_paper(session, space_id, target_paper_id)
                elif not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()).limit(1)):
                    raise HTTPException(status_code=404, detail="space not found")
                if chunk_id:
                    chunk = await session.get(Chunk, chunk_id)
                    if not chunk:
                        raise HTTPException(status_code=422, detail="chunk not found")
                    if target_paper_id and chunk.paper_id != target_paper_id:
                        raise HTTPException(status_code=422, detail="chunk does not belong to paper")
                    if target_paper_id is None:
                        target_paper_id = chunk.paper_id
                        await self._validate_space_paper(session, space_id, target_paper_id)
                    if anchor_start is not None and anchor_end is not None and anchor_end < anchor_start:
                        raise HTTPException(status_code=422, detail="anchor_end must be >= anchor_start")
                note = Note(
                    id=str(uuid4()),
                    space_id=space_id,
                    paper_id=target_paper_id,
                    content=content,
                    source="manual",
                    chunk_id=chunk_id,
                    anchor_quote=anchor_quote,
                    anchor_start=anchor_start,
                    anchor_end=anchor_end,
                    color=color,
                )
                session.add(note)
                await session.commit()
                return note
        return await retry_sqlite_locked(op)

    async def update(self, note_id: str, content: str) -> Note:
        async def op():
            async with SessionLocal() as session:
                note = await session.scalar(select(Note).join(ResearchSpace, Note.space_id == ResearchSpace.id).where(Note.id == note_id, ResearchSpace.user_id == owner_id()))
                if not note:
                    raise HTTPException(status_code=404, detail="note not found")
                note.content = content
                await session.commit()
                return note
        return await retry_sqlite_locked(op)

    async def delete(self, note_id: str) -> None:
        async def op():
            async with SessionLocal() as session:
                note = await session.scalar(select(Note).join(ResearchSpace, Note.space_id == ResearchSpace.id).where(Note.id == note_id, ResearchSpace.user_id == owner_id()))
                if not note:
                    raise HTTPException(status_code=404, detail="note not found")
                await session.delete(note)
                await session.commit()
        await retry_sqlite_locked(op)

    async def list(self, space_id: str, paper_id: str | None = None) -> list[Note]:
        async with SessionLocal() as session:
            if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()).limit(1)):
                raise HTTPException(status_code=404, detail="space not found")
            stmt = select(Note).where(Note.space_id == space_id)
            if paper_id is not None:
                if not await session.scalar(select(Pin.id).where(Pin.space_id == space_id, Pin.paper_id == paper_id).limit(1)):
                    raise HTTPException(status_code=404, detail="paper not pinned to space")
                stmt = stmt.where(Note.paper_id == paper_id)
            return (await session.execute(stmt.order_by(Note.updated_at.desc()))).scalars().all()

    async def get(self, note_id: str) -> Note:
        async with SessionLocal() as session:
            note = await session.scalar(select(Note).join(ResearchSpace, Note.space_id == ResearchSpace.id).where(Note.id == note_id, ResearchSpace.user_id == owner_id()))
            if not note:
                raise HTTPException(status_code=404, detail="note not found")
            return note

    async def search_as_chunks(self, space_id: str, question: str, limit: int = 3) -> list[ScoredChunk]:
        q = _tokens(question)
        if not q:
            return []
        async with SessionLocal() as session:
            rows = (await session.execute(select(Note, Paper.title).outerjoin(Paper, Paper.id == Note.paper_id).join(ResearchSpace, ResearchSpace.id == Note.space_id).where(Note.space_id == space_id, ResearchSpace.user_id == owner_id()))).all()
        hits = []
        for note, title in rows:
            text = note.content or note.anchor_quote or ""
            terms = _tokens(text)
            score = len(q & terms) / max(len(q), 1)
            if score <= 0:
                continue
            source = f"Note: {title or 'space'}"
            hits.append(ScoredChunk(chunk_id=f"note-{note.id}", paper_id=note.paper_id, text=text, score=score, source=source, metadata={"note_id": note.id, "title": title, "source": note.source, "anchor_quote": note.anchor_quote}))
        return sorted(hits, key=lambda c: c.score, reverse=True)[:limit]

    async def annotations(self, space_id: str, paper_id: str) -> list[Note]:
        async with SessionLocal() as session:
            await self._validate_space_paper(session, space_id, paper_id)
            stmt = (
                select(Note)
                .join(Chunk, Chunk.id == Note.chunk_id)
                .where(Note.space_id == space_id, Note.paper_id == paper_id, Note.chunk_id.is_not(None))
                .order_by(Chunk.ordinal, Note.anchor_start)
            )
            return (await session.execute(stmt)).scalars().all()

    async def augment_evidence_with_notes(self, space_id: str, question: str, evidence: EvidenceSet, limit: int = 3) -> EvidenceSet:
        notes = await self.search_as_chunks(space_id, question, limit=limit)
        if not notes:
            return evidence
        by_id = {chunk.chunk_id: chunk for chunk in evidence.chunks}
        merged = list(evidence.chunks)
        for note in notes:
            if note.chunk_id not in by_id:
                merged.append(note)
        return evidence.model_copy(update={"chunks": merged})

    async def _validate_space_paper(self, session, space_id: str, paper_id: str) -> None:
        if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()).limit(1)):
            raise HTTPException(status_code=404, detail="space not found")
        if not await session.scalar(select(Paper.id).where(Paper.id == paper_id, Paper.owner_id == owner_id()).limit(1)):
            raise HTTPException(status_code=404, detail="paper not found")
        if not await session.scalar(select(Pin.id).where(Pin.space_id == space_id, Pin.paper_id == paper_id).limit(1)):
            raise HTTPException(status_code=404, detail="paper not pinned to space")

    def _render_markdown(self, paper_title: str, note: dict) -> str:
        lines = [f"# Notes: {paper_title}", "", "## Summary", note.get("summary") or "", "", "## Key contributions"]
        contributions = note.get("key_contributions") or []
        lines.extend([f"- {item}" for item in contributions] or ["- "])
        for key, heading in (("methodology", "Methodology"), ("results", "Results"), ("limitations", "Limitations"), ("relevance", "Relevance")):
            lines.extend(["", f"## {heading}", note.get(key) or ""])
        return "\n".join(lines).strip() + "\n"
