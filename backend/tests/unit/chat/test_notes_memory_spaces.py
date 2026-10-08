import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.chat.agents.memory_agent import MemoryAgent
from app.modules.notes.agent import NotesAgent
from app.core.config import Settings
from app.db.session import configure_sqlite_pragmas
from app.core.exceptions import LLMUnavailableError
from app.db.models import Base
from app.modules.papers.orm.chunk import Chunk
from app.modules.chat.orm.citation import Citation
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.notes.orm import Note
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.auth.orm.user import User
from app.modules.spaces.orm.space_memory import SpaceMemory
from app.modules.chat.orm.turn import Turn
from app.modules.chat.orm.verification_iteration import VerificationIteration
from app.modules.chat.schemas.chat import EvidenceSet, ScoredChunk
from app.modules.chat import service as chat_service
from app.platform.retrieval import ingest_store
from app.modules.chat.memory import service as memory_service
from app.modules.notes import service as note_service
from app.modules.papers import service as paper_service
from app.modules.spaces import service as space_service
from app.modules.chat.service import NotesAwareRetriever
from app.modules.chat.memory.service import MemoryService
from app.modules.notes.service import NoteService
from app.modules.spaces.service import SpaceService


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = configure_sqlite_pragmas(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fr56.db'}", future=True))
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        session.add(User(id="test-owner", email="owner@example.com", is_admin=False))
        await session.commit()
    for module in (note_service, memory_service, space_service, paper_service, chat_service, ingest_store):
        monkeypatch.setattr(module, "SessionLocal", session_local, raising=False)
    ingest_store.clear()
    yield session_local
    ingest_store.clear()
    await engine.dispose()


class FakeRouter:
    def model_for(self, tier):
        return f"model-{getattr(tier, 'value', tier)}"


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def chat(self, messages, model, temperature=0.0, json_format=False):
        self.calls.append((model, json_format))
        return self.outputs.pop(0)


async def seed_space_paper(db, *, pinned=True):
    async with db() as session:
        session.add(ResearchSpace(id="s1", user_id="test-owner", name="Space"))
        session.add(Paper(id="p1", owner_id="test-owner", title="Paper One", authors=[], abstract="abstract", raw_payload={}))
        await session.flush()
        if pinned:
            session.add(Pin(id="pin1", space_id="s1", paper_id="p1"))
        session.add(Chunk(id="c1", paper_id="p1", ordinal=0, text="Method results limitations neural retrieval", embedding_json=[1.0]))
        await session.commit()


class CountingNotesAgent:
    def __init__(self):
        self.calls = 0

    async def generate(self, paper_title, chunks):
        self.calls += 1
        return {
            "summary": f"summary {self.calls}",
            "key_contributions": ["contribution"],
            "methodology": "method",
            "results": "results",
            "limitations": "limits",
            "relevance": "relevant",
        }


async def test_notes_service_auto_generate_idempotent_crud_and_validation(db):
    await seed_space_paper(db)
    agent = CountingNotesAgent()
    service = NoteService(agent=agent)

    first = await service.auto_generate("s1", "p1")
    second = await service.auto_generate("s1", "p1")
    refreshed = await service.auto_generate("s1", "p1", refresh=True)

    assert first.id == second.id == refreshed.id
    assert "summary 1" in second.content
    assert "summary 2" in refreshed.content
    assert refreshed.source == "auto"
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Note).where(Note.source == "auto")) == 1

    manual = await service.create("s1", None, "space note")
    paper_note = await service.create("s1", "p1", "paper note")
    assert paper_note.id in [n.id for n in await service.list("s1", "p1")]
    updated = await service.update(manual.id, "updated")
    assert updated.content == "updated"
    await service.delete(manual.id)
    with pytest.raises(HTTPException) as missing_space:
        await service.create("missing", None, "x")
    assert missing_space.value.status_code == 404
    with pytest.raises(HTTPException) as missing_paper:
        await service.auto_generate("s1", "missing")
    assert missing_paper.value.status_code == 404

    async with db() as session:
        session.add(ResearchSpace(id="s2", user_id="test-owner", name="Other"))
        await session.commit()
    with pytest.raises(HTTPException) as unpinned:
        await service.create("s2", "p1", "bad")
    assert unpinned.value.status_code == 404


async def test_notes_agent_tolerant_json_and_degradation():
    summary = "This paper introduces a retrieval augmented pipeline that reduces hallucination across structured generation tasks."
    payload = {"summary": summary, "key_contributions": ["k"], "methodology": "m", "results": "r", "limitations": "l", "relevance": "rel"}
    raws = [json.dumps(payload), "prose ```json\n" + json.dumps(payload) + "\n```", json.dumps(payload)[:-1] + ",}"]
    for raw in raws:
        note = await NotesAgent(llm=FakeLLM([raw]), router=FakeRouter()).generate("P", [ScoredChunk(chunk_id="c", text="text")])
        assert note["summary"] == summary and note["key_contributions"] == ["k"]

    good = json.dumps(payload | {"summary": "retry " + summary})
    llm = FakeLLM(["{}", good])
    note = await NotesAgent(llm=llm, router=FakeRouter()).generate("P", [ScoredChunk(chunk_id="c", text="text")])
    assert note["summary"].startswith("retry")
    assert len(llm.calls) == 2

    # Thin output (just an echoed title) must also be rejected and fall through.
    thin = json.dumps({"summary": "MultiRAG", "key_contributions": [], "methodology": "", "results": "", "limitations": "", "relevance": ""})
    thin_llm = FakeLLM([thin, thin])
    degraded = await NotesAgent(llm=thin_llm, router=FakeRouter()).generate("P", [ScoredChunk(chunk_id="c", text="fallback text")])
    assert "fallback text" in degraded["summary"]

    fallback = await NotesAgent(llm=FakeLLM(["{}", "{}"]), router=FakeRouter()).generate("P", [ScoredChunk(chunk_id="c", text="fallback text")])
    assert "fallback text" in fallback["summary"]


