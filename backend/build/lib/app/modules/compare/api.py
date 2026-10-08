from fastapi import APIRouter, Depends

from app.core.config import Settings
from app.db.session import get_config
from app.modules.compare.service import CompareService

router = APIRouter()


@router.get("/spaces/{space_id}/comparisons")
async def list_comparisons(space_id: str, settings: Settings = Depends(get_config)):
    return await CompareService(settings).list_reports(space_id)


@router.get("/comparisons/{report_id}")
async def get_comparison(report_id: str, settings: Settings = Depends(get_config)):
    return await CompareService(settings).get_report(report_id)
