"""Versioned evidence builds: source artifacts for one paper, created before any fact extraction."""

import asyncio
import base64
import hashlib
import logging
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.core.auth import owner_id
from app.core.config import Settings
from app.db.session import SessionLocal
from app.modules.compare.grounded import PARSER_VERSION
from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.llm import GroundedLLM
from app.modules.compare.grounded.pdf_parsing import (
    ParsedDocument, content_hash, parse_pdf_bytes, render_pages, table_text, text_units,
)
from app.modules.papers.orm.chunk import Chunk
from app.modules.compare.orm.grounded import DocumentArtifact, PaperEvidenceBuild
from app.modules.papers.orm.paper import Paper
from app.platform.llm.prompts.loader import PromptLoader
from app.db.retry import retry_sqlite_locked

logger = logging.getLogger(__name__)
VISION_PROMPT_VERSION = "grounded-vision-v1"
EMBED_BATCH = 16


def document_embedding_text(title: str, text: str) -> str:
    # EmbeddingGemma's documented document prompt.
    return f"title: {title or 'none'} | text: {text}"


def query_embedding_text(query: str) -> str:
    return f"task: search result | query: {query}"


@dataclass
class SourceBytes:
    data: bytes | None
    text_source: str


def stale_reason(build: PaperEvidenceBuild | None, paper: Paper | None, embed_model: str) -> str | None:
    """Why a build must be rebuilt before use, or None when it is current."""
    if build is None:
        return "no evidence build"
    if build.status != "ready":
        return f"previous build {build.status}"
    if build.parser_version != PARSER_VERSION:
        return "parser version changed"
    if build.embed_model != embed_model:
        return "embedding model changed"
    if paper is not None and (build.doc_metadata or {}).get("paper_content_hash") != paper.content_hash:
        return "paper content changed"
    return None


