import httpx
from sqlalchemy import text
from app.shared.schemas.common import HealthStatus


class HealthService:
    def __init__(self, settings, session=None):
        self.settings = settings
        self.session = session

    async def check(self):
        return {
            'database': await self._db(),
            # Ollama's HTTP server can stall while a model loads, so probe a cheap
            # endpoint with a tolerant timeout instead of reporting a false outage.
            'ollama': await self._http(self.settings.ollama_base_url, path='/api/tags', timeout=5.0),
            'qdrant': await self._http(self.settings.qdrant_url),
            'redis': {'status': HealthStatus.DEGRADED, 'detail': 'redis client not configured in skeleton'},
            'grobid': await self._http(self.settings.grobid_url),
        }

    async def _db(self):
        if not self.session:
            return {'status': HealthStatus.DEGRADED, 'detail': 'no session'}
        try:
            await self.session.execute(text('SELECT 1'))
            return {'status': HealthStatus.OK}
        except Exception as exc:
            return {'status': HealthStatus.UNAVAILABLE, 'detail': str(exc)}

    async def _http(self, url, path: str = '', timeout: float = 2.0):
        if not url:
            return {'status': HealthStatus.DEGRADED, 'detail': 'not configured'}
        target = url.rstrip('/') + path
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(target)
            return {'status': HealthStatus.OK if r.status_code < 500 else HealthStatus.DEGRADED, 'status_code': r.status_code}
        except httpx.TimeoutException:
            return {'status': HealthStatus.DEGRADED, 'detail': f'timed out after {timeout:g}s (service may be busy)'}
        except Exception as exc:
            return {'status': HealthStatus.UNAVAILABLE, 'detail': str(exc)}
