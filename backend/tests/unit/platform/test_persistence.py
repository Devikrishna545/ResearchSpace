import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.session import configure_sqlite_pragmas
from app.core.auth import _active_user_id
from app.db.models import Base
from app.modules.papers.orm.chunk import Chunk
from app.modules.chat.orm.citation import Citation
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.chat.orm.turn import Turn
from app.modules.auth.orm.user import User
from app.modules.chat.schemas.chat import EvidenceSet, ScoredChunk
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.chat import service as chat_service
from app.platform.retrieval import ingest_store
from app.modules.papers import service as paper_service
from app.modules.spaces import service as space_service
from app.modules.chat.service import QAOrchestrator
from app.modules.papers.service import PaperService
from app.modules.spaces.service import SpaceService
from app.modules.discovery.providers.normalizer import Normalizer
from app.platform.verification import trail
from app.platform.verification import trail_store
from app.platform.verification.trail_store import trail as shared_trail


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = configure_sqlite_pragmas(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True))
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        session.add(User(id="test-owner", email="owner@example.com", is_admin=False))
        await session.commit()
    for module in (paper_service, space_service, chat_service, ingest_store, trail, trail_store):
        monkeypatch.setattr(module, "SessionLocal", session_local, raising=False)
    ingest_store.clear()
    shared_trail.memory.clear()
    yield session_local
    ingest_store.clear()
    shared_trail.memory.clear()
    await engine.dispose()


class FakeEmbedder:
    async def embed(self, texts, model):
        return [[float(i + 1), 0.0, 0.0] for i, _ in enumerate(texts)]

class BadEmbedder:
    async def embed(self, texts, model):
        return []


async def test_paper_dedupe_on_repin(db):
    space = await SpaceService().create("Dedupe")
    service = PaperService()
    service.llm = FakeEmbedder()
    record = RawPaperRecord(
        source="test",
        title="A paper",
        authors=["Ada"],
        abstract="This abstract has enough words to become one chunk.",
        doi="10.123/example",
    )

    first = await service.pin_and_ingest(str(space.id), record)
    second = await service.pin_and_ingest(str(space.id), record)

    assert first.paper_id == second.paper_id
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Paper)) == 1
        assert await session.scalar(select(func.count()).select_from(Pin)) == 1
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 1


async def test_datacite_enrichment_reuses_owner_paper_without_unique_collision(db):
    service = PaperService()
    service.llm = FakeEmbedder()
    arxiv_space = await SpaceService().create("arXiv import")
    first = await service.pin_and_ingest(arxiv_space.id, RawPaperRecord(
        source="arxiv", title="An identifiable preprint",
        arxiv_id="2004.04906", abstract="Original evidence for local ingestion.",
    ))
    doi_record = RawPaperRecord(
        source="openalex", title="An alternate source rendering",
        doi="https://doi.org/10.48550/arXiv.2004.04906v3",
    )
    normalized = Normalizer().normalize([doi_record])[0]
    assert normalized.arxiv_id == "2004.04906"
    second_space = await SpaceService().create("DOI import")
    second = await service.pin_and_ingest(second_space.id, RawPaperRecord(**normalized.model_dump()))
    assert second.paper_id == first.paper_id
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Paper)) == 1
        assert await session.scalar(select(func.count()).select_from(Pin)) == 2
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 1
        session.add(User(id="separate-owner", email="separate@example.com", is_admin=False))
        await session.commit()
    token = _active_user_id.set("separate-owner")
    try:
        third_space = await SpaceService().create("Private copy")
        third = await service.pin_and_ingest(third_space.id, RawPaperRecord(**normalized.model_dump()))
        assert third.paper_id != first.paper_id
    finally:
        _active_user_id.reset(token)
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Paper)) == 2


async def test_same_doi_is_separate_per_user(db):
    service = PaperService()
    service.llm = FakeEmbedder()
    record = RawPaperRecord(source="test", title="Identical research", doi="10.123/shared", abstract="The same paper imported independently by two separate users.")
    first_space = await SpaceService().create("First")
    first = await service.pin_and_ingest(first_space.id, record)
    async with db() as session:
        session.add(User(id="another-owner", email="second@example.com", is_admin=False))
        await session.commit()
    token = _active_user_id.set("another-owner")
    try:
        second_space = await SpaceService().create("Second")
        second = await service.pin_and_ingest(second_space.id, record)
        assert second.paper_id != first.paper_id
        assert await service.get(first.paper_id) is None
        assert [c.paper_id for c in ingest_store.get_chunks(second_space.id)] == [second.paper_id]
    finally:
        _active_user_id.reset(token)
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Paper).where(Paper.doi == "10.123/shared")) == 2
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 2