class EvidenceBuilder:
    def __init__(self, settings: Settings, llm: GroundedLLM, embedder, prompts: PromptLoader | None = None, paper_service=None):
        self.settings = settings
        self.llm = llm
        self.embedder = embedder
        self.prompts = prompts or PromptLoader()
        self._paper_service = paper_service

    async def current_build(self, paper_id: str) -> PaperEvidenceBuild | None:
        async with SessionLocal() as session:
            return await session.scalar(
                select(PaperEvidenceBuild).join(Paper, Paper.id == PaperEvidenceBuild.paper_id)
                .where(PaperEvidenceBuild.paper_id == paper_id, PaperEvidenceBuild.is_current.is_(True),
                       Paper.owner_id == owner_id()).limit(1))

    def is_stale(self, build: PaperEvidenceBuild | None, paper: Paper | None = None) -> str | None:
        return stale_reason(build, paper, self.llm.tier.embed_model)

    async def ensure(self, paper_id: str, *, force: bool = False, progress=None) -> tuple[PaperEvidenceBuild, bool]:
        """Return the current build, rebuilding when forced or stale. Second value: rebuilt?"""
        paper = await self._paper(paper_id)
        build = await self.current_build(paper_id)
        reason = "explicit rebuild" if force else self.is_stale(build, paper)
        if reason is None:
            return build, False
        logger.info("Rebuilding evidence for %s: %s", paper_id, reason)
        return await self.build(paper, reason, progress=progress), True

    async def _paper(self, paper_id: str) -> Paper:
        async with SessionLocal() as session:
            paper = await session.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_id == owner_id()))
        if not paper:
            raise HTTPException(404, "Resource not found")
        return paper

    async def _source_bytes(self, paper: Paper) -> SourceBytes:
        from app.modules.papers.ingestion.upload import uploaded_pdf_path

        try:
            path = uploaded_pdf_path(str(paper.id))
            if path.is_file() and not path.is_symlink():
                return SourceBytes(await asyncio.to_thread(path.read_bytes), "local_pdf")
        except RuntimeError:
            logger.warning("Upload directory unavailable for evidence build", exc_info=True)
        if paper.pdf_url:
            service = self._paper_service
            if service is None:
                from app.modules.papers.service import PaperService
                service = PaperService()
            data = await service._fetch_pdf_bytes(paper.pdf_url)
            if data:
                return SourceBytes(data, "remote_pdf")
        return SourceBytes(None, "ingest_chunks")

    def _render_dir(self, paper_id: str, version: int):
        from app.modules.papers.ingestion.upload import _owner_directory

        return _owner_directory(create=True) / "evidence" / hashlib.sha256(paper_id.encode()).hexdigest()[:32] / f"v{version}"

    async def build(self, paper: Paper, reason: str, progress=None) -> PaperEvidenceBuild:
        paper_id = str(paper.id)
        source = await self._source_bytes(paper)
        parsed: ParsedDocument | None = None
        flags: list[str] = []
        if source.data:
            try:
                parsed = await asyncio.to_thread(parse_pdf_bytes, source.data)
            except Exception as exc:
                logger.warning("Grounded PDF parse failed for %s", paper_id, exc_info=True)
                flags.append(f"pdf_parse_failed:{type(exc).__name__}")
        version = await self._next_version(paper_id)
        build_id = str(uuid4())
        artifacts: list[dict] = []
        doc_metadata = {"title": paper.title, "authors": paper.authors or [], "year": paper.year, "doi": paper.doi,
                        "paper_content_hash": paper.content_hash, "rebuild_reason": reason}
        page_count = 0
        scanned = False
        if parsed and any(p.strip() for p in parsed.pages) or (parsed and parsed.scanned_pages):
            flags.extend(parsed.flags)
            page_count = parsed.total_pages
            scanned = parsed.is_scanned
            detected = {k: v for k, v in parsed.metadata.items() if v}
            doc_metadata["detected"] = detected
            artifacts, extra_flags = await self._pdf_artifacts(paper, parsed, source.data, build_id, version, progress)
            flags.extend(extra_flags)
        else:
            source = SourceBytes(None, "ingest_chunks")
            artifacts, extra_flags, page_count = await self._chunk_artifacts(paper, build_id, version)
            flags.extend(extra_flags)
            if artifacts and all(a["kind"] == "abstract" for a in artifacts):
                source = SourceBytes(None, "abstract")
        if not artifacts:
            flags.append("no_source_text")
        await self._embed(paper.title, artifacts)
        pdf_sha = hashlib.sha256(source.data).hexdigest() if source.data else None
        return await self._persist(paper_id, build_id, version, source.text_source, pdf_sha, page_count, scanned,
                                   sorted(set(flags)), doc_metadata, artifacts)

    async def _next_version(self, paper_id: str) -> int:
        async with SessionLocal() as session:
            current = await session.scalar(select(func.max(PaperEvidenceBuild.version)).where(PaperEvidenceBuild.paper_id == paper_id))
        return int(current or 0) + 1

    def _artifact(self, paper_id, build_id, version, kind, ordinal, page, text, *, section=None, label=None,
                  caption=None, cells=None, image_path=None, status="parsed", flags=None) -> dict:
        page_part = f"p{page:03d}" if page else "p000"
        return {
            "id": f"{paper_id}-v{version}-{page_part}-{kind}-{ordinal:03d}", "build_id": build_id, "paper_id": paper_id,
            "kind": kind, "ordinal": ordinal, "page_start": page, "page_end": page, "section": section, "label": label,
            "caption": caption, "text": text, "cells": cells, "image_path": str(image_path) if image_path else None,
            "extraction_status": status, "quality_flags": list(flags or []), "parser_version": PARSER_VERSION,
            "content_hash": content_hash(kind, page, text, cells),
        }

    async def _pdf_artifacts(self, paper: Paper, parsed: ParsedDocument, data: bytes, build_id: str, version: int, progress):
        paper_id = str(paper.id)
        flags: list[str] = []
        units, unit_flags = text_units(parsed.pages)
        flags.extend(unit_flags)
        artifacts = [self._artifact(paper_id, build_id, version, "text", i, u["page"], u["text"], section=u["section"])
                     for i, u in enumerate(units)]
        section_by_page = {}
        for unit in units:
            section_by_page.setdefault(unit["page"], unit["section"])
        for i, table in enumerate(parsed.tables):
            artifacts.append(self._artifact(paper_id, build_id, version, "table", i, table.page,
                                            table_text(table.cells, table.caption), section=section_by_page.get(table.page),
                                            label=table.label, caption=table.caption, cells=table.cells))
        # Pages needing the vision model: scanned pages, table captions without a parsed
        # table, and figures. Only these pages are rendered; never the whole PDF.
        parsed_table_labels = {(t.page, t.label) for t in parsed.tables if t.label}
        missing_tables = [c for c in parsed.captions if c.kind == "table" and (c.page, c.text.split(":")[0]) not in parsed_table_labels]
        figures = [c for c in parsed.captions if c.kind == "figure"]
        scanned = parsed.scanned_pages
        budget = self.settings.grounded_max_vlm_pages
        wanted = list(dict.fromkeys([*scanned, *[c.page for c in missing_tables], *[c.page for c in figures]]))[:budget]
        if len(set([*scanned, *[c.page for c in missing_tables], *[c.page for c in figures]])) > budget:
            flags.append("vision_page_budget_exhausted")
        rendered = {}
        if wanted:
            try:
                rendered = await asyncio.to_thread(render_pages, data, wanted, self._render_dir(paper_id, version), "page")
            except Exception:
                logger.warning("Page rendering failed for %s", paper_id, exc_info=True)
                flags.append("page_render_failed")
        ordinal = len(artifacts)
        for page in scanned:
            if page not in rendered:
                flags.append(f"scanned_page_not_ocr:p{page}")
                continue
            text = await self._vision_text(paper_id, rendered[page], "grounded/vision_ocr.jinja", "ocr")
            if text:
                ordinal += 1
                artifacts.append(self._artifact(paper_id, build_id, version, "text", ordinal, page, text,
                                                section=section_by_page.get(page), image_path=rendered[page],
                                                status="ocr_candidate", flags=["ocr_uncertain"]))
                flags.append("ocr_uncertain")
            else:
                flags.append(f"ocr_failed:p{page}")
        for caption in missing_tables:
            if caption.page not in rendered:
                flags.append(f"table_not_extracted:{caption.text.split(':')[0]}")
                continue
            cells = await self._vision_table(paper_id, rendered[caption.page], caption.text)
            ordinal += 1
            if cells:
                artifacts.append(self._artifact(paper_id, build_id, version, "table", ordinal, caption.page,
                                                table_text(cells, caption.text), section=section_by_page.get(caption.page),
                                                label=caption.text.split(":")[0], caption=caption.text, cells=cells,
                                                image_path=rendered[caption.page], status="candidate", flags=["visual_extraction"]))
            else:
                flags.append(f"table_not_extracted:{caption.text.split(':')[0]}")
        for caption in figures:
            description = None
            if caption.page in rendered:
                description = await self._vision_text(paper_id, rendered[caption.page], "grounded/vision_figure.jinja", "figure", caption=caption.text)
            ordinal += 1
            text = caption.text + (f"\nVisible content (vision model, candidate): {description}" if description else "")
            artifacts.append(self._artifact(paper_id, build_id, version, "figure", ordinal, caption.page, text,
                                            section=section_by_page.get(caption.page), label=caption.text.split(":")[0],
                                            caption=caption.text, image_path=rendered.get(caption.page),
                                            status="candidate" if description else "caption_only",
                                            flags=["visual_extraction"] if description else []))
        if progress:
            await progress(f"parsed {len(artifacts)} source artifacts")
        return artifacts, flags

    async def _chunk_artifacts(self, paper: Paper, build_id: str, version: int):
        paper_id = str(paper.id)
        async with SessionLocal() as session:
            chunks = (await session.execute(select(Chunk).where(Chunk.paper_id == paper_id).order_by(Chunk.ordinal))).scalars().all()
        flags = ["no_pdf_available_tables_and_figures_not_extracted"]
        if chunks:
            flags.append("derived_from_ingest_chunks")
            if all(c.page is None for c in chunks):
                flags.append("page_numbers_unavailable")
            pages = [c.page for c in chunks if c.page]
            return ([self._artifact(paper_id, build_id, version, "text", i, c.page, c.text, section=c.section,
                                    flags=["derived_from_ingest_chunk"]) for i, c in enumerate(chunks)],
                    flags, max(pages) if pages else 0)
        if paper.abstract:
            flags.append("abstract_only")
            return [self._artifact(paper_id, build_id, version, "abstract", 0, None, paper.abstract, section="Abstract",
                                   flags=["abstract_only"])], flags, 0
        return [], flags, 0

    async def _vision_text(self, paper_id: str, image_path, template: str, purpose: str, caption: str | None = None) -> str | None:
        image = base64.b64encode(await asyncio.to_thread(image_path.read_bytes)).decode()
        result, _ = await self.llm.call(
            purpose=f"vision_{purpose}", prompt_version=VISION_PROMPT_VERSION, vision=True, images=[image], paper_id=paper_id,
            system=self.prompts.render(template, caption=caption or ""), user=f"Page image attached. {caption or ''}".strip(),
            single_object=True, max_tokens=3072,
        )
        if not result.items:
            return None
        item = result.items[0]
        if norm.verdict_word(norm.get_key(item, "legible", "readable"), ("yes", "no"), "yes") == "no":
            return None
        text = norm.get_key(item, "text", "description", "content")
        return str(text).strip() or None if text else None

    async def _vision_table(self, paper_id: str, image_path, caption: str) -> list[list[str]] | None:
        image = base64.b64encode(await asyncio.to_thread(image_path.read_bytes)).decode()
        result, _ = await self.llm.call(
            purpose="vision_table", prompt_version=VISION_PROMPT_VERSION, vision=True, images=[image], paper_id=paper_id,
            system=self.prompts.render("grounded/vision_table.jinja", caption=caption), user=f"Extract {caption}.",
            single_object=True, max_tokens=3072,
        )
        if not result.items:
            return None
        cells = norm.table_cells(result.items[0])
        return cells if cells and len(cells) >= 2 else None

    async def _embed(self, title: str, artifacts: list[dict]) -> None:
        model = self.llm.tier.embed_model
        texts = [document_embedding_text(title, a["text"][:6000]) for a in artifacts]
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start:start + EMBED_BATCH]
            try:
                vectors = await self.embedder(batch, model)
            except Exception:
                logger.warning("Evidence embedding failed; retrieval falls back to section priors and lexical overlap", exc_info=True)
                for artifact in artifacts[start:]:
                    artifact["quality_flags"] = [*artifact["quality_flags"], "not_embedded"]
                return
            for artifact, vector in zip(artifacts[start:start + EMBED_BATCH], vectors):
                if vector:
                    artifact["embedding_json"] = vector
                    artifact["embed_model"] = model

    async def _persist(self, paper_id, build_id, version, text_source, pdf_sha, page_count, scanned, flags, doc_metadata, artifacts):
        status = "ready" if artifacts else "empty"

        async def op():
            async with SessionLocal() as session:
                # New build supersedes previous ones; old facts become stale with their build.
                await session.execute(update(PaperEvidenceBuild).where(PaperEvidenceBuild.paper_id == paper_id).values(is_current=False))
                build = PaperEvidenceBuild(
                    id=build_id, paper_id=paper_id, version=version, is_current=True, status=status,
                    parser_version=PARSER_VERSION, embed_model=self.llm.tier.embed_model, text_source=text_source,
                    pdf_sha256=pdf_sha, page_count=page_count, scanned=scanned, quality_flags=flags, doc_metadata=doc_metadata,
                )
                session.add(build)
                await session.flush()
                for artifact in artifacts:
                    session.add(DocumentArtifact(**artifact))
                await session.commit()
                return build
        return await retry_sqlite_locked(op)


async def load_artifacts(build_id: str) -> list[DocumentArtifact]:
    async with SessionLocal() as session:
        return list((await session.execute(select(DocumentArtifact).where(DocumentArtifact.build_id == build_id)
                                           .order_by(DocumentArtifact.kind, DocumentArtifact.ordinal))).scalars().all())
