import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from app.modules.chat.agents.memory_agent import MemoryAgent
from app.db.session import SessionLocal
from app.core.ownership import ensure_space_owned
from app.core.exceptions import LLMUnavailableError
from app.platform.llm.model_router import ModelRouter
from app.platform.llm.ollama_client import get_ollama_client
from app.modules.chat.memory.recall import keyword_recall
from app.modules.chat.orm.chat_session import ChatSession
from app.modules.spaces.orm.space_memory import SpaceMemory
from app.modules.chat.orm.turn import Turn
from app.modules.chat.schemas.chat import ConversationContext, ConversationTurnDTO, ReferencedSessionDTO
from app.db.retry import retry_sqlite_locked

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, agent: MemoryAgent | None = None, settings=None, summary_threshold: int = 6, recent_limit: int = 6):
        if agent is not None:
            self.agent = agent
        elif settings is not None:
            llm = get_ollama_client()
            self.agent = MemoryAgent(llm=llm, router=ModelRouter(settings))
        else:
            self.agent = MemoryAgent()
        self.summary_threshold = summary_threshold
        self.recent_limit = recent_limit

    async def get_context(self, space_id: str, budget_tokens: int = 800, session_id: str | None = None,
                          referenced_sessions: list[ReferencedSessionDTO] | None = None) -> ConversationContext:
        async with SessionLocal() as session:
            await ensure_space_owned(session, space_id)
        try:
            # A session-scoped question only sees its own thread, so a fresh chat is not
            # rewritten against another conversation's recent turns.
            scope = Turn.session_id == session_id if session_id else Turn.space_id == space_id
            async with SessionLocal() as session:
                memory = await session.get(SpaceMemory, space_id)
                recent = (await session.execute(select(Turn).where(scope).order_by(Turn.created_at.desc()).limit(self.recent_limit))).scalars().all()
                recent = list(reversed(recent))
                older = (await session.execute(select(Turn).where(scope).order_by(Turn.created_at.desc()).offset(self.recent_limit).limit(50))).scalars().all()
                chat_session = await session.get(ChatSession, session_id) if session_id else None
            recalled = keyword_recall(list(reversed(older)), recent, limit=4)
            context = ConversationContext(
                recent_turns=[self._turn_dto(t) for t in recent],
                rolling_summary=memory.rolling_summary if memory else None,
                recalled_turns=recalled,
                findings=list(memory.findings or []) if memory else [],
                open_questions=list(memory.open_questions or []) if memory else [],
                session_summary=chat_session.summary if chat_session else None,
                referenced_sessions=list(referenced_sessions or []),
            )
            return self._trim(context, budget_tokens)
        except Exception:
            logger.warning("Conversation memory lookup failed", exc_info=True)
            return ConversationContext(referenced_sessions=list(referenced_sessions or []))

    async def on_turn_complete(self, space_id: str, turns=None) -> None:
        async with SessionLocal() as session:
            await ensure_space_owned(session, space_id)
        try:
            async with SessionLocal() as session:
                total = await session.scalar(select(func.count()).select_from(Turn).where(Turn.space_id == space_id)) or 0
                memory = await session.get(SpaceMemory, space_id)
                recent = (await session.execute(select(Turn).where(Turn.space_id == space_id).order_by(Turn.created_at.desc()).limit(self.summary_threshold))).scalars().all()
                recent = list(reversed(recent))
            prior_summary = memory.rolling_summary if memory else None
            prior_findings = {"findings": list(memory.findings or []) if memory else [], "open_questions": list(memory.open_questions or []) if memory else []}
            should_summarize = total >= self.summary_threshold and (total % self.summary_threshold == 0 or not prior_summary)
            summary = prior_summary
            if should_summarize:
                summary = await self.agent.summarize(recent, prior_summary)
            findings = await self.agent.extract_findings(recent, prior_findings)
            await self._upsert(space_id, summary, findings.get("findings", []), findings.get("open_questions", []))
        except (LLMUnavailableError, TimeoutError):
            logger.warning("Conversation memory update skipped because the model was unavailable", exc_info=True)
        except Exception:
            logger.warning("Conversation memory update failed", exc_info=True)

    async def _upsert(self, space_id: str, summary: str | None, findings: list[str], open_questions: list[str]) -> None:
        async def op():
            async with SessionLocal() as session:
                await ensure_space_owned(session, space_id)
                row = await session.get(SpaceMemory, space_id)
                if row:
                    row.rolling_summary = summary
                    row.findings = findings
                    row.open_questions = open_questions
                else:
                    session.add(SpaceMemory(space_id=space_id, rolling_summary=summary, findings=findings, open_questions=open_questions))
                await session.commit()
        await retry_sqlite_locked(op)

    def _turn_dto(self, turn: Turn) -> ConversationTurnDTO:
        return ConversationTurnDTO(role=turn.role, content=turn.content, created_at=turn.created_at.isoformat() if turn.created_at else None)

    def _trim(self, context: ConversationContext, budget_tokens: int) -> ConversationContext:
        # Approximate token budget with whitespace tokens; TODO: use model tokenizer.
        count = 0
        recent = []
        for turn in reversed(context.recent_turns):
            count += len(turn.content.split())
            if count <= budget_tokens:
                recent.append(turn)
        context.recent_turns = list(reversed(recent))
        return context
