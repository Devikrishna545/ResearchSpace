import re

_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)\s*", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_ARXIV_DATACITE_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)
_NEW_ARXIV_ID_RE = re.compile(r"^\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}$", re.IGNORECASE)
_OLD_ARXIV_ID_RE = re.compile(r"^[a-z][a-z0-9.-]*/\d{2}(?:0[1-9]|1[0-2])\d{3}$", re.IGNORECASE)

def canonical_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _DOI_PREFIX_RE.sub("", value.strip()).strip()
    return cleaned.lower() or None

def canonical_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.lower().startswith("arxiv:"):
        cleaned = cleaned[6:].strip()
    url_identifier = re.search(r"/(?:abs|pdf)/(.+)$", cleaned, re.IGNORECASE)
    if url_identifier:
        cleaned = url_identifier.group(1).rstrip("/ ")
    if cleaned.endswith(".pdf"):
        cleaned = cleaned[:-4]
    # Store arXiv identifiers without version suffixes so v1/v2 records dedupe.
    cleaned = _ARXIV_VERSION_RE.sub("", cleaned).strip()
    return cleaned.lower() or None

def arxiv_id_from_doi(value: str | None) -> str | None:
    """Only the arXiv DataCite DOI namespace encodes an authoritative arXiv ID."""
    doi = canonical_doi(value)
    match = _ARXIV_DATACITE_RE.fullmatch(doi) if doi else None
    if not match:
        return None
    identifier = canonical_arxiv_id(match.group(1))
    if identifier and (_NEW_ARXIV_ID_RE.fullmatch(identifier) or _OLD_ARXIV_ID_RE.fullmatch(identifier)):
        return identifier
    return None

# Backwards-compatible alias used by older callers/tests.
def clean_doi(value: str | None) -> str | None:
    return canonical_doi(value)
