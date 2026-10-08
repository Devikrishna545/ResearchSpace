"""Per-paper, per-task retrieval. Similarity ranks candidates only; it never proves support."""

import math
import re

from app.modules.compare.grounded.evidence import query_embedding_text
from app.modules.compare.grounded.fact_types import FactType

SECTION_PRIOR_BONUS = 0.08
TABLE_BONUS = 0.05
RELATED_WORK_PENALTY = 0.10
WORD = re.compile(r"[a-z0-9]+")


def cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    denominator = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else None


def lexical(query: str, text: str) -> float:
    q = set(WORD.findall(query.lower()))
    t = set(WORD.findall(text.lower()))
    return len(q & t) / len(q) if q else 0.0


def section_matches(section: str | None, priors: tuple[str, ...]) -> bool:
    return bool(section) and any(section.startswith(prior) for prior in priors)


class Retriever:
    def __init__(self, embedder, embed_model: str, k: int):
        self.embedder = embedder
        self.embed_model = embed_model
        self.k = k
        self._query_vectors: dict[str, list[float] | None] = {}

    async def query_vector(self, query: str) -> list[float] | None:
        if query not in self._query_vectors:
            try:
                self._query_vectors[query] = (await self.embedder([query_embedding_text(query)], self.embed_model))[0]
            except Exception:
                self._query_vectors[query] = None
        return self._query_vectors[query]

    async def for_fact_type(self, artifacts: list, fact_type: FactType, k: int | None = None) -> list:
        vector = await self.query_vector(fact_type.query + " " + fact_type.definition)
        scored = []
        for artifact in artifacts:
            section = artifact.section or ""
            if section.startswith("References"):
                continue
            if artifact.kind == "figure" and not fact_type.table_relevant:
                continue
            similarity = cosine(vector, artifact.embedding_json) if artifact.embed_model == self.embed_model else None
            score = similarity if similarity is not None else 0.5 * lexical(fact_type.query, artifact.text)
            if section_matches(section, fact_type.section_priors):
                score += SECTION_PRIOR_BONUS
            if artifact.kind == "table" and fact_type.table_relevant:
                score += TABLE_BONUS
            if section.startswith("Related Work"):
                score -= RELATED_WORK_PENALTY
            scored.append((score, artifact.page_start or 0, artifact.ordinal, artifact))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        selected = [item[3] for item in scored[: k or self.k]]
        # The abstract/first page often states datasets and questions; keep one for coverage.
        first = next((a for a in artifacts if a.kind in {"text", "abstract"} and (a.page_start or 1) == 1), None)
        if first is not None and first not in selected and fact_type.name in {"research_question", "method", "dataset", "hypothesis"}:
            selected.append(first)
        return sorted(selected, key=lambda a: (a.page_start or 0, a.kind != "text", a.ordinal))
