from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import Settings
from app.db.session import get_config,get_db_session
from app.platform.observability.health import HealthService
router=APIRouter()
@router.get('/health')
async def health(settings:Settings=Depends(get_config),session:AsyncSession=Depends(get_db_session)): return await HealthService(settings,session).check()
@router.get('/models')
async def models(settings:Settings=Depends(get_config)): return {'small':settings.ollama_model_small,'medium':settings.ollama_model_medium,'large':settings.ollama_model_large,'verify':settings.ollama_model_verify,'embed':settings.ollama_model_embed}
