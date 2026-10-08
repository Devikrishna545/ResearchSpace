import re
from app.core.config import Settings
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchQuery
from app.modules.discovery.providers.base import SourceAdapter
from app.platform.http import client as source_http


class PubMedAdapter(SourceAdapter):
    name = "pubmed"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _params(self, **params):
        if self.settings.pubmed_api_key:
            params["api_key"] = self.settings.pubmed_api_key
        return params

    async def search(self, query: SearchQuery) -> list[RawPaperRecord]:
        client = source_http.get_source_client()
        headers = source_http.source_headers(self.settings)
        timeout = source_http.source_timeout(self.settings)
        search = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params=self._params(db="pubmed", term=query.query, retmode="json", retmax=query.limit, sort="relevance"),
            headers=headers, timeout=timeout,
        )
        search.raise_for_status()
        ids = search.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        summary = await client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params=self._params(db="pubmed", id=",".join(ids), retmode="json"),
            headers=headers, timeout=timeout,
        )
        summary.raise_for_status()
        result = summary.json().get("result", {})
        return [record for pmid in result.get("uids", ids) if (record := self._record_from_summary(pmid, result.get(pmid) or {}))]

    def _record_from_summary(self, pmid: str, item: dict) -> RawPaperRecord | None:
        title = (item.get("title") or "").strip()
        if not title:
            return None
        authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]
        pubdate = item.get("pubdate") or item.get("epubdate") or ""
        year_match = re.search(r"(18|19|20)\d{2}", pubdate)
        doi = None
        for article_id in item.get("articleids", []) or []:
            if str(article_id.get("idtype", "")).lower() == "doi":
                doi = article_id.get("value")
                break
        return RawPaperRecord(
            source=self.name,
            title=title,
            authors=authors,
            year=int(year_match.group(0)) if year_match else None,
            venue=item.get("fulljournalname") or item.get("source"),
            doi=doi,
            pmid=str(pmid),
            raw_payload=item,
        )
