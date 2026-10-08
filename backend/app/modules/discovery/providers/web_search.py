from app.core.config import Settings
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.providers.base import SourceAdapter
from app.modules.discovery.providers.web_providers import WebSearchProvider, provider_from_settings


class WebSearchAdapter(SourceAdapter):
    name = 'web'

    def __init__(self, settings: Settings, provider: WebSearchProvider | None = None):
        self.settings = settings
        self.provider = provider or provider_from_settings(settings)

    async def search(self, query):
        terms = " ".join(dict.fromkeys([query.query, *query.query_terms]))
        results = await self.provider.search(terms, min(query.limit, 8))
        return [
            RawPaperRecord(
                source='web',
                title=item.title,
                abstract=item.snippet,
                pdf_url=item.url,
                url=item.url,
                raw_payload={'url': item.url, 'provider': item.source_name},
            )
            for item in results
        ]