async def test_embedding_count_mismatch_fails_without_partial_publish(db):
    space = await SpaceService().create("Bad embeddings")
    service = PaperService()
    service.llm = BadEmbedder()
    result = await service.pin_and_ingest(
        str(space.id),
        RawPaperRecord(source="test", title="Bad", abstract="This abstract has enough words to chunk.", doi="10.123/bad"),
    )
    assert result.status.value == "FAILED"
    assert ingest_store.get_chunks(str(space.id)) == []
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 0

async def test_sqlite_foreign_keys_enabled(db):
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Paper)) == 0
        enabled = await session.scalar(text('PRAGMA foreign_keys'))
    assert enabled == 1

def test_pdf_url_validator_rejects_unsafe_urls():
    from app.modules.papers.service import validate_public_https_url
    assert not validate_public_https_url('http://example.com/file.pdf')
    assert not validate_public_https_url('https://127.0.0.1/file.pdf')
    assert not validate_public_https_url('https://169.254.1.1/file.pdf')
    assert not validate_public_https_url('https://10.0.0.1/file.pdf')
    assert not validate_public_https_url('https://192.168.1.1/file.pdf')


async def test_rehydrate_restores_chunks_for_pinned_papers(db):
    space = await SpaceService().create("Rehydrate")
    service = PaperService()
    service.llm = FakeEmbedder()
    await service.pin_and_ingest(
        str(space.id),
        RawPaperRecord(source="test", title="Stored", abstract="Persisted chunk text.", doi="10.123/stored"),
    )

    ingest_store.clear()
    assert ingest_store.get_chunks(str(space.id)) == []

    await ingest_store.rehydrate_from_db()

    chunks = ingest_store.get_chunks(str(space.id))
    assert [c.text for c in chunks] == ["Stored Persisted chunk text."]
    hits = await ingest_store.vector_store.search(str(space.id), [1.0, 0.0, 0.0])
    assert hits[0].chunk_id == chunks[0].chunk_id


class FakeRetriever:
    async def retrieve(self, space_id, question, extra_queries=None):
        return EvidenceSet(chunks=[ScoredChunk(chunk_id="chunk-1", paper_id="paper-1", text="Evidence text")])


class FakeLLM:
    async def embed(self, texts, model):
        return [[1.0] for _ in texts]

    async def chat(self, messages, model, temperature=0.0, json_format=False, **kwargs):
        if kwargs.get("schema", {}).get("title") == "_AnswerContent":
            return json.dumps({"claims": [{"text": "Answer", "cited_chunk_ids": ["chunk-1"]}]})
        if json_format:
            return json.dumps(
                {
                    "verdict": "APPROVED",
                    "overall_score": 1.0,
                    "global_feedback": "Every claim is supported by the cited passage.",
                    "hallucination_flags": ["test audit flag"],
                    "claims": [
                        {
                            "claim_id": "c1",
                            "claim_text": "Answer [chunk-1].",
                            "status": "SUPPORTED",
                            "cited_chunk_ids": ["chunk-1"],
                        }
                    ],
                }
            )
        return "Answer [chunk-1]."


async def test_turns_citations_and_verification_trail_persist(db, monkeypatch):
    space = await SpaceService().create("Chat")
    async with db() as session:
        session.add(Paper(id="paper-1", owner_id="test-owner", title="Paper", authors=[], raw_payload={}))
        await session.flush()
        session.add(Chunk(id="chunk-1", paper_id="paper-1", ordinal=0, text="Evidence text", embedding_json=[1.0]))
        await session.commit()
    monkeypatch.setattr(chat_service, "get_ollama_client", lambda: FakeLLM())

    result = await QAOrchestrator(Settings(), retriever=FakeRetriever()).answer(str(space.id), "Question?")

    async with db() as session:
        turns = (await session.execute(select(Turn).order_by(Turn.created_at))).scalars().all()
        citations = (await session.execute(select(Citation))).scalars().all()
    assert [turn.role for turn in turns] == ["user", "assistant"]
    assert turns[1].id == result.turn_id
    assert citations[0].turn_id == result.turn_id
    assert citations[0].claim_text == result.citations[0].claim_text
    assert citations[0].claim_text != citations[0].quote
    assert citations[0].match_score == 1.0

    shared_trail.memory.clear()
    traces = await shared_trail.get(result.turn_id)
    assert len(traces) == 1
    assert traces[0].verdict.overall_score == 1.0
    assert traces[0].verdict.global_feedback == "Every claim is supported by the cited passage."
    assert traces[0].verdict.hallucination_flags == ["test audit flag"]
    assert turns[1].answer_metadata["verified"] is True
    assert turns[1].answer_metadata["citations"][0]["quote"] == "Evidence text"
    assert traces[0].model_used == f"answer={Settings().ollama_model_medium}; review={Settings().ollama_model_verify}"


