import json

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.session import configure_sqlite_pragmas
from app.core.exceptions import LLMUnavailableError
from app.db.models import Base
from app.modules.chat.orm.chat_session import ChatSession
from app.modules.papers.orm.chunk import Chunk
from app.modules.chat.orm.citation import Citation
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.chat.orm.turn import Turn
from app.modules.auth.orm.user import User
from app.modules.chat.orm.verification_iteration import VerificationIteration
from app.platform.retrieval.query_rewriter import QueryRewriter
from app.modules.chat.schemas.chat import ConversationContext, ConversationTurnDTO, EvidenceSet, ReferencedSessionDTO, ScoredChunk
from app.modules.chat import service as chat_service
from app.modules.chat import sessions as chat_session_service
from app.platform.retrieval import ingest_store
from app.modules.chat.memory import service as memory_service
from app.modules.notes import service as note_service
from app.modules.spaces import service as space_service
from app.modules.chat.service import QAOrchestrator
from app.modules.chat.sessions import ChatSessionService, DEFAULT_TITLE, strip_mentions, title_from_question
from app.modules.chat.memory.service import MemoryService
from app.modules.spaces.service import SpaceService
from app.platform.verification import trail
from app.platform.verification import trail_store
from app.platform.verification.trail_store import trail as shared_trail


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = configure_sqlite_pragmas(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}", future=True))
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        session.add(User(id="test-owner", email="owner@example.com", is_admin=False))
        session.add(User(id="someone-else", email="other@example.com", is_admin=False))
        await session.flush()
        session.add(ResearchSpace(id="s1", user_id="test-owner", name="Space"))
        session.add(ResearchSpace(id="s2", user_id="test-owner", name="Second"))
        session.add(ResearchSpace(id="foreign", user_id="someone-else", name="Not mine"))
        session.add(Paper(id="paper-1", owner_id="test-owner", title="Paper", authors=[], raw_payload={}))
        await session.flush()
        session.add(Chunk(id="chunk-1", paper_id="paper-1", ordinal=0, text="Evidence text", embedding_json=[1.0]))
        await session.commit()
    for module in (chat_service, chat_session_service, memory_service, note_service, space_service, ingest_store, trail, trail_store):
        monkeypatch.setattr(module, "SessionLocal", session_local, raising=False)
    ingest_store.clear()
    shared_trail.memory.clear()
    yield session_local
    ingest_store.clear()
    shared_trail.memory.clear()
    await engine.dispose()


async def add_turns(db, session_id, space_id, count, start=0):
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with db() as session:
        for i in range(start, start + count):
            session.add(Turn(id=f"{session_id}-t{i}", space_id=space_id, session_id=session_id, role="user" if i % 2 == 0 else "assistant",
                             content=f"message {i} about retrieval", created_at=base + timedelta(minutes=i)))
        await session.commit()


def test_title_and_mention_helpers():
    assert title_from_question("   ") == DEFAULT_TITLE
    assert title_from_question("short   question") == "short question"
    long = title_from_question("word " * 40)
    assert len(long) == 60 and long.endswith("\u2026")
    assert strip_mentions("Compare @Transformer basics with @Transformer", ["Transformer", "Transformer basics"]) == 'Compare "Transformer basics" with "Transformer"'
    assert strip_mentions("No mentions here", []) == "No mentions here"
    from app.modules.chat.sessions import _preview
    assert _preview("Gains of 12 percent [c4358281-aa12-4b7e-9f0a-1-3]. Also [note-abc123].") == "Gains of 12 percent. Also."
    assert _preview("See [1] and [a]") == "See [1] and [a]"


