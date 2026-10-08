from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.modules.chat.agents.memory_agent import MemoryAgent
from app.core.config import Settings
from app.db.session import SessionLocal, get_config
from app.platform.llm.model_router import ModelRouter
from app.platform.llm.ollama_client import get_ollama_client
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.chat.schemas.chat_session import ChatRequest, ChatSessionCreate, ChatSessionStatus, ChatSessionUpdate
from app.modules.chat.service import QAOrchestrator
from app.modules.chat.sessions import ChatSessionService

router = APIRouter()


@router.post('/spaces/{space_id}/chat')
async def chat(space_id: str, body: ChatRequest, settings: Settings = Depends(get_config)):
    async with SessionLocal() as session:
        if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id).limit(1)):
            raise HTTPException(status_code=404, detail='space not found')
    return await QAOrchestrator(settings).answer(space_id, body.question, session_id=body.session_id,
                                                 mentioned_session_ids=body.mentioned_session_ids)


@router.get('/spaces/{space_id}/chat-sessions')
async def list_chat_sessions(space_id: str, status: ChatSessionStatus = 'active', q: str | None = Query(None, max_length=200),
                             limit: int = Query(200, ge=1, le=500)):
    """Sessions ordered pinned-first then by recent activity; `q` matches titles and message text."""
    return await ChatSessionService().list(space_id, status=status, q=q, limit=limit)


@router.post('/spaces/{space_id}/chat-sessions')
async def create_chat_session(space_id: str, body: ChatSessionCreate | None = None):
    return await ChatSessionService().create(space_id, (body or ChatSessionCreate()).title)


@router.get('/chat-sessions/{session_id}')
async def get_chat_session(session_id: str):
    return await ChatSessionService().get(session_id)


@router.patch('/chat-sessions/{session_id}')
async def update_chat_session(session_id: str, body: ChatSessionUpdate):
    return await ChatSessionService().update(session_id, title=body.title, pinned=body.pinned, archived=body.archived)


@router.delete('/chat-sessions/{session_id}')
async def delete_chat_session(session_id: str):
    return await ChatSessionService().delete(session_id)


@router.get('/chat-sessions/{session_id}/turns')
async def list_chat_session_turns(session_id: str, limit: int = Query(200, ge=1, le=1000)):
    return await ChatSessionService().list_turns(session_id, limit=limit)


@router.post('/chat-sessions/{session_id}/compress')
async def compress_chat_session(session_id: str, settings: Settings = Depends(get_config)):
    agent = MemoryAgent(llm=get_ollama_client(), router=ModelRouter(settings))
    return await ChatSessionService().compress(session_id, agent)
