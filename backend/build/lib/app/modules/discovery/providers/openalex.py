from app.core.config import Settings
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchQuery
from app.modules.discovery.providers.base import SourceAdapter
from app.platform.http import client as source_http
class OpenAlexAdapter(SourceAdapter):
    name='openalex'
    def __init__(self,settings:Settings,contact_email:str|None=None):
        self.settings=settings
        self.contact_email=contact_email
    async def search(self,query:SearchQuery)->list[RawPaperRecord]:
        params={'search':query.query,'per-page':query.limit}
        contact=source_http.validate_openalex_contact(self.contact_email) if self.contact_email else None
        if contact:
            params['mailto']=contact
        r=await source_http.get_source_client().get(
            'https://api.openalex.org/works',params=params,
            headers=source_http.source_headers(self.settings, contact=contact, allow_configured_contact=False),
            timeout=source_http.source_timeout(self.settings),
        )
        r.raise_for_status()
        out=[]
        for i in r.json().get('results',[]):
            doi=i.get('doi')
            if doi and doi.startswith('https://doi.org/'): doi=doi.replace('https://doi.org/','')
            authors=[a.get('author',{}).get('display_name','') for a in i.get('authorships',[])]
            out.append(RawPaperRecord(source=self.name,title=i.get('title') or '',authors=authors,year=i.get('publication_year'),doi=doi,openalex_id=i.get('id'),citation_count=i.get('cited_by_count') or 0,oa_status=(i.get('open_access') or {}).get('oa_status'),pdf_url=((i.get('primary_location') or {}).get('pdf_url')),raw_payload=i))
        return out
