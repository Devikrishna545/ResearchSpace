from __future__ import annotations
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.db.session import SessionLocal
from app.core.auth import owner_id
from app.modules.chat.orm.chat_session import ChatSession
from app.modules.chat.orm.citation import Citation
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.compare.orm.grounded import AnalysisJob, ComparisonFinding
from app.modules.notes.orm import Note
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.spaces.orm.space_memory import SpaceMemory
from app.modules.chat.orm.turn import Turn
from app.modules.chat.orm.verification_iteration import VerificationIteration
from app.modules.spaces.schemas import ResearchSpaceDTO
from app.modules.papers.service import PaperService
from app.db.retry import retry_sqlite_locked


class SpaceService:
    async def create(self,name):
        space=ResearchSpace(id=str(uuid4()),user_id=owner_id(),name=name)
        async with SessionLocal() as session:
            session.add(space)
            await session.commit()
        return ResearchSpaceDTO(id=space.id,name=space.name,status=space.status)

    async def list(self):
        async with SessionLocal() as session:
            rows=(await session.execute(select(ResearchSpace).where(ResearchSpace.user_id == owner_id()).order_by(ResearchSpace.created_at.desc()))).scalars().all()
            # Aggregate pin counts in one query so clients don't need an N+1 detail fetch.
            counts=dict((await session.execute(select(Pin.space_id,func.count(Pin.id)).join(ResearchSpace, ResearchSpace.id == Pin.space_id).where(ResearchSpace.user_id == owner_id()).group_by(Pin.space_id))).all())
        return [ResearchSpaceDTO(id=row.id,name=row.name,status=row.status,pin_count=counts.get(row.id,0),created_at=row.created_at,updated_at=row.updated_at) for row in rows]

    async def get(self,space_id):
        async with SessionLocal() as session:
            space=await session.scalar(select(ResearchSpace).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()))
            if not space: return None
            pins=(await session.execute(select(Paper).join(Pin,Pin.paper_id==Paper.id).where(Pin.space_id==space_id))).scalars().all()
            memory=await session.get(SpaceMemory,space_id)
        return {'id':space.id,'name':space.name,'status':space.status,'pins':[{'id':p.id,'title':p.title,'doi':p.doi,'arxiv_id':p.arxiv_id,'year':p.year,'venue':p.venue} for p in pins],'memory_summary':memory.rolling_summary if memory else ''}

    async def rename(self, space_id: str, name: str):
        async def op():
            async with SessionLocal() as session:
                space = await session.scalar(select(ResearchSpace).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()))
                if not space:
                    raise HTTPException(status_code=404, detail='space not found')
                space.name = name
                await session.commit()
                return ResearchSpaceDTO(id=space.id, name=space.name, status=space.status)
        return await retry_sqlite_locked(op)

    async def set_archived(self, space_id: str, archived: bool):
        async def op():
            async with SessionLocal() as session:
                space = await session.scalar(select(ResearchSpace).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()))
                if not space:
                    raise HTTPException(status_code=404, detail='space not found')
                space.status = 'archived' if archived else 'active'
                await session.commit()
                return ResearchSpaceDTO(id=space.id, name=space.name, status=space.status)
        return await retry_sqlite_locked(op)

    async def duplicate(self, space_id: str, copy_notes: bool = False, name: str | None = None):
        async def op():
            async with SessionLocal() as session:
                source = await session.scalar(select(ResearchSpace).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()))
                if not source:
                    raise HTTPException(status_code=404, detail='space not found')
                new_space = ResearchSpace(id=str(uuid4()), user_id=source.user_id, name=name or f'Copy of {source.name}', status='active')
                session.add(new_space)
                pins = (await session.execute(select(Pin.paper_id).where(Pin.space_id == space_id))).scalars().all()
                for paper_id in pins:
                    session.add(Pin(id=str(uuid4()), space_id=new_space.id, paper_id=paper_id))
                if copy_notes:
                    notes = (await session.execute(select(Note).where(Note.space_id == space_id))).scalars().all()
                    for note in notes:
                        session.add(Note(id=str(uuid4()), space_id=new_space.id, paper_id=note.paper_id, content=note.content, source=note.source))
                await session.commit()
                return new_space.id, list(pins)
        new_id, pins = await retry_sqlite_locked(op)
        paper_service = PaperService()
        for paper_id in pins:
            await paper_service._load_chunks(new_id, paper_id)
        return await self.get(new_id)

    async def delete(self, space_id: str):
        async def op():
            async with SessionLocal() as session:
                if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()).limit(1)):
                    raise HTTPException(status_code=404, detail='space not found')
                turn_ids = (await session.execute(select(Turn.id).where(Turn.space_id == space_id))).scalars().all()
                if turn_ids:
                    await session.execute(delete(VerificationIteration).where(VerificationIteration.turn_id.in_(turn_ids)))
                    await session.execute(delete(Citation).where(Citation.turn_id.in_(turn_ids)))
                await session.execute(delete(Turn).where(Turn.space_id == space_id))
                await session.execute(delete(ChatSession).where(ChatSession.space_id == space_id))
                await session.execute(delete(Note).where(Note.space_id == space_id))
                report_ids = select(ComparisonReport.id).where(ComparisonReport.space_id == space_id)
                await session.execute(delete(ComparisonFinding).where(ComparisonFinding.report_id.in_(report_ids)))
                await session.execute(delete(ComparisonReport).where(ComparisonReport.space_id == space_id))
                from app.modules.compare.grounded.jobs import stop_jobs
                stop_jobs((await session.execute(select(AnalysisJob.id).where(AnalysisJob.space_id == space_id))).scalars().all())
                await session.execute(delete(AnalysisJob).where(AnalysisJob.space_id == space_id))
                await session.execute(delete(SpaceMemory).where(SpaceMemory.space_id == space_id))
                await session.execute(delete(Pin).where(Pin.space_id == space_id))
                await session.execute(delete(ResearchSpace).where(ResearchSpace.id == space_id))
                await session.commit()
        await retry_sqlite_locked(op)
        from app.platform.retrieval import ingest_store
        ingest_store.chunks_by_space.pop(space_id, None)
        ingest_store.vector_store._data.pop(space_id, None)
        return {'id': space_id, 'deleted': True}

    async def search_content(self, space_id: str, q: str):
        async with SessionLocal() as session:
            if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()).limit(1)):
                raise HTTPException(status_code=404, detail='space not found')
            like = f'%{q.lower()}%'
            turns = (await session.execute(select(Turn).where(Turn.space_id == space_id, func.lower(Turn.content).like(like)).order_by(Turn.created_at.desc()))).scalars().all()
            notes = (await session.execute(select(Note).where(Note.space_id == space_id, func.lower(Note.content).like(like)).order_by(Note.created_at.desc()))).scalars().all()
        hits = []
        for turn in turns:
            hits.append({'type':'turn','id':turn.id,'session_id':turn.session_id,'snippet':self._snippet(turn.content,q),'created_at':turn.created_at.isoformat()})
        for note in notes:
            hits.append({'type':'note','id':note.id,'snippet':self._snippet(note.content,q),'created_at':note.created_at.isoformat()})
        # TODO: replace SQL LIKE search with FTS5 when schema migrations land.
        return hits

    async def list_turns(self, space_id: str, limit: int = 100):
        """Return conversation turns oldest-first, with citation counts for the UI."""
        async with SessionLocal() as session:
            if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()).limit(1)):
                raise HTTPException(status_code=404, detail='space not found')
            rows = (await session.execute(
                select(Turn).where(Turn.space_id == space_id).order_by(Turn.created_at.desc()).limit(limit)
            )).scalars().all()
            turn_ids = [t.id for t in rows]
            citations = {}
            if turn_ids:
                for turn_id, chunk_id, quote, paper_id, page, section in (await session.execute(
                    select(Citation.turn_id, Citation.chunk_id, Citation.quote, Citation.paper_id, Citation.page, Citation.section)
                    .where(Citation.turn_id.in_(turn_ids)).order_by(Citation.ordinal)
                )).all():
                    citations.setdefault(turn_id, []).append({'chunk_id': chunk_id, 'quote': quote, 'paper_id': paper_id, 'page': page, 'section': section})
        return [
            {'id': t.id, 'role': t.role, 'content': t.content, 'created_at': t.created_at.isoformat(), 'session_id': t.session_id, 'mentions': list(t.mentions or []),
             'citations': (t.answer_metadata or {}).get('citations', citations.get(t.id, [])),
             'verification': {key: value for key, value in t.answer_metadata.items() if key != 'citations'} if t.answer_metadata else None}
            for t in reversed(rows)
        ]

    def _snippet(self, text: str, q: str, width: int = 80) -> str:
        lower = text.lower(); idx = lower.find(q.lower()) if q else -1
        if idx < 0:
            return text[:width]
        start = max(0, idx - width // 2); end = min(len(text), idx + len(q) + width // 2)
        return text[start:end]