async def test_ingest_failure_marks_paper_failed(db):
    space = await SpaceService().create("Failure status")
    service = PaperService()
    service.llm = BadEmbedder()
    result = await service.pin_and_ingest(
        str(space.id),
        RawPaperRecord(source="test", title="Bad status", abstract="Text to embed.", doi="10.123/fail-status"),
    )
    assert result.status.value == "FAILED"
    async with db() as session:
        status = await session.scalar(select(Paper.ingest_status).where(Paper.id == result.paper_id))
    assert status == "FAILED"

async def test_abstract_only_ingest_marks_degraded(db):
    space = await SpaceService().create("Degraded status")
    service = PaperService()
    service.llm = FakeEmbedder()
    result = await service.pin_and_ingest(
        str(space.id),
        RawPaperRecord(source="test", title="Abstract only", abstract="Only abstract text.", doi="10.123/degraded"),
    )
    assert result.status.value == "DEGRADED"
    async with db() as session:
        status = await session.scalar(select(Paper.ingest_status).where(Paper.id == result.paper_id))
    assert status == "DEGRADED"


async def test_repin_enriches_existing_paper_and_reads_abstract_when_pdf_unavailable(db, monkeypatch):
    space = await SpaceService().create("Crossref metadata")
    async with db() as session:
        session.add(Paper(id="legacy-crossref", owner_id="test-owner", doi="10.1039/d3ay00704a",
                          title="Effect of <i>Borassus flabellifer</i>\n extracts",
                          authors=[], source="crossref", raw_payload={}, ingest_status="DEGRADED"))
        await session.commit()
    service = PaperService()
    service.llm = FakeEmbedder()

    async def unavailable_pdf(url):
        return []

    monkeypatch.setattr(service, "_fetch_pdf_pages", unavailable_pdf)
    result = await service.pin_and_ingest(space.id, RawPaperRecord(
        source="crossref", title="Effect of <i>Borassus flabellifer</i> extracts",
        abstract="<jats:p>There is readable evidence in this abstract.</jats:p>",
        doi="10.1039/d3ay00704a", pdf_url="https://publisher.example/restricted.pdf",
    ))
    assert result.paper_id == "legacy-crossref"
    assert result.status.value == "DEGRADED"
    assert "abstract only" in result.message
    async with db() as session:
        paper = await session.get(Paper, result.paper_id)
        chunks = (await session.execute(select(Chunk).where(Chunk.paper_id == result.paper_id))).scalars().all()
    assert paper.title == "Effect of Borassus flabellifer extracts"
    assert paper.abstract == "There is readable evidence in this abstract."
    assert paper.pdf_url == "https://publisher.example/restricted.pdf"
    assert len(chunks) == 1 and "readable evidence" in chunks[0].text
    assert "<jats:" not in chunks[0].text


