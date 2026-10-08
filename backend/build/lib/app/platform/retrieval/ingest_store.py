"""Shared in-process ingest store for the dev (no-Qdrant) deployment.

Holds one InMemoryVectorStore and a per-space chunk registry so that the
ingestion path (PaperService) and the retrieval path (QAOrchestrator) see the
same data. TODO: replace with Qdrant collections + Postgres chunk rows.
"""
from app.modules.chat.schemas.chat import ScoredChunk
from app.db.session import SessionLocal
from app.platform.retrieval.vectorstore.client import InMemoryVectorStore

vector_store = InMemoryVectorStore()
chunks_by_space: dict[str, list[ScoredChunk]] = {}


def register_chunks(space_id: str, chunks: list[ScoredChunk]) -> None:
    space=chunks_by_space.setdefault(space_id, [])
    by_id={c.chunk_id: c for c in space}
    for chunk in chunks:
        by_id[chunk.chunk_id]=chunk
    chunks_by_space[space_id]=list(by_id.values())


def get_chunks(space_id: str) -> list[ScoredChunk]:
    return chunks_by_space.get(space_id, [])


def clear() -> None:
    vector_store._data.clear()
    chunks_by_space.clear()


def remove_paper_from_space(space_id: str, paper_id: str) -> None:
    chunks_by_space[space_id] = [c for c in chunks_by_space.get(space_id, []) if c.paper_id != paper_id]
    if space_id in vector_store._data:
        vector_store._data[space_id] = {
            chunk_id: item for chunk_id, item in vector_store._data.get(space_id, {}).items() if item[0].paper_id != paper_id
        }


async def rehydrate_from_db() -> None:
    from sqlalchemy import select
    from app.modules.papers.orm.chunk import Chunk
    from app.modules.papers.orm.paper import Paper
    from app.modules.spaces.orm.pin import Pin
    from app.modules.spaces.orm.research_space import ResearchSpace

    clear()
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Pin.space_id, Paper.title, Chunk)
                .join(Paper, Paper.id == Pin.paper_id)
                .join(ResearchSpace, ResearchSpace.id == Pin.space_id)
                .join(Chunk, Chunk.paper_id == Paper.id)
                .where(Chunk.embedding_json.is_not(None), ResearchSpace.user_id.is_not(None), ResearchSpace.user_id == Paper.owner_id)
                .order_by(Pin.space_id, Chunk.paper_id, Chunk.ordinal)
            )
        ).all()
    by_space: dict[str, tuple[list[ScoredChunk], list[list[float]]]] = {}
    for space_id, title, chunk in rows:
        scored = ScoredChunk(
            chunk_id=chunk.id,
            paper_id=chunk.paper_id,
            text=chunk.text,
            section=chunk.section,
            page=chunk.page,
            source=title,
            metadata={'ordinal': chunk.ordinal},
        )
        chunks, vectors = by_space.setdefault(space_id, ([], []))
        chunks.append(scored)
        vectors.append(chunk.embedding_json)
    for space_id, (chunks, vectors) in by_space.items():
        chunks_by_space[space_id] = list(chunks)
        await vector_store.upsert(space_id, chunks, vectors)
