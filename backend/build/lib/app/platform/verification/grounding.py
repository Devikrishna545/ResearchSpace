import math
import re

from app.modules.chat.schemas.chat import Claim, EvidenceSet

MIN_GROUNDING_SIMILARITY = 0.65


def _windows(text: str, size: int = 500, step: int = 250) -> list[str]:
    if len(text) <= size:
        return [text]
    starts = list(range(0, len(text) - size + 1, step))
    if starts[-1] != len(text) - size:
        starts.append(len(text) - size)
    windows = []
    for start in starts:
        end = min(len(text), start + size)
        left = text.rfind(". ", max(0, start - 100), min(end, start + 100))
        if start and left >= 0:
            start = left + 2
        right = text.find(". ", max(start, end - 100), min(len(text), end + 100))
        if end < len(text) and right >= 0:
            end = right + 1
        windows.append(text[start:end].strip())
    return list(dict.fromkeys([text[:200].strip(), *windows]))


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("Embedding dimensions do not match")
    denominator = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    if not denominator:
        raise ValueError("Zero-length embedding vector")
    return sum(x * y for x, y in zip(a, b)) / denominator


async def match_claims(claims: list[Claim], evidence: EvidenceSet, embedder) -> dict[tuple[str, str], tuple[str, float]]:
    chunks = {chunk.chunk_id: chunk for chunk in evidence.chunks}
    pairs = [(claim, cid) for claim in claims for cid in claim.cited_chunk_ids if cid in chunks]
    if not pairs:
        return {}
    queries = [re.sub(r"\[[^\]]+\]", "", claim.text).strip() for claim, _ in pairs]
    texts = list(dict.fromkeys(
        [query for query in queries if query]
        + [window for _, cid in pairs for window in _windows(chunks[cid].text)]
    ))
    vectors = await embedder(texts)
    if len(vectors) != len(texts):
        raise ValueError("Embedding response length does not match input")
    by_text = dict(zip(texts, vectors))
    matches = {}
    for claim, cid in pairs:
        query = re.sub(r"\[[^\]]+\]", "", claim.text).strip()
        if not query:
            continue
        matches[(claim.claim_id, cid)] = max(
            ((window, _cosine(by_text[query], by_text[window])) for window in _windows(chunks[cid].text)),
            key=lambda item: item[1],
        )
    return matches
