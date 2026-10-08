from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import Settings
from app.db.session import SessionLocal, get_config
from app.modules.spaces.orm.space_memory import SpaceMemory
from app.modules.notes.schemas import NoteCreate, NoteUpdate
from app.modules.notes.service import NoteService

router = APIRouter()


def _note_dto(note):
    return {
        'id': note.id,
        'space_id': note.space_id,
        'paper_id': note.paper_id,
        'content': note.content,
        'source': note.source,
        'chunk_id': note.chunk_id,
        'anchor_quote': note.anchor_quote,
        'anchor_start': note.anchor_start,
        'anchor_end': note.anchor_end,
        'color': note.color,
        'created_at': note.created_at.isoformat() if note.created_at else None,
        'updated_at': note.updated_at.isoformat() if note.updated_at else None,
    }


@router.post('/spaces/{space_id}/notes')
async def create_note(space_id: str, body: NoteCreate):
    return _note_dto(await NoteService().create(space_id, body.paper_id, body.content, body.chunk_id, body.anchor_quote, body.anchor_start, body.anchor_end, body.color))


@router.post('/spaces/{space_id}/papers/{paper_id}/notes/auto')
async def auto_note(space_id: str, paper_id: str, refresh: bool = False, settings: Settings = Depends(get_config)):
    return _note_dto(await NoteService(settings=settings).auto_generate(space_id, paper_id, refresh=refresh))


@router.get('/spaces/{space_id}/notes')
async def list_notes(space_id: str, paper_id: str | None = None):
    return [_note_dto(note) for note in await NoteService().list(space_id, paper_id)]


@router.get('/spaces/{space_id}/papers/{paper_id}/annotations')
async def paper_annotations(space_id: str, paper_id: str):
    return [_note_dto(note) for note in await NoteService().annotations(space_id, paper_id)]


@router.get('/notes/{note_id}')
async def get_note(note_id: str): return _note_dto(await NoteService().get(note_id))


@router.put('/notes/{note_id}')
async def update_note(note_id: str, body: NoteUpdate): return _note_dto(await NoteService().update(note_id, body.content))


@router.delete('/notes/{note_id}')
async def delete_note(note_id: str):
    await NoteService().delete(note_id)
    return {'id': note_id, 'deleted': True}


@router.get('/spaces/{space_id}/memory')
async def get_memory(space_id: str):
    async with SessionLocal() as session:
        memory = await session.get(SpaceMemory, space_id)
    return {
        'space_id': space_id,
        'rolling_summary': memory.rolling_summary if memory else None,
        'findings': list(memory.findings or []) if memory else [],
        'open_questions': list(memory.open_questions or []) if memory else [],
        'updated_at': memory.updated_at.isoformat() if memory and memory.updated_at else None,
    }
