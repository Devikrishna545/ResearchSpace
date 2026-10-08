from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str = ""
    source_name: str = "web"


class WebSearchProvider(Protocol):
    name: str

    async def search(self, query: str, limit: int) -> list[WebResult]: ...


def provider_from_settings(settings: Settings) -> WebSearchProvider:
    from app.modules.discovery.providers.web_providers.brave import BraveProvider
    from app.modules.discovery.providers.web_providers.duckduckgo import DuckDuckGoProvider
    from app.modules.discovery.providers.web_providers.searxng import SearxngProvider
    from app.modules.discovery.providers.web_providers.tavily import TavilyProvider

    provider = (settings.web_search_provider or "duckduckgo").lower()
    if provider == "brave" and settings.brave_api_key:
        return BraveProvider(settings)
    if provider == "tavily" and settings.tavily_api_key:
        return TavilyProvider(settings)
    if provider == "searxng" and settings.searxng_url:
        return SearxngProvider(settings)
    return DuckDuckGoProvider(settings)
