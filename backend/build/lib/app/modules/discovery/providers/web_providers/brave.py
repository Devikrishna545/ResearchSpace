from app.core.config import Settings
from app.platform.http import client as source_http
from app.modules.discovery.providers.web_providers.base import WebResult


class BraveProvider:
    name = "brave"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def search(self, query: str, limit: int) -> list[WebResult]:
        if not self.settings.brave_api_key:
            return []
        headers = source_http.source_headers(self.settings)
        headers["X-Subscription-Token"] = self.settings.brave_api_key
        r = await source_http.get_source_client().get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit},
            headers=headers, timeout=source_http.source_timeout(self.settings),
        )
        r.raise_for_status()
        return [
            WebResult(title=i.get("title") or "", url=i.get("url") or "", snippet=i.get("description") or "", source_name="brave")
            for i in (r.json().get("web") or {}).get("results", [])
            if i.get("title") and i.get("url")
        ][:limit]
