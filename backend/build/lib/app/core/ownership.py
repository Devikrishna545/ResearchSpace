from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.core.auth import current_user, owner_id
from app.db.session import SessionLocal
from app.modules.chat.orm.chat_session import ChatSession
from app.modules.papers.orm.chunk import Chunk
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.notes.orm import Note
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.chat.orm.turn import Turn
from app.modules.auth.orm.user import User


async def ensure_space_owned(db, space_id: str) -> None:
    if not await db.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id())):
        raise HTTPException(404, "Resource not found")


async def require_owned_resources(request: Request, user: User = Depends(current_user)) -> None:
    ids = request.path_params
    space_id = ids.get("space_id")
    paper_id = ids.get("paper_id")
    async with SessionLocal() as db:
        if space_id and not await db.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == user.id)):
            raise HTTPException(404, "Resource not found")
        if paper_id:
            owned_paper = (
                select(Paper.id).join(Pin, Pin.paper_id == Paper.id)
                .join(ResearchSpace, ResearchSpace.id == Pin.space_id)
                .where(Paper.id == paper_id, Paper.owner_id == user.id, ResearchSpace.user_id == user.id)
            )
            if space_id:
                owned_paper = owned_paper.where(Pin.space_id == space_id)
            if not await db.scalar(owned_paper.limit(1)):
                raise HTTPException(404, "Resource not found")
        for key, model in (("note_id", Note), ("report_id", ComparisonReport), ("turn_id", Turn), ("session_id", ChatSession)):
            if ids.get(key) and not await db.scalar(
                select(model.id).join(ResearchSpace, model.space_id == ResearchSpace.id)
                .where(model.id == ids[key], ResearchSpace.user_id == user.id).limit(1)
            ):
                raise HTTPException(404, "Resource not found")
        if request.method in {"POST", "PUT", "PATCH"} and space_id:
            if request.url.path.endswith("/compare-jobs"):
                body = await request.json()
                paper_ids = body.get("paper_ids", [])
                if not isinstance(paper_ids, list):
                    raise HTTPException(422, "Invalid paper IDs")
                for selected in paper_ids:
                    if not await db.scalar(
                        select(Pin.id).join(Paper, Paper.id == Pin.paper_id)
                        .where(Pin.space_id == space_id, Pin.paper_id == selected, Paper.owner_id == user.id)
                    ):
                        raise HTTPException(404, "Resource not found")
            elif request.url.path.endswith("/notes"):
                body = await request.json()
                selected = body.get("paper_id")
                if selected and not await db.scalar(
                    select(Pin.id).join(Paper, Paper.id == Pin.paper_id)
                    .where(Pin.space_id == space_id, Pin.paper_id == selected, Paper.owner_id == user.id)
                ):
                    raise HTTPException(404, "Resource not found")
                chunk_id = body.get("chunk_id")
                if chunk_id and not await db.scalar(
                    select(Chunk.id).join(Pin, Pin.paper_id == Chunk.paper_id)
                    .join(Paper, Paper.id == Chunk.paper_id)
                    .where(Chunk.id == chunk_id, Pin.space_id == space_id, Paper.owner_id == user.id)
                ):
                    raise HTTPException(404, "Resource not found")
