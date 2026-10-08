from app.core.config import Settings
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchQuery
from app.modules.discovery.providers.base import SourceAdapter
from app.platform.http import client as source_http
from app.shared.text import clean_metadata_text


def _pdf_link(links: list[dict]) -> str | None:
    candidates = []
    for link in links:
        url = link.get('URL')
        content_type = (link.get('content-type') or '').lower().split(';', 1)[0]
        application = (link.get('intended-application') or '').lower()
        if not isinstance(url, str) or not url.startswith('https://'):
            continue
        if content_type not in {'application/pdf', 'application/x-pdf', 'unspecified'}:
            continue
        if application not in {'text-mining', 'similarity-checking'}:
            continue
        candidates.append((content_type in {'application/pdf', 'application/x-pdf'},
                           application == 'text-mining', url))
    return max(candidates, key=lambda item: item[:2])[-1] if candidates else None


class CrossrefAdapter(SourceAdapter):
    name='crossref'
    def __init__(self,settings:Settings): self.settings=settings
    async def search(self,query:SearchQuery)->list[RawPaperRecord]:
        r=await source_http.get_source_client().get(
            'https://api.crossref.org/works',params={'query':query.query,'rows':query.limit},
            headers=source_http.source_headers(self.settings),
            timeout=source_http.source_timeout(self.settings),
        )
        r.raise_for_status()
        return [self.record_from_item(item) for item in r.json().get('message', {}).get('items', [])]

    def record_from_item(self, item: dict) -> RawPaperRecord:
        title=clean_metadata_text((item.get('title') or [''])[0]) or ''
        authors=[' '.join(filter(None,[a.get('given'),a.get('family')])) for a in item.get('author',[])]
        parts=(item.get('published-print') or item.get('published-online') or {}).get('date-parts') or []
        year=parts[0][0] if parts and parts[0] else None
        return RawPaperRecord(source=self.name,title=title,authors=authors,year=year,doi=item.get('DOI'),
                              venue=clean_metadata_text((item.get('container-title') or [None])[0]),
                              abstract=clean_metadata_text(item.get('abstract')),pdf_url=_pdf_link(item.get('link') or []),
                              citation_count=item.get('is-referenced-by-count') or 0,raw_payload=item)
