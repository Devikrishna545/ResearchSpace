from difflib import SequenceMatcher
import re

from app.modules.papers.schemas.paper import Paper
from app.shared.identifiers import canonical_arxiv_id, canonical_doi
from app.shared.text import normalize_title

TITLE_SIMILARITY_THRESHOLD = 0.90


class Deduplicator:
    """Merges duplicate records across sources.

    Identifier matches (DOI/arXiv/PMID) resolve through hash lookups, and the
    expensive fuzzy-title comparison is gated by cheap pre-filters so a fan-out
    of ~100 records does not degenerate into thousands of SequenceMatcher runs.
    """

    def merge(self, papers: list[Paper]) -> list[Paper]:
        out: list[Paper] = []
        norms: list[str] = []
        authors: list[str | None] = []
        by_doi: dict[str, int] = {}
        by_arxiv: dict[str, int] = {}
        by_pmid: dict[str, int] = {}

        def index(i: int, paper: Paper) -> None:
            doi = canonical_doi(paper.doi)
            arxiv = canonical_arxiv_id(paper.arxiv_id)
            if doi:
                by_doi.setdefault(doi, i)
            if arxiv:
                by_arxiv.setdefault(arxiv, i)
            if paper.pmid:
                by_pmid.setdefault(paper.pmid, i)

        for paper in papers:
            norm = normalize_title(paper.title)
            author = self._first_author_surname(paper)
            i = self._find_duplicate(out, norms, authors, by_doi, by_arxiv, by_pmid, paper, norm, author)
            if i is None:
                out.append(paper)
                norms.append(norm)
                authors.append(author)
                index(len(out) - 1, paper)
            else:
                out[i] = self._merge_two(out[i], paper)
                index(i, out[i])
                # The merged record may gain a title/author it lacked before.
                norms[i] = normalize_title(out[i].title)
                authors[i] = self._first_author_surname(out[i])
        return out

    def _find_duplicate(self, existing, norms, authors, by_doi, by_arxiv, by_pmid, paper, norm, author):
        doi = canonical_doi(paper.doi)
        if doi and doi in by_doi:
            return by_doi[doi]
        arxiv = canonical_arxiv_id(paper.arxiv_id)
        if arxiv and arxiv in by_arxiv:
            return by_arxiv[arxiv]
        if paper.pmid and paper.pmid in by_pmid:
            return by_pmid[paper.pmid]
        if not norm:
            return None

        length = len(norm)
        tokens = set(norm.split())
        for i, cur in enumerate(existing):
            cur_norm = norms[i]
            if not cur_norm:
                continue
            # Cheap gates before the O(n*m) similarity computation.
            if abs(len(cur_norm) - length) > length * 0.25:
                continue
            if paper.year and cur.year and paper.year != cur.year:
                continue
            cur_author = authors[i]
            if author and cur_author and author != cur_author:
                continue
            if tokens and not (tokens & set(cur_norm.split())):
                continue
            matcher = SequenceMatcher(None, norm, cur_norm)
            if matcher.real_quick_ratio() < TITLE_SIMILARITY_THRESHOLD:
                continue
            if matcher.quick_ratio() < TITLE_SIMILARITY_THRESHOLD:
                continue
            if matcher.ratio() >= TITLE_SIMILARITY_THRESHOLD:
                return i
        return None

    @staticmethod
    def _first_author_surname(paper: Paper) -> str | None:
        details = Deduplicator._author_details(paper.authors[0]) if paper.authors else None
        return details[0][0] if details else None

    @staticmethod
    def _author_details(name: str) -> tuple[tuple[str, str], str, bool] | None:
        if ',' in name:
            surname, given = name.split(',', 1)
            surname = ' '.join(surname.split())
            given = ' '.join(given.replace('.', ' ').split())
        else:
            words = name.replace('.', ' ').split()
            if len(words) < 2:
                return None
            if len(words[-1]) == 1 and len(words[0]) > 1:
                surname, given = words[0], words[-1]
            else:
                surname, given = words[-1], words[0]
        if not surname or not given:
            return None
        return (surname.casefold(), given[0].casefold()), given.casefold(), len(given) == 1

    @classmethod
    def _merge_authors(cls, existing: list[str], incoming: list[str]) -> list[str]:
        def normalized(name: str) -> str:
            return re.sub(r'[\s.,]+', ' ', name).strip().casefold()

        left = [cls._author_details(name) for name in existing]
        right = [cls._author_details(name) for name in incoming]
        result = existing.copy()
        seen = {normalized(name) for name in result}
        for index, name in enumerate(incoming):
            details = right[index]
            if details and index < len(existing) and left[index] and left[index][0] == details[0]:
                signature = details[0]
                if (sum(item is not None and item[0] == signature for item in left) == 1
                        and sum(item is not None and item[0] == signature for item in right) == 1):
                    prior = left[index]
                    if prior[2] and not details[2]:
                        seen.discard(normalized(result[index]))
                        result[index] = name
                        seen.add(normalized(name))
                        continue
                    if details[2] or prior[1] == details[1]:
                        continue
            key = normalized(name)
            if key not in seen:
                result.append(name)
                seen.add(key)
        return result

    def _merge_two(self, a, b):
        data = a.model_dump()
        for k, v in b.model_dump().items():
            if k == 'authors':
                data[k] = self._merge_authors(data.get(k) or [], v or [])
            elif k == 'citation_count':
                data[k] = max(data.get(k) or 0, v or 0)
            elif k == 'raw_payload':
                data[k] = {**(data.get(k) or {}), b.source or 'source': v}
            elif not data.get(k) and v:
                data[k] = v
        return Paper(**data)
