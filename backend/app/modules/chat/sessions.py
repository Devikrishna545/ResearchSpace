"""Chat sessions: named conversation threads inside a research space."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select

from app.core.auth import owner_id
from app.db.session import SessionLocal
from app.core.exceptions import LLMUnavailableError
from app.modules.chat.orm.chat_session import ChatSession
from app.modules.chat.orm.citation import Citation
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.chat.orm.turn import Turn
from app.modules.chat.orm.verification_iteration import VerificationIteration
from app.modules.chat.schemas.chat import ConversationTurnDTO, ReferencedSessionDTO
from app.db.retry import retry_sqlite_locked

DEFAULT_TITLE = "New chat"
AUTO_TITLE_LIMIT = 60
# Compression keeps the newest turns verbatim and summarises everything older.
COMPRESS_KEEP_RECENT = 4
COMPRESS_MIN_TURNS = 8
COMPRESS_BATCH = 12
REFERENCE_TURNS = 4
REFERENCE_TURN_CHARS = 400


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def title_from_question(question: str) -> str:
    text = " ".join(question.split())
    if not text:
        return DEFAULT_TITLE
    return text if len(text) <= AUTO_TITLE_LIMIT else text[: AUTO_TITLE_LIMIT - 1].rstrip() + "\u2026"


def strip_mentions(question: str, titles: list[str]) -> str:
    """Replace `@Title` tokens with the plain title so retrieval sees topical words, not markup."""
    cleaned = question
    for title in sorted(titles, key=len, reverse=True):
        cleaned = re.sub(r"@" + re.escape(title), f'"{title}"', cleaned)
    return " ".join(cleaned.split()) or question


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


_CITATION_MARKER = re.compile(r"\s?\[[^\]\s]{6,}\]")


def _preview(text: str | None) -> str | None:
    """Message text for list previews, without inline `[chunk-id]` citation markers."""
    return _CITATION_MARKER.sub("", text or "").strip() or None


def _snippet(text: str, q: str, width: int = 90) -> str:
    text = _preview(text) or ""
    idx = text.lower().find(q.lower())
    if idx < 0:
        return text[:width]
    start = max(0, idx - width // 2)
    end = min(len(text), idx + len(q) + width // 2)
    return ("\u2026" if start else "") + text[start:end] + ("\u2026" if end < len(text) else "")


def session_dto(row: ChatSession, turn_count: int = 0, last_message: str | None = None, match: str | None = None) -> dict:
    return {
        "id": row.id,
        "space_id": row.space_id,
        "title": row.title,
        "pinned": bool(row.pinned),
        "archived": bool(row.archived),
        "summary": row.summary,
        "summary_turn_count": row.summary_turn_count or 0,
        "summary_updated_at": _iso(row.summary_updated_at),
        "turn_count": turn_count,
        "last_message": (_preview(last_message) or "")[:160] or None,
        "match": match,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


class ChatSessionService:
    async def _owned(self, db, session_id: str) -> ChatSession:
        row = await db.scalar(
            select(ChatSession).join(ResearchSpace, ResearchSpace.id == ChatSession.space_id)
            .where(ChatSession.id == session_id, ResearchSpace.user_id == owner_id())
        )
        if not row:
            raise HTTPException(404, "Resource not found")
        return row

    async def _ensure_space(self, db, space_id: str) -> None:
        if not await db.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()).limit(1)):
            raise HTTPException(404, "Resource not found")

    async def _stats(self, db, session_ids: list[str]) -> tuple[dict[str, int], dict[str, str]]:
        if not session_ids:
            return {}, {}
        counts = dict((await db.execute(
            select(Turn.session_id, func.count(Turn.id)).where(Turn.session_id.in_(session_ids)).group_by(Turn.session_id)
        )).all())
        latest = (
            select(Turn.session_id, func.max(Turn.created_at).label("at"))
            .where(Turn.session_id.in_(session_ids)).group_by(Turn.session_id).subquery()
        )
        last = dict((await db.execute(
            select(Turn.session_id, Turn.content).join(latest, (latest.c.session_id == Turn.session_id) & (latest.c.at == Turn.created_at))
        )).all())
        return counts, last

    async def list(self, space_id: str, status: str = "active", q: str | None = None, limit: int = 200) -> list[dict]:
        async with SessionLocal() as db:
            await self._ensure_space(db, space_id)
            stmt = select(ChatSession).where(ChatSession.space_id == space_id)
            if status == "active":
                stmt = stmt.where(ChatSession.archived.is_(False))
            elif status == "archived":
                stmt = stmt.where(ChatSession.archived.is_(True))
            query = (q or "").strip()
            if query:
                like = f"%{query.lower()}%"
                content_match = select(Turn.session_id).where(Turn.space_id == space_id, func.lower(Turn.content).like(like))
                stmt = stmt.where(or_(func.lower(ChatSession.title).like(like), ChatSession.id.in_(content_match)))
            rows = (await db.execute(
                stmt.order_by(ChatSession.pinned.desc(), ChatSession.updated_at.desc()).limit(limit)
            )).scalars().all()
            ids = [row.id for row in rows]
            counts, last = await self._stats(db, ids)
            matches: dict[str, str] = {}
            if query and ids:
                like = f"%{query.lower()}%"
                for session_id, content in (await db.execute(
                    select(Turn.session_id, Turn.content)
                    .where(Turn.session_id.in_(ids), func.lower(Turn.content).like(like))
                    .order_by(Turn.created_at.desc())
                )).all():
                    matches.setdefault(session_id, _snippet(content, query))
        return [session_dto(row, counts.get(row.id, 0), last.get(row.id), matches.get(row.id)) for row in rows]

    async def create(self, space_id: str, title: str | None = None) -> dict:
        async def op():
            async with SessionLocal() as db:
                await self._ensure_space(db, space_id)
                stamp = now_utc()
                row = ChatSession(id=str(uuid4()), space_id=space_id, title=title or DEFAULT_TITLE, pinned=False, archived=False,
                                  summary_turn_count=0, created_at=stamp, updated_at=stamp)
                db.add(row)
                await db.commit()
                return session_dto(row)
        return await retry_sqlite_locked(op)

    async def get(self, session_id: str) -> dict:
        async with SessionLocal() as db:
            row = await self._owned(db, session_id)
            counts, last = await self._stats(db, [row.id])
        return session_dto(row, counts.get(row.id, 0), last.get(row.id))

    async def update(self, session_id: str, title: str | None = None, pinned: bool | None = None, archived: bool | None = None) -> dict:
        async def op():
            async with SessionLocal() as db:
                row = await self._owned(db, session_id)
                if title is not None:
                    row.title = title
                if pinned is not None:
                    row.pinned = pinned
                if archived is not None:
                    row.archived = archived
                await db.commit()
                return row
        row = await retry_sqlite_locked(op)
        return await self.get(row.id)

    async def delete(self, session_id: str) -> dict:
        async def op():
            async with SessionLocal() as db:
                row = await self._owned(db, session_id)
                turn_ids = (await db.execute(select(Turn.id).where(Turn.session_id == row.id))).scalars().all()
                if turn_ids:
                    await db.execute(delete(VerificationIteration).where(VerificationIteration.turn_id.in_(turn_ids)))
                    await db.execute(delete(Citation).where(Citation.turn_id.in_(turn_ids)))
                    await db.execute(delete(Turn).where(Turn.id.in_(turn_ids)))
                await db.execute(delete(ChatSession).where(ChatSession.id == row.id))
                await db.commit()
        await retry_sqlite_locked(op)
        return {"id": session_id, "deleted": True}

    async def list_turns(self, session_id: str, limit: int = 200) -> list[dict]:
        """Turns of one session, oldest first, with citations and mention links."""
        async with SessionLocal() as db:
            row = await self._owned(db, session_id)
            turns = (await db.execute(
                select(Turn).where(Turn.session_id == row.id).order_by(Turn.created_at.desc()).limit(limit)
            )).scalars().all()
            turn_ids = [t.id for t in turns]
            citations: dict[str, list[dict]] = {}
            if turn_ids:
                for c in (await db.execute(select(Citation).where(Citation.turn_id.in_(turn_ids)).order_by(Citation.ordinal))).scalars().all():
                    citations.setdefault(c.turn_id, []).append({
                        "chunk_id": c.chunk_id, "quote": c.quote, "claim_text": c.claim_text, "paper_id": c.paper_id,
                        "page": c.page, "section": c.section, "match_score": c.match_score,
                    })
        return [
            {"id": t.id, "role": t.role, "content": t.content, "created_at": _iso(t.created_at), "session_id": t.session_id,
             "mentions": list(t.mentions or []),
             "citations": (t.answer_metadata or {}).get("citations", citations.get(t.id, [])),
             "verification": {key: value for key, value in t.answer_metadata.items() if key != "citations"} if t.answer_metadata else None}
            for t in reversed(turns)
        ]

    async def resolve_for_chat(self, space_id: str, session_id: str | None) -> ChatSession:
        """Return the session a new question belongs to.

        Callers that do not send a session (older clients) continue their most recent
        active conversation, matching the pre-session single-thread behaviour.
        """
        async with SessionLocal() as db:
            await self._ensure_space(db, space_id)
            if session_id:
                row = await self._owned(db, session_id)
                if row.space_id != space_id:
                    raise HTTPException(404, "Resource not found")
                if row.archived:
                    raise HTTPException(409, "This chat is archived. Unarchive it to continue the conversation.")
                return row
            row = await db.scalar(
                select(ChatSession).where(ChatSession.space_id == space_id, ChatSession.archived.is_(False))
                .order_by(ChatSession.updated_at.desc()).limit(1)
            )
        if row:
            return row
        created = await self.create(space_id)
        async with SessionLocal() as db:
            return await self._owned(db, created["id"])

    async def mention_context(self, space_id: str, session_ids: list[str], exclude: str | None = None) -> list[ReferencedSessionDTO]:
        wanted = [sid for sid in dict.fromkeys(session_ids) if sid and sid != exclude]
        if not wanted:
            return []
        async with SessionLocal() as db:
            rows = (await db.execute(
                select(ChatSession).join(ResearchSpace, ResearchSpace.id == ChatSession.space_id)
                .where(ChatSession.id.in_(wanted), ChatSession.space_id == space_id, ResearchSpace.user_id == owner_id())
            )).scalars().all()
            by_id = {row.id: row for row in rows}
            refs = []
            for sid in wanted:
                row = by_id.get(sid)
                if not row:
                    continue
                recent = (await db.execute(
                    select(Turn).where(Turn.session_id == sid).order_by(Turn.created_at.desc()).limit(REFERENCE_TURNS)
                )).scalars().all()
                refs.append(ReferencedSessionDTO(
                    session_id=row.id, title=row.title, summary=row.summary,
                    recent_turns=[ConversationTurnDTO(role=t.role, content=t.content[:REFERENCE_TURN_CHARS], created_at=_iso(t.created_at)) for t in reversed(recent)],
                ))
        return refs

    async def record_activity(self, db, session_id: str, question: str) -> None:
        """Bump recency and give an untitled session a title from its first question (caller commits)."""
        row = await db.get(ChatSession, session_id)
        if not row:
            return
        if row.title == DEFAULT_TITLE:
            row.title = title_from_question(question)
        row.updated_at = now_utc()

    async def compress(self, session_id: str, agent, keep_recent: int = COMPRESS_KEEP_RECENT, batch_size: int = COMPRESS_BATCH) -> dict:
        """Summarise all but the newest turns, reusing any still-valid earlier summary."""
        async with SessionLocal() as db:
            row = await self._owned(db, session_id)
            rows = (await db.execute(select(Turn).where(Turn.session_id == row.id).order_by(Turn.created_at))).scalars().all()
            prior_summary, prior_count = row.summary, row.summary_turn_count or 0
        # Citation markers are opaque chunk ids; they only add noise to a readable summary.
        turns = [SimpleNamespace(id=t.id, role=t.role, content=_preview(t.content) or "") for t in rows]
        if len(turns) < COMPRESS_MIN_TURNS:
            raise HTTPException(409, f"Conversation needs at least {COMPRESS_MIN_TURNS} messages before it can be compressed.")
        target = len(turns) - keep_recent
        start = prior_count if prior_summary and 0 < prior_count <= target else 0
        summary = prior_summary if start else None
        try:
            for index in range(start, target, batch_size):
                summary = await agent.summarize(turns[index:min(index + batch_size, target)], summary)
        except LLMUnavailableError as exc:
            raise HTTPException(503, "The local model is unavailable, so the conversation could not be compressed.") from exc
        stamp = now_utc()

        async def op():
            async with SessionLocal() as db:
                current = await self._owned(db, session_id)
                current.summary = (summary or "").strip() or None
                current.summary_turn_count = target
                current.summary_updated_at = stamp
                await db.commit()
        await retry_sqlite_locked(op)
        return await self.get(session_id)
