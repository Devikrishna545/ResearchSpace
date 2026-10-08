from collections.abc import AsyncIterator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import get_settings
def configure_sqlite_pragmas(async_engine):
    @event.listens_for(async_engine.sync_engine, 'connect')
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.close()
    return async_engine
_settings=get_settings(); engine=configure_sqlite_pragmas(create_async_engine(_settings.database_url,future=True,echo=False)); SessionLocal=async_sessionmaker(engine,expire_on_commit=False,class_=AsyncSession)
async def get_db_session()->AsyncIterator[AsyncSession]:
    async with SessionLocal() as session: yield session
def get_config(): return get_settings()