@pytest.mark.parametrize(("status", "content_type", "body"), [
    (403, "text/html", b"<html>Sign in to continue</html>"),
    (200, "text/html", b"<html>Sign in to continue</html>"),
    (200, "application/pdf", b"<html>Sign in to continue</html>"),
])
async def test_pdf_fetch_never_accepts_publisher_login_or_non_pdf(monkeypatch, status, content_type, body):
    service = PaperService()
    real_client = httpx.AsyncClient
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(status, headers={"content-type": content_type}, content=body)

    def client_factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(paper_service.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(paper_service, "validate_public_https_url", lambda url: url.startswith("https://publisher.example/"))
    assert await service._fetch_pdf_pages("https://publisher.example/paper.pdf") == []
    assert requested == ["https://publisher.example/paper.pdf"]


async def test_pdf_fetch_checks_each_redirect_before_request(monkeypatch):
    service = PaperService()
    real_client = httpx.AsyncClient
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(paper_service.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(paper_service, "validate_public_https_url", lambda url: url == "https://publisher.example/paper.pdf")
    assert await service._fetch_pdf_pages("https://publisher.example/paper.pdf") == []
    assert requested == ["https://publisher.example/paper.pdf"]


async def test_pdf_fetch_accepts_real_pdf_magic_after_safe_redirect(monkeypatch):
    service = PaperService()
    real_client = httpx.AsyncClient
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == "/paper.pdf":
            return httpx.Response(302, headers={"location": "/download.pdf"})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7\nvalid-pdf")

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(paper_service.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(paper_service, "validate_public_https_url", lambda url: url.startswith("https://publisher.example/"))
    monkeypatch.setattr(paper_service, "_parse_pdf_pages", lambda data: ["Readable PDF text"] if data.startswith(b"%PDF-") else [])
    assert await service._fetch_pdf_pages("https://publisher.example/paper.pdf") == ["Readable PDF text"]
    assert requested == ["https://publisher.example/paper.pdf", "https://publisher.example/download.pdf"]

async def test_status_endpoint_reads_db_and_404s(db, monkeypatch):
    from fastapi import HTTPException
    from app.modules.papers import api as papers_api

    monkeypatch.setattr(papers_api, "SessionLocal", db, raising=False)
    space = await SpaceService().create("Status endpoint")
    service = PaperService()
    service.llm = FakeEmbedder()
    result = await service.pin_and_ingest(
        str(space.id),
        RawPaperRecord(source="test", title="Status", abstract="Status abstract.", doi="10.123/status"),
    )

    assert await papers_api.paper_status(result.paper_id) == {"paper_id": result.paper_id, "status": "DEGRADED"}
    with pytest.raises(HTTPException) as exc:
        await papers_api.paper_status("missing")
    assert exc.value.status_code == 404


class FakeStreamResponse:
    def __init__(self, data=b"", content_type="text/html", url="https://example.com/page"):
        self._data = data
        self.headers = {"content-type": content_type}
        self.url = url

    async def __aenter__(self): return self
    async def __aexit__(self, *args): return None
    def raise_for_status(self): return None
    async def aiter_bytes(self):
        yield self._data


class FakeRobotsResponse:
    def __init__(self, text="", status_code=200, url="https://example.com/robots.txt"):
        self.text = text
        self.status_code = status_code
        self.url = url


class FakeWebClient:
    robots = "User-agent: *\nAllow: /\n"
    html = b"<html><head><title>Captured title</title><script>x()</script></head><body><header>menu</header><main><h1>Heading</h1><p>Readable web page text with enough words to make a useful grounded citation chunk for later chat evidence and retrieval. The paragraph continues with additional context, definitions, observations, limitations, and practical implications for the research assistant workspace.</p></main></body></html>"
    fetched = False

    def __init__(self, *args, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return None
    async def get(self, url):
        return FakeRobotsResponse(self.robots)
    def stream(self, method, url):
        self.__class__.fetched = True
        return FakeStreamResponse(self.html, url=url)


async def test_web_capture_html_extracts_pins_and_dedupes(db, monkeypatch):
    from app.modules.papers import service as ps
    monkeypatch.setattr(ps, "validate_public_https_url", lambda url: True)
    monkeypatch.setattr(ps.httpx, "AsyncClient", FakeWebClient)
    space = await SpaceService().create("Web")
    service = PaperService()
    service.llm = FakeEmbedder()

    first = await service.capture_web(str(space.id), "https://example.com/page")
    second = await service.capture_web(str(space.id), "https://example.com/page")

    assert first.status.value == "READY"
    assert first.paper_id == second.paper_id
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Paper)) == 1
        assert await session.scalar(select(func.count()).select_from(Pin)) == 1
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 1


async def test_web_capture_rejects_unsafe_and_robots(db, monkeypatch):
    from app.modules.papers import service as ps
    space = await SpaceService().create("Blocked")
    service = PaperService()
    monkeypatch.setattr(ps, "validate_public_https_url", lambda url: False)
    with pytest.raises(ValueError, match="public"):
        await service.capture_web(str(space.id), "http://127.0.0.1/")

    monkeypatch.setattr(ps, "validate_public_https_url", lambda url: True)
    FakeWebClient.robots = "User-agent: *\nDisallow: /\n"
    monkeypatch.setattr(ps.httpx, "AsyncClient", FakeWebClient)
    with pytest.raises(ValueError, match="robots"):
        await service.capture_web(str(space.id), "https://example.com/private")
    FakeWebClient.robots = "User-agent: *\nAllow: /\n"


async def test_web_capture_content_skips_fetch(db, monkeypatch):
    from app.modules.papers import service as ps
    space = await SpaceService().create("Selection")
    service = PaperService()
    service.llm = FakeEmbedder()
    monkeypatch.setattr(ps, "validate_public_https_url", lambda url: True)
    FakeWebClient.fetched = False
    monkeypatch.setattr(ps.httpx, "AsyncClient", FakeWebClient)
    result = await service.capture_web(str(space.id), "https://example.com/page", "Selected", "Copied text with enough words to become a chunk for grounded evidence in the space.")
    assert result.status.value == "DEGRADED"
    assert not FakeWebClient.fetched

async def test_canonical_identifiers_dedupe_at_persistence(db):
    space = await SpaceService().create("Canonical IDs")
    service = PaperService()
    service.llm = FakeEmbedder()
    records = [
        RawPaperRecord(source="test", title="DOI A", abstract="Text A.", doi="https://doi.org/10.X/Y"),
        RawPaperRecord(source="test", title="DOI B", abstract="Text B.", doi="DOI:10.X/Y"),
        RawPaperRecord(source="test", title="DOI C", abstract="Text C.", doi="10.x/Y"),
    ]
    ids = [(await service.pin_and_ingest(str(space.id), record)).paper_id for record in records]
    assert len(set(ids)) == 1
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Paper)) == 1
        stored = await session.scalar(select(Paper.doi))
    assert stored == "10.x/y"

