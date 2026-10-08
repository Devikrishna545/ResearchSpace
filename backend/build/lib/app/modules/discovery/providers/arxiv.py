import xml.etree.ElementTree as ET
from app.core.config import Settings
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchQuery
from app.modules.discovery.providers.base import SourceAdapter
from app.platform.http import client as source_http
from app.shared.identifiers import canonical_arxiv_id


class ArxivAdapter(SourceAdapter):
    name = "arxiv"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _search_query(self, query: SearchQuery) -> str:
        text = f"all:{query.query}" if query.query else "all:*"
        if query.arxiv_categories:
            cats = " OR ".join(f"cat:{category}" for category in query.arxiv_categories)
            return f"{text} AND ({cats})"
        return text

    async def search(self, query: SearchQuery) -> list[RawPaperRecord]:
        params = {"search_query": self._search_query(query), "start": 0, "max_results": query.limit}
        r = await source_http.get_source_client().get(
            "https://export.arxiv.org/api/query",
            params=params, headers=source_http.source_headers(self.settings),
            timeout=source_http.source_timeout(self.settings),
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        out = []
        for e in root.findall("a:entry", ns):
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
            authors = [a.findtext("a:name", default="", namespaces=ns) for a in e.findall("a:author", ns)]
            arxiv_id = canonical_arxiv_id(e.findtext("a:id", default="", namespaces=ns)) or ""
            summary = (e.findtext("a:summary", default="", namespaces=ns) or "").strip()
            primary = e.find("arxiv:primary_category", ns)
            categories = [c.attrib.get("term", "") for c in e.findall("a:category", ns) if c.attrib.get("term")]
            primary_category = primary.attrib.get("term") if primary is not None else (categories[0] if categories else None)
            pdf = None
            for link in e.findall("a:link", ns):
                if link.attrib.get("title") == "pdf":
                    pdf = link.attrib.get("href")
            out.append(RawPaperRecord(source=self.name, title=title, authors=authors, arxiv_id=arxiv_id, abstract=summary, pdf_url=pdf, raw_payload={"id": arxiv_id, "primary_category": primary_category, "categories": categories}))
        return out