async def test_session_crud_ordering_search_archive_and_delete(db):
    service = ChatSessionService()
    first = await service.create("s1")
    second = await service.create("s1", "Graph methods")
    assert first["title"] == DEFAULT_TITLE and not first["pinned"] and not first["archived"]
    await add_turns(db, first["id"], "s1", 2)

    await service.update(first["id"], title="Renamed thread")
    pinned = await service.update(second["id"], pinned=True)
    assert pinned["pinned"]
    listed = await service.list("s1")
    assert [row["id"] for row in listed] == [second["id"], first["id"]]
    assert listed[1]["title"] == "Renamed thread"
    assert listed[1]["turn_count"] == 2 and listed[1]["last_message"] == "message 1 about retrieval"

    by_title = await service.list("s1", q="graph")
    assert [row["id"] for row in by_title] == [second["id"]]
    by_content = await service.list("s1", q="RETRIEVAL")
    assert [row["id"] for row in by_content] == [first["id"]]
    assert "retrieval" in by_content[0]["match"]

    await service.update(first["id"], archived=True)
    assert [row["id"] for row in await service.list("s1")] == [second["id"]]
    assert [row["id"] for row in await service.list("s1", status="archived")] == [first["id"]]
    assert len(await service.list("s1", status="all")) == 2
    await service.update(first["id"], archived=False)
    assert len(await service.list("s1")) == 2

    async with db() as session:
        session.add(Citation(id="cit", turn_id=f"{first['id']}-t1", chunk_id="chunk-1", paper_id="paper-1", ordinal=0))
        session.add(VerificationIteration(id="vi", turn_id=f"{first['id']}-t1", iteration=1, draft_text="d", verdict="APPROVED", overall_score=1.0, action_taken="accept"))
        await session.commit()
    turns = await service.list_turns(first["id"])
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert turns[1]["citations"][0]["chunk_id"] == "chunk-1"

    await service.delete(first["id"])
    async with db() as session:
        assert await session.get(ChatSession, first["id"]) is None
        assert await session.scalar(select(func.count()).select_from(Turn).where(Turn.session_id == first["id"])) == 0
        assert await session.scalar(select(func.count()).select_from(Citation)) == 0
        assert await session.scalar(select(func.count()).select_from(VerificationIteration)) == 0

    with pytest.raises(HTTPException) as missing:
        await service.get(first["id"])
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as foreign:
        await service.create("foreign")
    assert foreign.value.status_code == 404


class CountingSummaryAgent:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def summarize(self, turns, prior_summary=None):
        if self.fail:
            raise LLMUnavailableError("down")
        self.calls.append(([t.id for t in turns], prior_summary))
        return f"summary through {turns[-1].id}"


async def test_compression_covers_older_turns_incrementally(db):
    service = ChatSessionService()
    thread = await service.create("s1", "Long thread")
    sid = thread["id"]
    await add_turns(db, sid, "s1", 6)
    with pytest.raises(HTTPException) as too_short:
        await service.compress(sid, CountingSummaryAgent())
    assert too_short.value.status_code == 409

    await add_turns(db, sid, "s1", 10, start=6)
    agent = CountingSummaryAgent()
    compressed = await service.compress(sid, agent, batch_size=5)
    assert compressed["summary_turn_count"] == 12
    assert compressed["summary"] == f"summary through {sid}-t11"
    assert [len(ids) for ids, _ in agent.calls] == [5, 5, 2]
    assert agent.calls[1][1] == f"summary through {sid}-t4"

    await add_turns(db, sid, "s1", 4, start=16)
    again = CountingSummaryAgent()
    updated = await service.compress(sid, again, batch_size=5)
    assert updated["summary_turn_count"] == 16
    assert again.calls == [([f"{sid}-t{i}" for i in range(12, 16)], f"summary through {sid}-t11")]

    await add_turns(db, sid, "s1", 2, start=20)
    with pytest.raises(HTTPException) as unavailable:
        await service.compress(sid, CountingSummaryAgent(fail=True))
    assert unavailable.value.status_code == 503
    assert (await service.get(sid))["summary_turn_count"] == 16


class FakeRetriever:
    def __init__(self):
        self.questions = []

    async def retrieve(self, space_id, question, extra_queries=None):
        self.questions.append((question, list(extra_queries or [])))
        return EvidenceSet(chunks=[ScoredChunk(chunk_id="chunk-1", paper_id="paper-1", text="Evidence text")])


class FakeLLM:
    def __init__(self):
        self.prompts = []

    async def embed(self, texts, model):
        return [[1.0] for _ in texts]

    async def chat(self, messages, model, temperature=0.0, json_format=False, **kwargs):
        self.prompts.append(messages[-1]["content"])
        if kwargs.get("schema", {}).get("title") == "_AnswerContent":
            return json.dumps({"claims": [{"text": "Answer", "cited_chunk_ids": ["chunk-1"]}]})
        if json_format:
            return json.dumps({"verdict": "APPROVED", "overall_score": 1.0, "claims": [
                {"claim_id": "c1", "claim_text": "Answer [chunk-1].", "status": "SUPPORTED", "cited_chunk_ids": ["chunk-1"]}]})
        if "standalone" in messages[0]["content"].lower() or "rewrite" in messages[0]["content"].lower():
            return "What evidence covers retrieval augmented generation?"
        return "Answer [chunk-1]."