async def test_arxiv_identifier_dedupe_without_version(db):
    space = await SpaceService().create("Arxiv IDs")
    service = PaperService()
    service.llm = FakeEmbedder()
    first = await service.pin_and_ingest(str(space.id), RawPaperRecord(source="test", title="A", abstract="A text.", arxiv_id="arXiv:2401.12345v2"))
    second = await service.pin_and_ingest(str(space.id), RawPaperRecord(source="test", title="B", abstract="B text.", arxiv_id="2401.12345"))
    assert first.paper_id == second.paper_id
    async with db() as session:
        stored = await session.scalar(select(Paper.arxiv_id))
    assert stored == "2401.12345"


async def test_background_pin_returns_before_ingest_and_bulk_unpin_is_owner_scoped(db):
    import asyncio
    from app.modules.papers import service as paper_module

    space = await SpaceService().create("Background")
    service = PaperService()
    gate = asyncio.Event()

    class GatedEmbedder(FakeEmbedder):
        async def embed(self, texts, model):
            await gate.wait()
            return await super().embed(texts, model)

    service.llm = GatedEmbedder()
    records = [RawPaperRecord(source="test", title=f"Paper {i}", abstract=f"Abstract {i} has enough words for a chunk.", doi=f"10.1/bg{i}") for i in range(3)]
    jobs = [await service.pin_and_ingest_background(str(space.id), record) for record in records]
    assert {job.status for job in jobs} == {"QUEUED"}
    detail = await SpaceService().get(str(space.id))
    assert {pin["id"] for pin in detail["pins"]} == {job.paper_id for job in jobs}
    assert all(status in {"QUEUED", "CHUNKING", "EMBEDDING"} for status in [await service.get_status(job.paper_id) for job in jobs])

    gate.set()
    for _ in range(100):
        if not paper_module._background_ingests:
            break
        await asyncio.sleep(0.01)
    # Abstract-only records finish as DEGRADED (readable but not full text).
    assert [await service.get_status(job.paper_id) for job in jobs] == ["DEGRADED"] * 3
    assert {c.paper_id for c in ingest_store.get_chunks(str(space.id))} == {job.paper_id for job in jobs}

    again = await service.pin_and_ingest_background(str(space.id), records[0])
    assert again.status == "DEGRADED" and again.paper_id == jobs[0].paper_id
    await asyncio.gather(*list(paper_module._background_ingests))

    removed = await service.unpin_many(str(space.id), [jobs[0].paper_id, jobs[1].paper_id, jobs[0].paper_id, "not-pinned"])
    assert sorted(removed["unpinned"]) == sorted([jobs[0].paper_id, jobs[1].paper_id])
    assert {c.paper_id for c in ingest_store.get_chunks(str(space.id))} == {jobs[2].paper_id}
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Pin)) == 1
    token = _active_user_id.set("intruder")
    try:
        assert (await service.unpin_many(str(space.id), [jobs[2].paper_id]))["unpinned"] == []
    finally:
        _active_user_id.reset(token)
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Pin)) == 1
