from fastapi import APIRouter, HTTPException
from app.modules.spaces.schemas import SpaceCreate, SpaceDuplicateRequest, SpaceUpdate
from app.modules.spaces.service import SpaceService

router=APIRouter()

@router.post('')
async def create_space(body:SpaceCreate): return await SpaceService().create(body.name)

@router.get('')
async def list_spaces(): return await SpaceService().list()

@router.get('/{space_id}')
async def get_space(space_id:str):
    space = await SpaceService().get(space_id)
    if not space:
        raise HTTPException(status_code=404, detail='space not found')
    return space

@router.patch('/{space_id}')
async def rename_space(space_id: str, body: SpaceUpdate): return await SpaceService().rename(space_id, body.name)

@router.post('/{space_id}/archive')
async def archive_space(space_id: str): return await SpaceService().set_archived(space_id, True)

@router.post('/{space_id}/unarchive')
async def unarchive_space(space_id: str): return await SpaceService().set_archived(space_id, False)

@router.post('/{space_id}/duplicate')
async def duplicate_space(space_id: str, body: SpaceDuplicateRequest | None = None):
    body = body or SpaceDuplicateRequest()
    return await SpaceService().duplicate(space_id, copy_notes=body.copy_notes, name=body.name)

@router.delete('/{space_id}')
async def delete_space(space_id: str): return await SpaceService().delete(space_id)

@router.get('/{space_id}/search-content')
async def search_content(space_id: str, q: str): return await SpaceService().search_content(space_id, q)

@router.get('/{space_id}/turns')
async def list_turns(space_id: str, limit: int = 100):
    """Conversation history for the space, oldest first, so a client can rehydrate a chat."""
    return await SpaceService().list_turns(space_id, limit=limit)