async def test_chat_answers_are_scoped_to_sessions_with_mentions(db, monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(chat_service, "get_ollama_client", lambda: llm)
    monkeypatch.setattr(MemoryService, "on_turn_complete", lambda self, space_id, turns=None: _noop())
    retriever = FakeRetriever()
    orchestrator = QAOrchestrator(Settings(), retriever=retriever)
    service = ChatSessionService()

    first = await service.create("s1")
    result = await orchestrator.answer("s1", "What is retrieval augmented generation?", session_id=first["id"])
    assert result.session_id == first["id"]
    titled = await service.get(first["id"])
    assert titled["title"] == "What is retrieval augmented generation?"
    assert titled["turn_count"] == 2
    saved = (await service.list_turns(first["id"]))[1]
    assert saved["verification"]["verified"] is True
    assert saved["verification"]["confidence"] == result.confidence
    assert saved["verification"]["iterations"] == result.iterations
    assert saved["citations"] == [c.model_dump(mode="json") for c in result.citations]

    second = await service.create("s1")
    await orchestrator.answer("s1", "Compare with @What is retrieval augmented generation? for vision", session_id=second["id"],
                              mentioned_session_ids=[first["id"], second["id"], "missing"])
    turns = await service.list_turns(second["id"])
    assert turns[0]["mentions"] == [{"id": first["id"], "title": "What is retrieval augmented generation?"}]
    assert turns[0]["content"].startswith("Compare with @What")
    assert retriever.questions[-1] == ("What evidence covers retrieval augmented generation?",
                                       ['Compare with "What is retrieval augmented generation?" for vision'])
    assert any(prompt.startswith("Question:\nWhat evidence covers retrieval augmented generation?") for prompt in llm.prompts)

    context = await MemoryService(recent_limit=6).get_context("s1", 800, session_id=second["id"])
    assert [turn.content for turn in context.recent_turns][0].startswith("Compare with")
    assert all(turn["session_id"] == second["id"] for turn in turns)
    assert len(context.recent_turns) == 2

    legacy = await orchestrator.answer("s1", "Follow up without a session")
    assert legacy.session_id == second["id"]

    await service.update(first["id"], archived=True)
    with pytest.raises(HTTPException) as archived:
        await orchestrator.answer("s1", "Another", session_id=first["id"])
    assert archived.value.status_code == 409
    with pytest.raises(HTTPException) as other_space:
        await orchestrator.answer("s2", "Wrong space", session_id=second["id"])
    assert other_space.value.status_code == 404

    fresh = await orchestrator.answer("s2", "Fresh space question")
    assert (await service.get(fresh.session_id))["space_id"] == "s2"

    await SpaceService().delete("s1")
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(ChatSession).where(ChatSession.space_id == "s1")) == 0


async def _noop():
    return None


async def test_note_citations_and_low_confidence_survive_history_reload(db):
    service = ChatSessionService()
    chat = await service.create("s1")
    note_citation = {"marker": 1, "chunk_id": "note-saved", "quote": "User note", "paper_id": None}
    async with db() as session:
        session.add(Turn(id="note-answer", space_id="s1", session_id=chat["id"], role="assistant",
                         content="A note [note-saved].", answer_metadata={
                             "verified": False, "confidence": 0.5, "iterations": 2,
                             "low_confidence_warning": "Partial support only.", "citations": [note_citation],
                         }))
        await session.commit()
    saved = (await service.list_turns(chat["id"]))[0]
    assert saved["citations"] == [note_citation]
    assert saved["verification"]["verified"] is False
    assert saved["verification"]["low_confidence_warning"] == "Partial support only."
    assert (await SpaceService().list_turns("s1"))[0]["verification"] == saved["verification"]


async def test_mentions_force_a_context_aware_rewrite():
    class RecordingLLM:
        def __init__(self):
            self.user_prompt = ""

        async def chat(self, messages, model, temperature=0.0, json_format=False):
            self.user_prompt = messages[-1]["content"]
            return "How do sparse retrievers compare on long documents?"

    class Router:
        def model_for(self, tier):
            return "small"

    llm = RecordingLLM()
    context = ConversationContext(referenced_sessions=[ReferencedSessionDTO(
        session_id="x", title="Sparse retrieval", recent_turns=[ConversationTurnDTO(role="user", content="BM25 on long documents")])])
    rewritten = await QueryRewriter(llm=llm, router=Router()).rewrite("Compare with dense models", context)
    assert rewritten == ["How do sparse retrievers compare on long documents?", "Compare with dense models"]
    assert 'referenced conversation "Sparse retrieval"' in llm.user_prompt
    assert await QueryRewriter(llm=llm, router=Router()).rewrite("Compare with dense models", ConversationContext()) == ["Compare with dense models"]
