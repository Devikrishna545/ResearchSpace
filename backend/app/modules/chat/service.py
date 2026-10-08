import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.db.session import SessionLocal
from app.core.ownership import ensure_space_owned
from app.modules.chat.orm.citation import Citation
from app.modules.chat.orm.turn import Turn
from app.modules.chat.agents.answer_agent import AnswerAgent
from app.modules.chat.agents.memory_agent import MemoryAgent
from app.platform.verification.peer_reviewer_agent import PeerReviewerAgent
from app.platform.verification.refinement_controller import RefinementController
from app.platform.llm.model_router import ModelRouter
from app.platform.llm.model_router import ModelTier
from app.platform.llm.ollama_client import get_ollama_client
from app.db.retry import retry_sqlite_locked
from app.platform.retrieval.hybrid_retriever import HybridRetriever
from app.platform.retrieval.query_rewriter import QueryRewriter
from app.platform.retrieval.sparse_search import SparseSearch
from app.platform.retrieval import ingest_store
from app.modules.chat.sessions import ChatSessionService, strip_mentions
from app.modules.chat.memory.service import MemoryService
from app.modules.notes.service import NoteService
from app.platform.verification.loop import VerificationLoopDriver
from app.platform.verification.policies import LoopPolicies

logger = logging.getLogger(__name__)


class NotesAwareRetriever:
    def __init__(self, inner, note_service: NoteService):
        self.inner = inner
        self.note_service = note_service

    async def retrieve(self, space_id: str, question: str, scope=None, extra_queries=None):
        try:
            evidence = await self.inner.retrieve(space_id, question, scope=scope, extra_queries=extra_queries)
        except TypeError:
            evidence = await self.inner.retrieve(space_id, question, extra_queries=extra_queries)
        try:
            # Append a small number of note chunks after paper evidence so notes enrich
            # Q&A context without crowding out the verification loop's paper evidence.
            return await self.note_service.augment_evidence_with_notes(space_id, " ".join([question] + list(extra_queries or [])), evidence)
        except Exception:
            logger.warning("Note context augmentation failed", exc_info=True)
            return evidence


class QAOrchestrator:
    def __init__(self,settings,retriever=None):
        self.settings=settings
        policies=LoopPolicies(settings.loop_max_iterations,settings.loop_wall_clock_cap_ms,settings.loop_acceptance_threshold)
        self._retriever=retriever
        self._policies=policies
    def _build_retriever(self,space_id):
        if self._retriever: return self._retriever
        llm=get_ollama_client()
        async def embed(texts): return await llm.embed(texts,self.settings.ollama_model_embed)
        return HybridRetriever(dense=ingest_store.vector_store,sparse=SparseSearch(ingest_store.get_chunks(space_id)),embedder=embed)
    async def answer(self,space_id,question,session_id=None,mentioned_session_ids=None):
        asked_at=datetime.now(timezone.utc)
        async with SessionLocal() as session:
            await ensure_space_owned(session, space_id)
        llm=get_ollama_client(); router=ModelRouter(self.settings)
        # Keep service modules on the same SessionLocal object so test fixtures and
        # app startup wiring share one database/session factory.
        from app.modules.chat.memory import service as memory_module
        from app.modules.notes import service as note_module
        from app.modules.chat import sessions as sessions_module
        memory_module.SessionLocal = SessionLocal
        note_module.SessionLocal = SessionLocal
        sessions_module.SessionLocal = SessionLocal
        sessions = ChatSessionService()
        chat_session = await sessions.resolve_for_chat(space_id, session_id)
        referenced = await sessions.mention_context(space_id, list(mentioned_session_ids or []), exclude=chat_session.id)
        mentions = [{'id': ref.session_id, 'title': ref.title} for ref in referenced]
        grounded_question = strip_mentions(question, [ref.title for ref in referenced])
        memory = MemoryService(agent=MemoryAgent(llm=llm, router=router), settings=None)
        note_service = NoteService()
        context = await memory.get_context(space_id, budget_tokens=800, session_id=chat_session.id, referenced_sessions=referenced)
        # Resolve follow-up wording without treating conversation memory as evidence.
        rewritten = await QueryRewriter(llm=llm, router=router).rewrite(grounded_question, context)
        resolved_question = rewritten[0]
        extra_queries = [q for q in rewritten if q != resolved_question]
        from app.platform.verification.trail_store import trail
        retriever = NotesAwareRetriever(self._build_retriever(space_id), note_service)
        async def embed_citations(texts):
            return await llm.embed(texts, router.model_for(ModelTier.EMBED))
        driver=VerificationLoopDriver(retriever,AnswerAgent(llm=llm,router=router),PeerReviewerAgent(llm=llm,router=router),RefinementController(self._policies),trail=trail,embedder=embed_citations)
        result=await driver.run(space_id,resolved_question,extra_queries=extra_queries)
        result.session_id=chat_session.id
        async def write_turn():
            async with SessionLocal() as session:
                async with session.begin():
                    await ensure_space_owned(session, space_id)
                    answered_at=max(datetime.now(timezone.utc),asked_at+timedelta(microseconds=1))
                    session.add(Turn(id=str(uuid4()),space_id=space_id,session_id=chat_session.id,role='user',content=question,mentions=mentions or None,created_at=asked_at))
                    session.add(Turn(id=result.turn_id,space_id=space_id,session_id=chat_session.id,role='assistant',content=result.answer,created_at=answered_at,answer_metadata=result.model_dump(mode='json',exclude={'turn_id','answer','session_id'})))
                    await sessions.record_activity(session, chat_session.id, grounded_question)
                    await session.flush()
                    for i,citation in enumerate(result.citations):
                        # Note-derived evidence has virtual chunk ids and no row in chunks;
                        # keep it in the response but do not violate the citations FK.
                        if citation.chunk_id and not citation.chunk_id.startswith('note-'):
                            session.add(Citation(id=str(uuid4()),turn_id=result.turn_id,chunk_id=citation.chunk_id,paper_id=citation.paper_id,section=citation.section,page=citation.page,quote=citation.quote,claim_text=citation.claim_text,match_score=citation.match_score,ordinal=i))
                    await trail.persist_to_session(result.turn_id,result.verification_traces,session)
        await retry_sqlite_locked(write_turn)
        task = asyncio.create_task(memory.on_turn_complete(space_id, None))
        task.add_done_callback(lambda t: logger.warning("Memory background update failed", exc_info=t.exception()) if t.exception() else None)
        return result
