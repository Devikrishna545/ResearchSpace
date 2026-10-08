from app.core.config import Settings
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchQuery
from app.modules.discovery.providers.base import SourceAdapter
from app.platform.http import client as source_http
class COREAdapter(SourceAdapter):
    name='core'
    def __init__(self,settings:Settings): self.settings=settings
    async def search(self,query:SearchQuery)->list[RawPaperRecord]:
        if not self.settings.core_api_key: return []
        headers=source_http.source_headers(self.settings)
        headers['Authorization']=f'Bearer {self.settings.core_api_key}'
        r=await source_http.get_source_client().get(
            'https://api.core.ac.uk/v3/search/works',
            params={'q':query.query,'limit':query.limit},
            headers=headers,timeout=source_http.source_timeout(self.settings),
        )
        r.raise_for_status()
        return [RawPaperRecord(source=self.name,title=i.get('title') or '',authors=i.get('authors') or [],year=i.get('yearPublished'),abstract=i.get('abstract'),doi=i.get('doi'),pdf_url=i.get('downloadUrl'),raw_payload=i) for i in r.json().get('results',[])]
