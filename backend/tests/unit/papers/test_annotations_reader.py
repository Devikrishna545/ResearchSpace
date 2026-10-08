import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.session import configure_sqlite_pragmas
from app.db.models import Base
from app.modules.papers.orm.chunk import Chunk
from app.modules.notes.orm import Note
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.auth.orm.user import User
from app.modules.papers import api as papers
from app.modules.notes import service as note_service
from app.modules.papers import service as paper_service
from app.modules.notes.service import NoteService


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = configure_sqlite_pragmas(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reader.db'}", future=True))
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        session.add(User(id="test-owner", email="owner@example.com", is_admin=False))
        await session.commit()
    monkeypatch.setattr(note_service, "SessionLocal", session_local, raising=False)
    monkeypatch.setattr(paper_service, "SessionLocal", session_local, raising=False)
    monkeypatch.setattr(papers, "SessionLocal", session_local, raising=False)
    yield session_local
    await engine.dispose()


async def seed(db):
    async with db() as session:
        session.add(ResearchSpace(id="s1", user_id="test-owner", name="Space"))
        session.add(ResearchSpace(id="s2", user_id="test-owner", name="Other"))
        session.add(Paper(id="p1", owner_id="test-owner", title="Paper One", authors=["Ada"], year=2024, venue="Venue", raw_payload={"url": "https://example.test"}, source="test"))
        session.add(Paper(id="p2", owner_id="test-owner", title="Paper Two", authors=[], raw_payload={}, source="test"))
        await session.flush()
        session.add(Pin(id="pin1", space_id="s1", paper_id="p1"))
        session.add(Chunk(id="p1-0", paper_id="p1", ordinal=0, section="Intro", page=1, text="Alpha beta gamma delta"))
        session.add(Chunk(id="p1-1", paper_id="p1", ordinal=1, section="Methods", page=2, text="Methods text"))
        session.add(Chunk(id="p2-0", paper_id="p2", ordinal=0, text="Other paper text"))
        await session.commit()


async def test_paper_content_validation_and_ordering(db):
    await seed(db)
    from app.modules.papers.api import paper_content

    body = await paper_content("p1", space_id="s1", limit=200)
    assert [chunk["chunk_id"] for chunk in body["chunks"]] == ["p1-0", "p1-1"]
    assert body["paper"]["url"] == "https://example.test"
    with pytest.raises(HTTPException) as missing:
        await paper_content("missing", space_id="s1")
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as unpinned:
        await paper_content("p1", space_id="s2")
    assert unpinned.value.status_code == 404


async def test_anchored_note_validation_and_empty_highlight(db):
    await seed(db)
    service = NoteService()
    note = await service.create("s1", "p1", "", chunk_id="p1-0", anchor_quote="beta", anchor_start=6, anchor_end=10, color="yellow")
    assert note.chunk_id == "p1-0"
    assert note.anchor_quote == "beta"
    with pytest.raises(HTTPException) as wrong_chunk:
        await service.create("s1", "p1", "bad", chunk_id="p2-0", anchor_quote="Other", anchor_start=0, anchor_end=5)
    assert wrong_chunk.value.status_code == 422
    async with db() as session:
        stored = await session.get(Note, note.id)
    assert stored and stored.content == ""


async def test_annotations_ordered_and_anchored_only(db):
    await seed(db)
    service = NoteService()
    await service.create("s1", "p1", "plain")
    late = await service.create("s1", "p1", "late", chunk_id="p1-1", anchor_quote="Methods", anchor_start=0, anchor_end=7)
    early = await service.create("s1", "p1", "early", chunk_id="p1-0", anchor_quote="gamma", anchor_start=11, anchor_end=16)
    first = await service.create("s1", "p1", "first", chunk_id="p1-0", anchor_quote="Alpha", anchor_start=0, anchor_end=5)
    notes = await service.annotations("s1", "p1")
    assert [note.id for note in notes] == [first.id, early.id, late.id]
