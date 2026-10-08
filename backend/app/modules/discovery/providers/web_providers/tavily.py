from app.core.config import Settings
from app.platform.http import client as source_http
from app.modules.discovery.providers.web_providers.base import WebResult


class TavilyProvider:
    name = "tavily"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def search(self, query: str, limit: int) -> list[WebResult]:
        if not self.settings.tavily_api_key:
            return []
        r = await source_http.get_source_client().post(
            "https://api.tavily.com/search",
            json={"api_key": self.settings.tavily_api_key, "query": query, "max_results": limit},
            headers=source_http.source_headers(self.settings),
            timeout=source_http.source_timeout(self.settings),
        )
        r.raise_for_status()
        return [
            WebResult(title=i.get("title") or "", url=i.get("url") or "", snippet=i.get("content") or "", source_name="tavily")
            for i in r.json().get("results", [])
            if i.get("title") and i.get("url")
        ][:limit]
