from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.core.config import Settings
from app.db.session import get_config
from app.modules.compare.grounded import service
from app.modules.compare.grounded.jobs import CompareJobService
from app.modules.compare.grounded.novelty import CorpusService
from app.modules.compare.grounded.tiers import all_tiers, tier_config
from app.platform.llm.ollama_client import get_ollama_client
from app.modules.compare.schemas.grounded import CompareJobRequest, CorpusAddRequest, CorpusMetadataRequest, JobDTO

router = APIRouter()


def _corpus(settings: Settings) -> CorpusService:
    return CorpusService(get_ollama_client().embed, tier_config(settings).embed_model)


@router.post("/spaces/{space_id}/compare-jobs", response_model=JobDTO, status_code=202)
async def start_compare_job(space_id: str, body: CompareJobRequest, settings: Settings = Depends(get_config)):
    return await CompareJobService(settings).start(space_id, body)


@router.get("/spaces/{space_id}/compare-jobs", response_model=list[JobDTO])
async def list_compare_jobs(space_id: str, settings: Settings = Depends(get_config)):
    return await CompareJobService(settings).list(space_id)


@router.get("/compare-jobs/{job_id}", response_model=JobDTO)
async def get_compare_job(job_id: str, settings: Settings = Depends(get_config)):
    return await CompareJobService(settings).get(job_id)


@router.post("/compare-jobs/{job_id}/cancel", response_model=JobDTO)
async def cancel_compare_job(job_id: str, settings: Settings = Depends(get_config)):
    return await CompareJobService(settings).cancel(job_id)


@router.get("/compare-jobs/{job_id}/diagnostics")
async def compare_job_diagnostics(job_id: str):
    return await service.job_diagnostics(job_id)


@router.post("/papers/{paper_id}/evidence/rebuild", response_model=JobDTO, status_code=202)
async def rebuild_evidence(paper_id: str, tier: str | None = Query(default=None, pattern="^(weak|student|deep)$"), settings: Settings = Depends(get_config)):
    return await CompareJobService(settings).start_rebuild(paper_id, tier)


@router.get("/papers/{paper_id}/evidence")
async def get_evidence_ledger(paper_id: str, settings: Settings = Depends(get_config)):
    return await service.evidence_ledger(settings, paper_id)


@router.get("/evidence/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    return await service.artifact_detail(artifact_id)


@router.get("/evidence/artifacts/{artifact_id}/image")
async def get_artifact_image(artifact_id: str):
    return FileResponse(await service.artifact_image(artifact_id), media_type="image/png")


@router.get("/grounded/tiers")
async def grounded_tiers(settings: Settings = Depends(get_config)):
    return {"active": settings.grounded_tier, "tiers": all_tiers(settings)}


@router.get("/corpus")
async def get_corpus(corpus_id: str = "default", settings: Settings = Depends(get_config)):
    corpus = _corpus(settings)
    items = await corpus.items(corpus_id)
    return {"coverage": await corpus.coverage(corpus_id, items),
            "items": [{"id": i.id, "title": i.title, "year": i.year, "doi": i.doi, "field": i.field, "paper_id": i.paper_id,
                       "permission": i.permission, "permission_note": i.permission_note, "embedded": bool(i.embed_model),
                       "added_at": i.added_at} for i in items]}


@router.post("/corpus/papers")
async def add_corpus_papers(body: CorpusAddRequest, settings: Settings = Depends(get_config)):
    return await _corpus(settings).add_library_papers(body.corpus_id, body.paper_ids, body.permission, body.permission_note, body.field)


@router.post("/corpus/items")
async def add_corpus_items(body: CorpusMetadataRequest, settings: Settings = Depends(get_config)):
    return await _corpus(settings).add_metadata(body.corpus_id, [i.model_dump() for i in body.items])


@router.delete("/corpus/items/{item_id}", status_code=204)
async def delete_corpus_item(item_id: str, settings: Settings = Depends(get_config)):
    await _corpus(settings).remove(item_id)
