"""Four strategies over one canonical, offset-addressable source corpus."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Callable

import numpy as np
import tiktoken

from .corpus import Block, Document

STRATEGIES = ("baseline", "research_aware", "hierarchical_recursive",
              "hierarchical_semantic_structured")


@lru_cache(maxsize=1)
def encoding():
    return tiktoken.get_encoding("cl100k_base")


def tokens(text: str) -> int:
    return len(encoding().encode(text, disallowed_special=()))


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    start: int
    end: int
    text: str
    page: int | None
    section: str
    subsection: str
    kind: str
    parent_id: str | None = None

    def payload(self) -> dict:
        return {"chunk_id": self.chunk_id, "paper": self.title, "page": self.page,
                "section": self.section, "subsection": self.subsection,
                "kind": self.kind, "text": self.text}


@dataclass
class ChunkSet:
    strategy: str
    children: list[Chunk]
    parents: dict[str, Chunk]
    build_seconds: float = 0.0
    semantic_embedding_seconds: float = 0.0

    def payload(self) -> dict:
        return {"strategy": self.strategy, "children": [asdict(c) for c in self.children],
                "parents": {key: asdict(c) for key, c in self.parents.items()},
                "build_seconds": self.build_seconds,
                "semantic_embedding_seconds": self.semantic_embedding_seconds}

    @classmethod
    def from_payload(cls, data: dict) -> ChunkSet:
        return cls(data["strategy"], [Chunk(**row) for row in data["children"]],
                   {key: Chunk(**row) for key, row in data["parents"].items()},
                   data["build_seconds"], data["semantic_embedding_seconds"])


def token_spans(text: str, start: int, end: int, size: int, overlap: int = 0) -> list[tuple[int, int]]:
    if not 0 <= overlap < size:
        raise ValueError("Overlap must be between zero and chunk size.")
    fragment = text[start:end]
    ids = encoding().encode(fragment, disallowed_special=())
    if not ids:
        return []
    _, offsets = encoding().decode_with_offsets(ids)
    offsets.append(len(fragment))
    result: list[tuple[int, int]] = []
    lo = 0
    while lo < len(ids):
        hi = min(lo + size, len(ids))
        while hi > lo + 1 and tokens(fragment[offsets[lo]:offsets[hi]]) > size:
            hi -= 1
        left, right = start + offsets[lo], start + offsets[hi]
        if right > left:
            result.append((left, right))
        if hi == len(ids):
            break
        lo = max(lo + 1, hi - overlap)
    return result


def recursive_spans(text: str, start: int, end: int, limit: int = 320,
                    separators: tuple[str, ...] = (r"\n\n+", r"(?<=[.!?])\s+", r"\s+")) -> list[tuple[int, int]]:
    if tokens(text[start:end]) <= limit:
        return [(start, end)] if start < end else []
    if not separators:
        return token_spans(text, start, end, limit)
    cuts = [start] + [start + m.end() for m in re.finditer(separators[0], text[start:end])] + [end]
    pieces: list[tuple[int, int]] = []
    pending = start
    for left, right in zip(cuts, cuts[1:]):
        if tokens(text[pending:right]) > limit:
            if pending < left:
                pieces.append((pending, left))
            if tokens(text[left:right]) > limit:
                pieces.extend(recursive_spans(text, left, right, limit, separators[1:]))
                pending = right
            else:
                pending = left
    if pending < end:
        pieces.append((pending, end))
    return pieces


def make_chunk(doc: Document, prefix: str, ordinal: int, span: tuple[int, int],
               parent_id: str | None = None) -> Chunk:
    start, end = span
    blocks = [b for b in doc.blocks if b.end > start and b.start < end]
    if not blocks or not start < end:
        raise ValueError("Chunk does not overlap source evidence.")
    first = blocks[0]
    sections = list(dict.fromkeys(b.section for b in blocks))
    kinds = set(b.kind for b in blocks)
    return Chunk(f"{prefix}-{doc.doc_id[:8]}-{ordinal}", doc.doc_id, doc.title,
                 start, end, doc.text[start:end], first.page,
                 " / ".join(sections), first.subsection,
                 first.kind if len(kinds) == 1 else "mixed", parent_id)


def structural_groups(doc: Document, size: int = 800, target: int = 650) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    begin: int | None = None
    end = 0
    key: tuple | None = None
    for block in doc.blocks:
        block_key = (block.section, block.subsection, block.page)
        if begin is not None and (block_key != key or tokens(doc.text[begin:block.end]) > size):
            result.append((begin, end))
            begin = None
        if tokens(block.text) > size:
            result.extend(recursive_spans(doc.text, block.start, block.end, target))
            continue
        if begin is None:
            begin = block.start
        end, key = block.end, block_key
        if tokens(doc.text[begin:end]) >= target:
            result.append((begin, end))
            begin = None
    if begin is not None:
        result.append((begin, end))
    return result


def chunk_documents(documents: list[Document], strategy: str,
                    embed: Callable[[list[str]], np.ndarray] | None = None) -> ChunkSet:
    from time import perf_counter
    started = perf_counter()
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}")
    children: list[Chunk] = []
    parents: dict[str, Chunk] = {}
    semantic_seconds = 0.0
    for doc in documents:
        if strategy == "baseline":
            spans = token_spans(doc.text, 0, len(doc.text), 650, 81)
            children.extend(make_chunk(doc, "b", i, span) for i, span in enumerate(spans))
        elif strategy == "research_aware":
            children.extend(make_chunk(doc, "r", i, span)
                            for i, span in enumerate(structural_groups(doc)))
        elif strategy == "hierarchical_recursive":
            for i, span in enumerate(structural_groups(doc)):
                parent = make_chunk(doc, "hp", i, span)
                parents[parent.chunk_id] = parent
                for child_span in recursive_spans(doc.text, *span, limit=320):
                    children.append(make_chunk(doc, "hc", len(children), child_span, parent.chunk_id))
        else:
            if embed is None:
                raise ValueError("Semantic chunking requires an embedding function.")
            blocks: list[Block] = []
            for block in doc.blocks:
                spans = recursive_spans(doc.text, block.start, block.end, limit=800) if block.kind == "text" else [(block.start, block.end)]
                for start, end in spans:
                    blocks.append(Block(doc.text[start:end], block.page, block.section,
                                        block.subsection, block.kind, start, end))
            prose = [b for b in blocks if b.kind == "text"]
            begin_embed = perf_counter()
            vectors = embed([b.text for b in prose]) if prose else np.empty((0, 0))
            semantic_seconds += perf_counter() - begin_embed
            by_start = {block.start: vector for block, vector in zip(prose, vectors, strict=True)}
            pending: list[Block] = []
            previous: Block | None = None

            def flush() -> None:
                if not pending:
                    return
                span = (pending[0].start, pending[-1].end)
                for bounded in recursive_spans(doc.text, *span, limit=800):
                    parent = make_chunk(doc, "sp", len(parents), bounded)
                    parents[parent.chunk_id] = parent
                    for child_span in recursive_spans(doc.text, *bounded, limit=320):
                        children.append(make_chunk(doc, "sc", len(children), child_span, parent.chunk_id))
                pending.clear()

            for block in blocks:
                if block.kind in {"table", "figure"}:
                    flush()
                    # Keep caption/body or grid together unless it exceeds the common cap.
                    for span in recursive_spans(doc.text, block.start, block.end, limit=800):
                        atomic = make_chunk(doc, "sa", len(children), span)
                        children.append(atomic)
                    previous = None
                    continue
                similarity = float(by_start[block.start] @ by_start[previous.start]) if previous else 1.0
                boundary = previous is not None and (
                    (block.section, block.subsection, block.page) !=
                    (previous.section, previous.subsection, previous.page)
                    or similarity < 0.65
                )
                if pending and (boundary or tokens(doc.text[pending[0].start:block.end]) > 800):
                    flush()
                pending.append(block)
                previous = block
            flush()
    return ChunkSet(strategy, children, parents, perf_counter() - started, semantic_seconds)
