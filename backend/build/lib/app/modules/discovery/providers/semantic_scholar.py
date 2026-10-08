from app.core.config import Settings
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchQuery
from app.modules.discovery.providers.base import SourceAdapter
from app.platform.http import client as source_http
class SemanticScholarAdapter(SourceAdapter):
    name='semantic_scholar'
    def __init__(self,settings:Settings):
        self.settings=settings
        self.breaker_failure_threshold = 3 if settings.semantic_scholar_api_key else 1
    async def search(self,query:SearchQuery)->list[RawPaperRecord]:
        if not self.settings.semantic_scholar_api_key:
            raise RuntimeError('semantic_scholar skipped: configure SEMANTIC_SCHOLAR_API_KEY to avoid unauthenticated rate limits')
        headers=source_http.source_headers(self.settings)
        headers['x-api-key']=self.settings.semantic_scholar_api_key
        r=await source_http.get_source_client().get(
            'https://api.semanticscholar.org/graph/v1/paper/search',
            params={'query':query.query,'limit':query.limit,'fields':'title,authors,year,abstract,citationCount,externalIds,venue,openAccessPdf'},
            headers=headers,timeout=source_http.source_timeout(self.settings),
        )
        r.raise_for_status()
        return [RawPaperRecord(source=self.name,title=i.get('title') or '',authors=[a.get('name','') for a in i.get('authors',[])],year=i.get('year'),venue=i.get('venue'),abstract=i.get('abstract'),doi=(i.get('externalIds') or {}).get('DOI'),arxiv_id=(i.get('externalIds') or {}).get('ArXiv'),pmid=(i.get('externalIds') or {}).get('PubMed'),citation_count=i.get('citationCount') or 0,pdf_url=(i.get('openAccessPdf') or {}).get('url'),raw_payload=i) for i in r.json().get('data',[])]
