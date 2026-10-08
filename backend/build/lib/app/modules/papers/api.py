from fastapi import APIRouter,File,Form,HTTPException,Query,UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from sqlalchemy import select
from app.db.session import SessionLocal
from app.modules.papers.orm.chunk import Chunk
from app.modules.spaces.orm.pin import Pin
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.papers.schemas.web_capture import WebCaptureRequest
from app.modules.papers.service import PaperService
from app.modules.papers.ingestion.upload import PdfUploadService, uploaded_pdf_path
router=APIRouter(); _service=PaperService()
_upload_service=PdfUploadService()
class BulkUnpinRequest(BaseModel):
    paper_ids:list[str]=Field(min_length=1,max_length=200)
@router.post('/spaces/{space_id}/papers')
async def pin_paper(space_id:str,body:RawPaperRecord,background:bool=False):
    async with SessionLocal() as session:
        if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id==space_id).limit(1)):
            raise HTTPException(status_code=404,detail='space not found')
    if background:
        return await _service.pin_and_ingest_background(space_id,body)
    return await _service.pin_and_ingest(space_id,body)
@router.post('/spaces/{space_id}/papers/unpin')
async def unpin_many(space_id:str,body:BulkUnpinRequest):
    return await _service.unpin_many(space_id,body.paper_ids)
@router.post('/spaces/{space_id}/papers/upload')
async def upload_pdf(space_id:str,file:UploadFile=File(...),title:str|None=Form(None)):
    return await _upload_service.ingest(space_id,file,title)
@router.post('/spaces/{space_id}/web-captures')
async def capture_web(space_id:str,body:WebCaptureRequest):
    async with SessionLocal() as session:
        if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id==space_id).limit(1)):
            raise HTTPException(status_code=404,detail='space not found')
    try:
        return await _service.capture_web(space_id, body.url, body.title, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
@router.get('/papers/{paper_id}')
async def get_paper(paper_id:str):
    paper = await _service.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404,detail='paper not found')
    return paper
@router.get('/papers/{paper_id}/content')
async def paper_content(paper_id:str,space_id:str|None=None,limit:int=Query(200,ge=1,le=500)):
    """Return reader content, capped to 200 chunks by default (500 max)."""
    async with SessionLocal() as session:
        paper=await session.get(Paper,paper_id)
        if not paper:
            raise HTTPException(status_code=404,detail='paper not found')
        if space_id is not None:
            pin=await session.scalar(select(Pin.id).where(Pin.space_id==space_id,Pin.paper_id==paper_id).limit(1))
            if not pin:
                raise HTTPException(status_code=404,detail='paper not pinned to space')
        rows=(await session.execute(select(Chunk).where(Chunk.paper_id==paper_id).order_by(Chunk.ordinal).limit(limit))).scalars().all()
    raw=paper.raw_payload or {}
    return {
        'paper': {
            'id': paper.id,
            'title': paper.title,
            'authors': paper.authors or [],
            'year': paper.year,
            'venue': paper.venue,
            'doi': paper.doi,
            'arxiv_id': paper.arxiv_id,
            'source': paper.source,
            'url': raw.get('url') or raw.get('landing_url') or raw.get('source_url'),
            'pdf_url': paper.pdf_url,
            'local_pdf_available': uploaded_pdf_path(paper_id).is_file() and not uploaded_pdf_path(paper_id).is_symlink(),
            'ingest_status': paper.ingest_status,
        },
        'chunks': [{'chunk_id': row.id, 'ordinal': row.ordinal, 'section': row.section, 'page': row.page, 'text': row.text} for row in rows],
    }
@router.get('/papers/{paper_id}/file')
async def uploaded_pdf(paper_id:str):
    async with SessionLocal() as session:
        paper=await session.get(Paper,paper_id)
    if not paper:
        raise HTTPException(404,'paper not found')
    path=uploaded_pdf_path(paper_id)
    if not path.is_file() or path.is_symlink():
        raise HTTPException(404,'uploaded PDF not found')
    return FileResponse(path,media_type='application/pdf',filename=f'{paper.title}.pdf',
                        content_disposition_type='inline',headers={'Cache-Control':'private, no-store'})
@router.get('/papers/{paper_id}/status')
async def paper_status(paper_id:str):
    async with SessionLocal() as session:
        status=await session.scalar(select(Paper.ingest_status).where(Paper.id==paper_id).limit(1))
    if status is None:
        raise HTTPException(status_code=404,detail='paper not found')
    return {'paper_id':paper_id,'status':status}
@router.delete('/spaces/{space_id}/papers/{paper_id}')
async def unpin(space_id:str,paper_id:str):
    async with SessionLocal() as session:
        pin=await session.scalar(select(Pin.id).where(Pin.space_id==space_id,Pin.paper_id==paper_id).limit(1))
        if not pin:
            raise HTTPException(status_code=404,detail='pin not found')
    return await _service.unpin(space_id,paper_id)
