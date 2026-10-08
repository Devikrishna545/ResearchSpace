from app.modules.discovery.providers.base import SourceAdapter
class UnpaywallAdapter(SourceAdapter):
    name='unpaywall'
    async def search(self,query): return []
