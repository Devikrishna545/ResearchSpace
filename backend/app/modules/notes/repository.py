from sqlalchemy import select

from app.db.session import SessionLocal
from app.modules.notes.orm import Note


class NoteRepository:
    async def get(self, note_id: str) -> Note | None:
        async with SessionLocal() as session:
            return await session.get(Note, note_id)

    async def list(self, space_id: str, paper_id: str | None = None) -> list[Note]:
        async with SessionLocal() as session:
            stmt = select(Note).where(Note.space_id == space_id).order_by(Note.updated_at.desc())
            if paper_id is not None:
                stmt = stmt.where(Note.paper_id == paper_id)
            return (await session.execute(stmt)).scalars().all()
