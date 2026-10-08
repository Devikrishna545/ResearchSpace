from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from app.core.config import Settings
from app.platform.http import client as source_http
from app.modules.discovery.providers.web_providers.base import WebResult


def _real_url(href: str) -> str:
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(uddg) if uddg else href
    return urljoin("https://lite.duckduckgo.com/lite/", href)


class _DDGLiteParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[WebResult] = []
        self._href: str | None = None
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] | None = None
        self._last_index: int | None = None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        classes = data.get("class", "")
        href = data.get("href", "")
        if tag == "a" and href and ("result-link" in classes or "/l/?" in href or href.startswith("http")):
            self._href = href
            self._title_parts = []
        elif tag in {"td", "span", "div"} and "result-snippet" in classes:
            self._snippet_parts = []

    def handle_data(self, data):
        if self._href is not None:
            self._title_parts.append(data)
        elif self._snippet_parts is not None:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            title = " ".join(" ".join(self._title_parts).split())
            url = _real_url(self._href)
            self._href = None
            if title and url.startswith(("http://", "https://")) and "duckduckgo.com" not in urlparse(url).netloc:
                self.results.append(WebResult(title=title, url=url, source_name="duckduckgo"))
                self._last_index = len(self.results) - 1
        elif self._snippet_parts is not None and tag in {"td", "span", "div"}:
            snippet = " ".join(" ".join(self._snippet_parts).split())
            if snippet and self._last_index is not None:
                prior = self.results[self._last_index]
                self.results[self._last_index] = WebResult(prior.title, prior.url, snippet, prior.source_name)
            self._snippet_parts = None


def parse_lite_results(html: str, limit: int) -> list[WebResult]:
    parser = _DDGLiteParser()
    parser.feed(html)
    seen: set[str] = set()
    out: list[WebResult] = []
    for item in parser.results:
        if item.url in seen:
            continue
        seen.add(item.url)
        out.append(item)
        if len(out) >= limit:
            break
    return out


class DuckDuckGoProvider:
    name = "duckduckgo"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def search(self, query: str, limit: int) -> list[WebResult]:
        response = await source_http.get_source_client().get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query}, headers=source_http.source_headers(self.settings),
            timeout=source_http.source_timeout(self.settings),
        )
        response.raise_for_status()
        return parse_lite_results(response.text, limit)