class FixedRetriever:
    async def retrieve(self, space_id, question, scope=None, extra_queries=None):
        return EvidenceSet(chunks=[ScoredChunk(chunk_id="paper-c1", paper_id="p1", text="paper evidence retrieval", source="Paper")])


async def test_notes_as_context_adds_virtual_chunks_without_displacing_paper_evidence(db):
    await seed_space_paper(db)
    created = await NoteService().create("s1", "p1", "This note discusses unique limitations for retrieval.")
    evidence = await NotesAwareRetriever(FixedRetriever(), NoteService()).retrieve("s1", "What limitations affect retrieval?")
    assert evidence.chunks[0].chunk_id == "paper-c1"
    note_chunks = [c for c in evidence.chunks if c.chunk_id.startswith("note-")]
    assert note_chunks and note_chunks[0].chunk_id == f"note-{created.id}"
    assert note_chunks[0].source == "Note: Paper One"


class CountingMemoryAgent:
    def __init__(self, fail=False):
        self.summary_calls = 0
        self.finding_calls = 0
        self.fail = fail

    async def summarize(self, turns, prior_summary=None):
        self.summary_calls += 1
        if self.fail:
            raise LLMUnavailableError("down")
        return "new summary"

    async def extract_findings(self, turns, prior_findings=None):
        self.finding_calls += 1
        if self.fail:
            raise LLMUnavailableError("down")
        return {"findings": ["finding"], "open_questions": ["question"]}


async def test_memory_service_context_threshold_and_swallowed_llm_failure(db):
    async with db() as session:
        session.add(ResearchSpace(id="s1", user_id="test-owner", name="Memory"))
        await session.flush()
        session.add(SpaceMemory(space_id="s1", rolling_summary="prior summary", findings=["old finding"], open_questions=[]))
        for i in range(5):
            session.add(Turn(id=f"t{i}", space_id="s1", role="user" if i % 2 == 0 else "assistant", content=f"turn {i} retrieval topic"))
        await session.commit()

    svc = MemoryService(agent=CountingMemoryAgent(), summary_threshold=6, recent_limit=3)
    context = await svc.get_context("s1", 200)
    assert context.rolling_summary == "prior summary"
    assert len(context.recent_turns) == 3
    await svc.on_turn_complete("s1", None)
    assert svc.agent.summary_calls == 0

    async with db() as session:
        session.add(Turn(id="t5", space_id="s1", role="assistant", content="turn 5 answer"))
        await session.commit()
    await svc.on_turn_complete("s1", None)
    assert svc.agent.summary_calls == 1
    async with db() as session:
        memory = await session.get(SpaceMemory, "s1")
    assert memory.rolling_summary == "new summary"
    assert memory.findings == ["finding"]

    await MemoryService(agent=CountingMemoryAgent(fail=True), summary_threshold=1).on_turn_complete("s1", None)


async def test_space_management_duplicate_delete_and_search(db):
    await seed_space_paper(db)
    await NoteService().create("s1", "p1", "Manual NOTE about GraphRAG")
    async with db() as session:
        session.add(Turn(id="turn1", space_id="s1", role="user", content="Tell me about graphrag"))
        session.add(Turn(id="turn2", space_id="s1", role="assistant", content="Answer"))
        await session.flush()
        session.add(Citation(id="cit1", turn_id="turn2", chunk_id="c1", paper_id="p1"))
        session.add(VerificationIteration(id="vi1", turn_id="turn2", iteration=1, draft_text="d", verdict="APPROVED", overall_score=1.0, action_taken="accept"))
        session.add(ComparisonReport(id="r1", space_id="s1", paper_ids=["p1"], matrix={}, commonalities=[], contradictions=[], gaps=[]))
        session.add(SpaceMemory(space_id="s1", rolling_summary="summary", findings=[], open_questions=[]))
        await session.commit()

    renamed = await SpaceService().rename("s1", "Renamed")
    assert renamed.name == "Renamed"
    assert (await SpaceService().set_archived("s1", True)).status == "archived"
    assert (await SpaceService().set_archived("s1", False)).status == "active"
    duplicate = await SpaceService().duplicate("s1", copy_notes=True)
    assert duplicate["pins"][0]["id"] == "p1"
    assert ingest_store.get_chunks(duplicate["id"])[0].chunk_id == "c1"

    hits = await SpaceService().search_content("s1", "graphrag")
    assert {hit["type"] for hit in hits} == {"turn", "note"}

    await SpaceService().delete("s1")
    async with db() as session:
        assert await session.get(ResearchSpace, "s1") is None
        assert await session.scalar(select(func.count()).select_from(Pin).where(Pin.space_id == "s1")) == 0
        assert await session.scalar(select(func.count()).select_from(Turn).where(Turn.space_id == "s1")) == 0
        assert await session.scalar(select(func.count()).select_from(Note).where(Note.space_id == "s1")) == 0
        assert await session.scalar(select(func.count()).select_from(SpaceMemory).where(SpaceMemory.space_id == "s1")) == 0


def test_fr56_routes_present_in_openapi():
    from app.main import create_app
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    assert "/v1/spaces/{space_id}/notes" in paths
    assert "/v1/spaces/{space_id}/papers/{paper_id}/notes/auto" in paths
    assert "/v1/notes/{note_id}" in paths
    assert "/v1/spaces/{space_id}/memory" in paths
    assert "/v1/spaces/{space_id}/duplicate" in paths
    assert "/v1/spaces/{space_id}/search-content" in paths
