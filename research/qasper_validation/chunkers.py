from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from time import perf_counter

from chat_chunking.chunking import ChunkSet, chunk_documents, make_chunk
from chat_chunking.corpus import Document

ARMS = ("current_chat", "baseline", "research_aware")
INGESTION_SOURCE = Path(__file__).resolve().parents[2] / "backend" / "app" / "modules" / "papers" / "service.py"


def current_word_helper():
    # Load only the existing pure helper, not the application or database modules.
    tree = ast.parse(INGESTION_SOURCE.read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_chunk_words")
    isolated = ast.Module(body=[node], type_ignores=[])
    namespace: dict = {}
    exec(compile(isolated, str(INGESTION_SOURCE), "exec"), namespace)
    return namespace["_chunk_words"]


def build(documents: list[Document], arm: str) -> ChunkSet:
    if arm not in ARMS:
        raise ValueError(f"Unknown validation arm: {arm}")
    if arm != "current_chat":
        return chunk_documents(documents, arm)
    started = perf_counter()
    word_helper = current_word_helper()
    children = []
    for doc in documents:
        groups = []
        for block in doc.blocks:
            key = (block.page, block.section, block.subsection)
            if groups and groups[-1][0] == key:
                groups[-1][2] = block.end
            else:
                groups.append([key, block.start, block.end])
        for _, start, end in groups:
            text = doc.text[start:end]
            words = list(re.finditer(r"\S+", text))
            expected = word_helper(text, size=350, overlap=50)
            for ordinal, normalized_text in enumerate(expected):
                offset = ordinal * 300
                chosen = words[offset:offset + 350]
                if not chosen:
                    raise ValueError("Current helper and source-word offsets disagree.")
                span = (start + chosen[0].start(), start + chosen[-1].end())
                chunk = make_chunk(doc, "live", len(children), span)
                if " ".join(chunk.text.split()) != normalized_text:
                    raise ValueError("Current Chat word-window control differs from the production helper.")
                # Preserve canonical whitespace for evidence alignment.
                children.append(chunk)
    return ChunkSet(arm, children, {}, perf_counter() - started)


def helper_digest() -> str:
    return hashlib.sha256(INGESTION_SOURCE.read_bytes()).hexdigest()
