from contextlib import asynccontextmanager
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError
from app.api.v1.router import api_router
from app.core.auth import _active_user_id, prepare_setup_token
from app.core.config import get_settings
from app.db import models
from app.db.session import engine
from app.core.logging import configure_logging
from app.platform.retrieval.ingest_store import rehydrate_from_db
from app.platform.llm.ollama_client import close_shared_ollama_client
from app.platform.http.client import close_shared_source_client
from app.platform.cache.source_results import clear_shared_source_result_cache
from app.core.upload_limit import UploadBodyLimitMiddleware
@asynccontextmanager
async def lifespan(app:FastAPI):
    configure_logging()
    alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    head = ScriptDirectory.from_config(alembic_config).get_current_head()
    async with engine.connect() as conn:
        try:
            version = await conn.exec_driver_sql("SELECT version_num FROM alembic_version")
            current = version.scalar_one_or_none()
        except OperationalError as exc:
            raise RuntimeError("Database is not migrated; run the controlled Alembic upgrade before starting the API") from exc
    if current != head:
        raise RuntimeError(f"Database revision {current!r} is outdated; expected {head!r}. Run the controlled Alembic upgrade.")
    await prepare_setup_token()
    await rehydrate_from_db()
    try:
        yield
    finally:
        try:
            await close_shared_ollama_client()
        finally:
            try:
                await close_shared_source_client()
            finally:
                clear_shared_source_result_cache()
def create_app()->FastAPI:
    settings=get_settings()
    app=FastAPI(title=settings.app_name,version='0.1.0',lifespan=lifespan)
    app.add_middleware(UploadBodyLimitMiddleware)
    # The browser UI is served from a different origin (Next.js dev server), so the
    # API must answer preflight requests. Origins stay configurable and explicit.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )
    @app.middleware("http")
    async def request_owner_context(request, call_next):
        token = _active_user_id.set(None)
        try:
            return await call_next(request)
        finally:
            _active_user_id.reset(token)
    app.include_router(api_router,prefix='/v1')
    return app
app=create_app()
