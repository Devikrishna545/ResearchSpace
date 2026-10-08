"""Fixed hybrid ranker; only the indexed/retrieved units vary between strategies."""

from __future__ import annotations

import json
import math
import re
from collections import Counter

import numpy as np

from .chunking import Chunk, ChunkSet, tokens

CONTEXT_BUDGET = 2400


def terms(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def serialized(contexts: list[Chunk]) -> str:
    return json.dumps([c.payload() for c in contexts], ensure_ascii=False, separators=(",", ":"))


def retrieve(question: str, query_vector: np.ndarray, chunks: ChunkSet,
             vectors: np.ndarray, budget: int = CONTEXT_BUDGET) -> tuple[list[Chunk], list[dict]]:
    candidates = chunks.children
    if len(candidates) != len(vectors):
        raise ValueError("Index/vector count mismatch.")
    query_terms = terms(question)
    documents = [terms(c.title + " " + c.text) for c in candidates]
    df = Counter(t for doc in documents for t in set(doc))
    sparse = [sum(Counter(doc)[t] * math.log((len(documents) + 1) / (df[t] + 1))
                  for t in query_terms) for doc in documents]
    dense = vectors @ query_vector
    dense_order = sorted(range(len(candidates)), key=lambda i: (-float(dense[i]), candidates[i].chunk_id))[:50]
    sparse_order = sorted((i for i, s in enumerate(sparse) if s > 0),
                          key=lambda i: (-sparse[i], candidates[i].chunk_id))[:50]
    scores: dict[int, float] = {}
    for order in (dense_order, sparse_order):
        for rank, i in enumerate(order, 1):
            scores[i] = scores.get(i, 0) + 1 / (60 + rank)
    q = set(query_terms)
    normalized = " " + " ".join(query_terms) + " "
    for i in scores:
        c = candidates[i]
        title = " ".join(terms(c.title))
        scores[i] += len(q & set(terms(c.text))) / max(1, len(q))
        if len(title.split()) >= 2 and " " + title + " " in normalized:
            scores[i] += 2.0
    remaining = sorted(scores, key=lambda i: (-scores[i], candidates[i].chunk_id))[:12]
    selected: list[int] = []
    while remaining:
        def mmr(i: int) -> float:
            if not selected:
                return scores[i]
            words = set(documents[i])
            redundancy = max(len(words & set(documents[j])) / max(1, len(words | set(documents[j])))
                             for j in selected)
            return 0.7 * scores[i] - 0.3 * redundancy
        pick = max(remaining, key=mmr)
        selected.append(pick)
        remaining.remove(pick)
    contexts: list[Chunk] = []
    seen: set[str] = set()
    ranked = []
    for i in selected:
        child = candidates[i]
        context = chunks.parents[child.parent_id] if child.parent_id else child
        ranked.append({"child_id": child.chunk_id, "context_id": context.chunk_id,
                       "dense_score": float(dense[i]), "rank_score": scores[i]})
        if context.chunk_id in seen:
            continue
        seen.add(context.chunk_id)
        if len(contexts) < 8 and tokens(serialized(contexts + [context])) <= budget:
            contexts.append(context)
    return contexts, ranked
