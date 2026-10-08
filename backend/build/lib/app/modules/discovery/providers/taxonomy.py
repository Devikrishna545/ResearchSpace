from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DomainTag:
    tag: str
    label: str
    aliases: tuple[str, ...] = ()
    arxiv_categories: tuple[str, ...] = ()
    source_priority: tuple[str, ...] = ("arxiv", "openalex", "crossref")
    query_terms: tuple[str, ...] = ()
    pubmed_relevant: bool = False

    @property
    def description(self) -> str:
        bits: list[str] = []
        if self.arxiv_categories:
            bits.append("arXiv " + ", ".join(self.arxiv_categories))
        if self.pubmed_relevant:
            bits.append("PubMed relevant")
        if self.query_terms:
            bits.append("bias terms: " + ", ".join(self.query_terms[:3]))
        return "; ".join(bits) or self.label


def _tag(tag: str, label: str, *, aliases=(), arxiv=(), priority=None, terms=(), pubmed=False) -> DomainTag:
    if priority is None:
        priority = ("pubmed", "openalex", "arxiv", "crossref") if pubmed else ("arxiv", "openalex", "crossref")
    return DomainTag(tag=tag, label=label, aliases=tuple(aliases), arxiv_categories=tuple(arxiv), source_priority=tuple(priority), query_terms=tuple(terms), pubmed_relevant=pubmed)


DOMAIN_TAGS: dict[str, DomainTag] = {
    "ml": _tag("ml", "Machine learning", arxiv=("cs.LG", "stat.ML"), terms=("machine learning",)),
    "ai": _tag("ai", "Artificial intelligence", arxiv=("cs.AI",), terms=("artificial intelligence",)),
    "nlp": _tag("nlp", "Natural language processing", arxiv=("cs.CL",), terms=("natural language processing", "language model")),
    "cv": _tag("cv", "Computer vision", arxiv=("cs.CV",), terms=("computer vision",)),
    "robotics": _tag("robotics", "Robotics", arxiv=("cs.RO",), terms=("robotics",)),
    "security": _tag("security", "Security", arxiv=("cs.CR",), terms=("security", "cryptography")),
    "systems": _tag("systems", "Distributed systems", arxiv=("cs.DC",), terms=("distributed systems",)),
    "cs": _tag("cs", "Computer science", arxiv=("cs.*",), terms=("computer science",)),
    "math": _tag("math", "Mathematics", arxiv=("math.*",), terms=("mathematics",)),
    "physics": _tag("physics", "Physics", arxiv=("physics.*",), terms=("physics",)),
    "stats": _tag("stats", "Statistics", aliases=("statistics",), arxiv=("stat.*",), terms=("statistics",)),
    "bio": _tag("bio", "Biology", arxiv=("q-bio.*",), terms=("biology", "biomedical"), pubmed=True),
    "medical": _tag("medical", "Medical and clinical", aliases=("med", "medicine", "clinical", "health"), terms=("medical", "clinical", "health"), pubmed=True),
    "neuro": _tag("neuro", "Neuroscience", arxiv=("q-bio.NC",), terms=("neuroscience", "neurobiology"), pubmed=True),
    "genomics": _tag("genomics", "Genomics", arxiv=("q-bio.GN",), terms=("genomics", "genetics"), pubmed=True),
    "chem": _tag("chem", "Chemistry", aliases=("chemistry",), terms=("chemistry",), priority=("openalex", "crossref", "arxiv")),
    "climate": _tag("climate", "Climate science", terms=("climate", "environmental science"), priority=("openalex", "crossref", "arxiv")),
    "econ": _tag("econ", "Economics and finance", aliases=("economics",), arxiv=("econ.*", "q-fin.*"), terms=("economics", "finance")),
    "edu": _tag("edu", "Education", aliases=("education",), terms=("education", "learning"), priority=("openalex", "crossref", "arxiv")),
}

ALIAS_TO_TAG = {alias.lower(): tag for tag, item in DOMAIN_TAGS.items() for alias in (tag, *item.aliases)}
TAG_RE = re.compile(r"(?<![A-Za-z0-9_])#([A-Za-z][A-Za-z0-9_-]*)")


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ,;\t\r\n")


def parse_tags(text: str) -> tuple[str, list[str], list[str]]:
    matched: list[str] = []
    unknown: list[str] = []
    spans: list[tuple[int, int]] = []
    for match in TAG_RE.finditer(text):
        raw = match.group(1).lower()
        canonical = ALIAS_TO_TAG.get(raw)
        spans.append(match.span())
        if canonical:
            if canonical not in matched:
                matched.append(canonical)
        elif raw not in unknown:
            unknown.append(raw)
    if not spans:
        return _clean_text(text), matched, unknown
    chunks: list[str] = []
    cursor = 0
    for start, end in spans:
        chunks.append(text[cursor:start])
        cursor = end
    chunks.append(text[cursor:])
    return _clean_text("".join(chunks)), matched, unknown


def plan_for_tags(tags: list[str]) -> dict[str, list[str] | str | None]:
    priorities: list[str] = []
    categories: list[str] = []
    terms: list[str] = []
    for tag in tags:
        item = DOMAIN_TAGS.get(tag)
        if not item:
            continue
        for source in item.source_priority:
            if source not in priorities:
                priorities.append(source)
        for category in item.arxiv_categories:
            if category not in categories:
                categories.append(category)
        for term in item.query_terms:
            if term not in terms:
                terms.append(term)
    fragment = " OR ".join(f"cat:{category}" for category in categories) if categories else None
    return {"source_priority": priorities, "arxiv_categories": categories, "arxiv_query_fragment": fragment, "query_terms": terms}


def serializable_tags() -> list[dict[str, object]]:
    return [
        {"tag": f"#{item.tag}", "label": item.label, "aliases": list(item.aliases), "description": item.description}
        for item in DOMAIN_TAGS.values()
    ]
