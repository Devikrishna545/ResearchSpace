import asyncio
import hashlib
import io
import logging
import re
import weakref
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.core.auth import owner_id
from app.platform.llm.ollama_client import get_ollama_client
from app.modules.papers.orm.chunk import Chunk
from app.modules.papers.orm.paper import Paper as PaperRow
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.chat.schemas.chat import ScoredChunk
from app.modules.papers.schemas.paper import IngestJob, IngestStatus, Paper
from app.platform.retrieval import ingest_store
from app.shared.identifiers import canonical_arxiv_id, canonical_doi
from app.platform.http.net import validate_public_https_url
from app.db.retry import retry_sqlite_locked
from app.shared.text import clean_metadata_text

logger = logging.getLogger(__name__)
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_WEB_CAPTURE_BYTES = 5 * 1024 * 1024
# Background ingests (bulk pinning) fetch PDFs and embed; bound them so a large
# selection cannot saturate the local model or the network at once.
BACKGROUND_INGEST_CONCURRENCY = 2
_background_ingests: set[asyncio.Task] = set()
_ingest_slots: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _ingest_slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    slot = _ingest_slots.get(loop)
    if slot is None:
        slot = _ingest_slots[loop] = asyncio.Semaphore(BACKGROUND_INGEST_CONCURRENCY)
    return slot


def _chunk_words(text: str, size: int = 350, overlap: int = 50) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks, start = [], 0
    while start < len(words):
        chunks.append(' '.join(words[start:start + size]))
        start += size - overlap
    return chunks


SECTION_PATTERNS = (
    'abstract', 'introduction', 'background', 'related work', 'method', 'methodology',
    'approach', 'experiment', 'evaluation', 'dataset', 'result', 'discussion',
    'limitation', 'conclusion', 'future work', 'references', 'appendix',
)


NUMBERED_HEADING = re.compile(
    r"^\s*(?P<number>\d{1,2}(?:\.\d{1,2}){0,3})(?:\.)?\s+(?P<title>[A-Z][^\n]{2,80}?)\s*$"
)
UNNUMBERED_HEADINGS = frozenset({
    "abstract", "introduction", "background", "related work", "previous work",
    "methods", "method", "methodology", "materials and methods", "dataset",
    "data", "results", "discussion", "conclusion", "limitations", "references",
    "acknowledgements", "appendix",
})


def _canonical_heading(title: str) -> str | None:
    value = title.lower().strip()
    if value.startswith(("references", "bibliography")):
        return "References"
    if value.startswith(("related work", "previous work", "prior work")):
        return "Related Work"
    if value.startswith(("introduction", "background", "goals of the paper")):
        return "Introduction"
    if value.startswith(("dataset", "data collection", "corpus", "corpora", "data sources")) or value == "data":
        return "Dataset"
    if value.startswith(("metric", "measure", "evaluation metrics")):
        return "Metrics"
    if value.startswith(("results", "findings", "evaluation results")):
        return "Results"
    if value.startswith(("limitations", "limitations and future", "threats to validity")):
        return "Limitations"
    if value.startswith("discussion"):
        return "Discussion"
    if value.startswith("conclusion"):
        return "Conclusion"
    if value.startswith("abstract"):
        return "Abstract"
    if value.startswith(("method", "materials and methods", "model architecture",
                         "new log-linear model", "parallel training", "continuous bag-of-words",
                         "continuous skip-gram", "feedforward neural net", "recurrent neural net",
                         "approach")) or value.startswith("the ") and "model" in value[:35]:
        return "Method"
    return None


def _detect_section(line: str, *, allow_numbered: bool = True) -> str | None:
    """Recognize a heading line, never infer a section from nearby prose."""
    raw = " ".join(line.split())
    if not raw or len(raw) > 100:
        return None
    match = NUMBERED_HEADING.fullmatch(raw)
    if match and not allow_numbered:
        return None
    if match is None and raw.lower().rstrip(":") not in UNNUMBERED_HEADINGS:
        return None
    if match:
        numbers = [int(part) for part in match.group("number").split(".")]
        if not all(1 <= part <= 20 for part in numbers):
            return None
        title = match.group("title")
        if any(symbol in title for symbol in ("=", "|", ";")) or re.search(r"\.\s+[A-Z]", title):
            return None
    else:
        title = raw.rstrip(":")
    canonical = _canonical_heading(title)
    return f"{canonical} — {raw}" if canonical and canonical.casefold() != raw.casefold() else canonical or raw


def _section_segments(page_text: str, *, allow_numbered: bool = True) -> list[tuple[str, str | None]]:
    """Segment on actual PDF line breaks before `_chunk_words` flattens them."""
    segments = []
    lines = []
    current_section = None
    for line in page_text.splitlines():
        heading = None if current_section and current_section.startswith("References") else _detect_section(
            line, allow_numbered=allow_numbered,
        )
        if heading:
            if any(piece.strip() for piece in lines):
                segments.append(("\n".join(lines), current_section))
            lines = [line]
            current_section = heading
        elif not (current_section and current_section.startswith("References")) and (
            NUMBERED_HEADING.fullmatch(" ".join(line.split()))
            or (len(line.split()) >= 2 and len(line) <= 80 and line.strip().isupper())
        ):
            if current_section is not None:
                if any(piece.strip() for piece in lines):
                    segments.append(("\n".join(lines), current_section))
                lines = [line]
                current_section = None
            else:
                lines.append(line)
        else:
            lines.append(line)
    if any(piece.strip() for piece in lines):
        segments.append(("\n".join(lines), current_section))
    return segments


def _chunk_pages(pages: list[str], size: int = 350, overlap: int = 50,
                 *, heading_aware: bool = True) -> list[dict]:
    """Chunk each page and real heading segment without crossing either boundary."""
    out: list[dict] = []
    has_numbered_outline = any(
        (match := NUMBERED_HEADING.fullmatch(" ".join(line.split())))
        and match.group("number") == "1"
        and _canonical_heading(match.group("title")) in {"Introduction", "Method"}
        for page in pages for line in page.splitlines()
    ) if heading_aware else False
    for page_number, page_text in enumerate(pages, start=1):
        segments = _section_segments(page_text, allow_numbered=has_numbered_outline) if heading_aware else [(page_text, None)]
        for text, section in segments:
            for piece in _chunk_words(text, size=size, overlap=overlap):
                out.append({'text': piece, 'page': page_number, 'section': section})
    return out


def _validate_vectors(chunks: list[ScoredChunk], vectors: list[list[float]]) -> None:
    if len(vectors) != len(chunks):
        raise ValueError('embedding count does not match chunk count')
    if any(not v for v in vectors):
        raise ValueError('embeddings must be non-empty')
    dims = {len(v) for v in vectors}
    if len(dims) != 1:
        raise ValueError('embeddings must be non-empty and share one dimension')


def _parse_pdf_pages(data: bytes) -> list[str]:
    """Extract text per page so chunks can carry real page numbers."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return [(page.extract_text() or '').strip() for page in list(reader.pages[:MAX_PDF_PAGES])]
    except Exception as exc:
        logger.warning('PDF parse failed: %s', exc)
        return []


def _parse_pdf_text(data: bytes) -> str | None:
    pages = _parse_pdf_pages(data)
    text = '\n'.join(pages).strip()
    return text or None


class _ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {'script', 'style', 'noscript', 'svg', 'nav', 'header', 'footer'}:
            self._skip_depth += 1
        elif tag == 'title':
            self._in_title = True
        elif tag in {'p', 'div', 'section', 'article', 'main', 'br', 'li', 'h1', 'h2', 'h3'} and not self._skip_depth:
            self._text_parts.append('\n')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {'script', 'style', 'noscript', 'svg', 'nav', 'header', 'footer'} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == 'title':
            self._in_title = False
            self.title = ' '.join(' '.join(self._title_parts).split())

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        elif not self._skip_depth:
            text = ' '.join(data.split())
            if text:
                self._text_parts.append(text)

    @property
    def text(self) -> str:
        lines = [' '.join(line.split()) for line in ''.join(self._text_parts).splitlines()]
        return '\n'.join(line for line in lines if line).strip()


def _parse_html_text(data: bytes) -> tuple[str | None, str | None]:
    parser = _ReadableHTMLParser()
    parser.feed(data.decode('utf-8', errors='ignore'))
    return parser.text or None, parser.title or None


class PaperService:
    def __init__(self):
        self.papers = {}
        self.settings = get_settings()
        self.llm = get_ollama_client()

    async def _fetch_pdf_pages(self, url: str) -> list[str]:
        """Download a PDF safely and return its text page by page."""
        data = await self._fetch_pdf_bytes(url)
        return await asyncio.to_thread(_parse_pdf_pages, data) if data else []

    async def _fetch_pdf_bytes(self, url: str) -> bytes | None:
        """Download a PDF over validated public HTTPS with size and redirect limits."""
        try:
            async with asyncio.timeout(35):
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, headers={'User-Agent': self.settings.source_user_agent}) as c:
                    current_url = url
                    for _ in range(6):
                        if not validate_public_https_url(current_url):
                            logger.warning('Rejected unsafe PDF URL')
                            return None
                        async with c.stream('GET', current_url) as r:
                            if r.status_code in {301, 302, 303, 307, 308}:
                                location = r.headers.get('location')
                                if not location:
                                    logger.warning('Publisher PDF redirect has no location')
                                    return None
                                current_url = urljoin(str(r.url), location)
                                continue
                            r.raise_for_status()
                            if 'html' in r.headers.get('content-type', '').lower():
                                logger.warning('Publisher returned HTML instead of a PDF')
                                return None
                            data = bytearray()
                            async for chunk in r.aiter_bytes():
                                data.extend(chunk)
                                if len(data) > MAX_PDF_BYTES:
                                    logger.warning('Rejected oversized PDF download')
                                    return None
                            if bytes(data[:5]) != b'%PDF-':
                                logger.warning('Rejected non-PDF publisher content')
                                return None
                            return bytes(data)
                    logger.warning('Publisher PDF exceeded redirect limit')
                    return None
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            logger.warning('Publisher PDF unavailable (%s)', type(exc).__name__)
            return None

    async def _fetch_pdf_text(self, url: str) -> str | None:
        pages = await self._fetch_pdf_pages(url)
        text = '\n'.join(pages).strip()
        return text or None

    async def capture_web(self, space_id: str, url: str, title: str | None = None, content: str | None = None):
        if not validate_public_https_url(url):
            raise ValueError('URL must be HTTPS and resolve to a public address')

        text: str | None
        page_title: str | None = title
        content_type = 'text/plain'
        capture_kind = 'selection' if content else 'html'
        if content is not None:
            text = content.strip()
        else:
            await self._check_robots_allowed(url)
            data, content_type, final_url = await self._fetch_web_bytes(url)
            url = final_url
            if content_type.lower().startswith('application/pdf') or data[:5] == b'%PDF-':
                capture_kind = 'pdf'
                text = await asyncio.to_thread(_parse_pdf_text, data)
            elif 'html' in content_type.lower() or b'<html' in data[:2048].lower():
                text, extracted_title = await asyncio.to_thread(_parse_html_text, data)
                page_title = page_title or extracted_title
            else:
                raise ValueError(f'unsupported content type: {content_type or "unknown"}')

        if not text:
            text = ''
        source_title = page_title or urlparse(url).netloc or 'Web capture'
        previous_hash = await self._get_web_content_hash(url)
        content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest() if text else None
        final_status = IngestStatus.READY if len(text.split()) >= 30 else IngestStatus.DEGRADED
        paper = Paper(
            title=source_title,
            abstract=text[:1000] if text else None,
            pdf_url=url,
            source='web',
            raw_payload={'url': url, 'content_type': content_type, 'capture_kind': capture_kind},
        )
        paper_id = await self._upsert_paper_row(paper, content_hash, bool(text))
        await self._ensure_pin(space_id, paper_id)
        paper.id = paper_id
        self.papers[str(paper.id)] = paper

        stored_hash = await self._get_content_hash(str(paper.id))
        existing_chunks = await self._load_chunks(space_id, str(paper.id))
        reusable_hash = previous_hash if previous_hash is not None else stored_hash
        if existing_chunks and reusable_hash == content_hash:
            await self._update_status(str(paper.id), final_status)
            return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=final_status, message=f'Captured; reused {len(existing_chunks)} existing chunks')
        if existing_chunks:
            await self._clear_chunks(str(paper.id), space_id)

        if not text:
            await self._update_status(str(paper.id), IngestStatus.DEGRADED)
            return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=IngestStatus.DEGRADED, message='Captured; little readable text found')

        try:
            await self._update_status(str(paper.id), IngestStatus.CHUNKING)
            parts = _chunk_pages([text], heading_aware=False)
            chunks = [ScoredChunk(chunk_id=f'{paper.id}-{i}', paper_id=str(paper.id), text=part['text'], source=paper.title,
                                  section=part['section'], metadata={'ordinal': i}) for i, part in enumerate(parts)]
            await self._update_status(str(paper.id), IngestStatus.EMBEDDING)
            vectors = await self.llm.embed([c.text for c in chunks], self.settings.ollama_model_embed)
            _validate_vectors(chunks, vectors)
            await self._persist_chunks(str(paper.id), chunks, vectors)
            await ingest_store.vector_store.upsert(space_id, chunks, vectors)
            ingest_store.register_chunks(space_id, chunks)
            await self._update_status(str(paper.id), final_status)
            return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=final_status, message=f'Captured; ingested {len(chunks)} chunks')
        except Exception as exc:
            logger.exception('Web capture ingest failed for %s', paper.id)
            await self._update_status(str(paper.id), IngestStatus.FAILED)
            return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=IngestStatus.FAILED, message=f'Capture failed: {exc}')

    async def _check_robots_allowed(self, url: str) -> None:
        parsed = urlparse(url)
        robots_url = urlunparse((parsed.scheme, parsed.netloc, '/robots.txt', '', '', ''))
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, headers={'User-Agent': self.settings.source_user_agent}) as c:
                r = await c.get(robots_url)
                if not validate_public_https_url(str(r.url)):
                    return
                if r.status_code >= 400:
                    return
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(r.text.splitlines())
            if not parser.can_fetch(self.settings.source_user_agent, url):
                raise ValueError('blocked by robots.txt for this user agent')
        except ValueError:
            raise
        except Exception:
            return

    async def _fetch_web_bytes(self, url: str) -> tuple[bytes, str, str]:
        data = bytearray()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={'User-Agent': self.settings.source_user_agent}) as c:
            async with c.stream('GET', url) as r:
                r.raise_for_status()
                final_url = str(r.url)
                if not validate_public_https_url(final_url):
                    raise ValueError('final URL after redirects is not public HTTPS')
                content_type = r.headers.get('content-type', '').split(';')[0].strip()
                async for chunk in r.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_WEB_CAPTURE_BYTES:
                        raise ValueError('web page exceeds the 5MB capture limit')
        return bytes(data), content_type, final_url

    async def _pin_record(self, space_id, record) -> Paper:
        paper = Paper(**record.model_dump(exclude={'url'}))
        paper.title = clean_metadata_text(paper.title) or ''
        if not paper.title:
            raise ValueError('Paper title has no readable text')
        paper.abstract = clean_metadata_text(paper.abstract)
        paper.authors = [name for author in paper.authors if (name := clean_metadata_text(author))]
        paper.doi = canonical_doi(paper.doi)
        paper.arxiv_id = canonical_arxiv_id(paper.arxiv_id)
        paper_id = await self._upsert_paper_row(paper, None, False)
        await self._ensure_pin(space_id, paper_id)
        paper.id = paper_id
        self.papers[str(paper.id)] = paper
        return paper

    async def pin_and_ingest(self, space_id, record):
        paper = await self._pin_record(space_id, record)
        return await self._ingest_pinned(space_id, paper)

    async def pin_and_ingest_background(self, space_id, record):
        """Pin immediately and ingest later so the UI can show the pin without waiting on PDF/embedding work.

        Clients poll `/papers/{paper_id}/status` until a terminal status is reached.
        """
        paper = await self._pin_record(space_id, record)
        prior = await self.get_status(str(paper.id))
        if prior in {IngestStatus.READY.value, IngestStatus.DEGRADED.value}:
            status = IngestStatus(prior)
        else:
            status = IngestStatus.QUEUED
            await self._update_status(str(paper.id), status)
        task = asyncio.create_task(self._ingest_with_slot(space_id, paper))
        _background_ingests.add(task)
        task.add_done_callback(_background_ingests.discard)
        return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=status, message='Pinned; indexing in the background')

    async def _ingest_with_slot(self, space_id: str, paper: Paper) -> None:
        async with _ingest_slot():
            await self._ingest_pinned(space_id, paper)

    async def _ingest_pinned(self, space_id, paper: Paper):
        final_status = IngestStatus.READY
        try:
            # Reuse check before any network work: an already-embedded paper only needs
            # publishing into this space's store (FR-2.9), not re-fetching or re-embedding.
            existing_chunks = await self._load_chunks(space_id, str(paper.id))
            if existing_chunks:
                prior = await self.get_status(str(paper.id))
                status = IngestStatus(prior) if prior in {IngestStatus.READY.value, IngestStatus.DEGRADED.value} else IngestStatus.READY
                await self._update_status(str(paper.id), status)
                return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=status, message=f'Pinned; reused {len(existing_chunks)} existing chunks')
            text = None
            pages: list[str] = []
            if paper.pdf_url:
                await self._update_status(str(paper.id), IngestStatus.FETCHING)
                await self._update_status(str(paper.id), IngestStatus.PARSING)
                pages = await self._fetch_pdf_pages(paper.pdf_url)
                text = '\n'.join(pages).strip() or None
            has_pdf_text = bool(text)
            if not text and paper.abstract:
                text = f'{paper.title}\n\n{paper.abstract}'
                pages = [text]
                final_status = IngestStatus.DEGRADED
            content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest() if text else None
            if content_hash:
                await self._set_content_hash(str(paper.id), content_hash)

            if not text:
                await self._update_status(str(paper.id), IngestStatus.DEGRADED)
                message = 'Pinned; publisher PDF unavailable and no abstract available' if paper.pdf_url else 'Pinned; no full text or abstract available'
                return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=IngestStatus.DEGRADED, message=message)

            await self._update_status(str(paper.id), IngestStatus.CHUNKING)
            # Chunk per page so each citation can name a real page and section.
            parts = _chunk_pages(pages or [text], heading_aware=has_pdf_text)
            chunks = [ScoredChunk(chunk_id=f'{paper.id}-{i}', paper_id=str(paper.id), text=part['text'], source=paper.title,
                                  page=part['page'] if len(pages) > 1 else None, section=part['section'],
                                  metadata={'ordinal': i}) for i, part in enumerate(parts)]
            await self._update_status(str(paper.id), IngestStatus.EMBEDDING)
            vectors = await self.llm.embed([c.text for c in chunks], self.settings.ollama_model_embed)
            _validate_vectors(chunks, vectors)

            if not await self._pin_exists(space_id, str(paper.id)):
                await self._update_status(str(paper.id), IngestStatus.FAILED)
                return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=IngestStatus.FAILED, message='Pin removed before ingest publish')
            await self._persist_chunks(str(paper.id), chunks, vectors)
            if not await self._pin_exists(space_id, str(paper.id)):
                await self._update_status(str(paper.id), final_status)
                return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=final_status, message='Ingested but pin removed before publish')
            await ingest_store.vector_store.upsert(space_id, chunks, vectors)
            ingest_store.register_chunks(space_id, chunks)
            await self._update_status(str(paper.id), final_status)
            message = f'Pinned; abstract only (full text unavailable); ingested {len(chunks)} chunks' if final_status == IngestStatus.DEGRADED else f'Pinned; ingested {len(chunks)} chunks'
            return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=final_status, message=message)
        except Exception as exc:
            logger.exception('Paper ingest failed for %s', paper.id)
            await self._update_status(str(paper.id), IngestStatus.FAILED)
            return IngestJob(job_id=str(uuid4()), paper_id=str(paper.id), status=IngestStatus.FAILED, message=f'Ingest failed: {exc}')

    async def _upsert_paper_row(self, paper: Paper, content_hash: str | None, has_text: bool) -> str:
        paper.doi = canonical_doi(paper.doi)
        paper.arxiv_id = canonical_arxiv_id(paper.arxiv_id)
        async def op():
            async with SessionLocal() as session:
                existing = await self._find_existing_paper(session, paper, content_hash)
                if existing:
                    cleaned_title = clean_metadata_text(existing.title)
                    if cleaned_title and cleaned_title != existing.title:
                        existing.title = cleaned_title
                    if not existing.abstract and paper.abstract:
                        existing.abstract = paper.abstract
                    if not existing.pdf_url and paper.pdf_url:
                        existing.pdf_url = paper.pdf_url
                    if paper.source == 'web' and paper.pdf_url:
                        existing.title = paper.title
                        existing.abstract = paper.abstract
                        existing.pdf_url = paper.pdf_url
                        existing.source = paper.source
                        existing.raw_payload = paper.raw_payload
                    if content_hash and (not existing.content_hash or paper.source == 'web'):
                        existing.content_hash = content_hash
                    await session.commit()
                    return existing.id
                paper_id = str(paper.id)
                session.add(PaperRow(id=paper_id, owner_id=owner_id(), doi=paper.doi, arxiv_id=paper.arxiv_id, pmid=paper.pmid, openalex_id=paper.openalex_id, title=paper.title, authors=paper.authors, year=paper.year, venue=paper.venue, abstract=paper.abstract, citation_count=paper.citation_count, oa_status=paper.oa_status, pdf_url=paper.pdf_url, source=paper.source, content_hash=content_hash, ingest_status=IngestStatus.QUEUED.value, raw_payload=paper.raw_payload))
                try:
                    await session.commit()
                    return paper_id
                except IntegrityError:
                    await session.rollback()
                    winner = await self._find_existing_paper(session, paper, content_hash)
                    if winner:
                        return winner.id
                    raise
        return await retry_sqlite_locked(op)

    async def _find_existing_paper(self, session, paper: Paper, content_hash: str | None):
        predicates = []
        doi = canonical_doi(paper.doi)
        arxiv_id = canonical_arxiv_id(paper.arxiv_id)
        if doi:
            predicates.append(PaperRow.doi == doi)
        if arxiv_id:
            predicates.append(PaperRow.arxiv_id == arxiv_id)
        if content_hash:
            predicates.append(PaperRow.content_hash == content_hash)
        if not predicates:
            if paper.source == 'web' and paper.pdf_url:
                return (await session.execute(select(PaperRow).where(PaperRow.owner_id == owner_id(), PaperRow.source == 'web', PaperRow.pdf_url == paper.pdf_url).limit(1))).scalar_one_or_none()
            return None
        if paper.source == 'web' and paper.pdf_url:
            web_match = (await session.execute(select(PaperRow).where(PaperRow.owner_id == owner_id(), PaperRow.source == 'web', PaperRow.pdf_url == paper.pdf_url).limit(1))).scalar_one_or_none()
            if web_match:
                return web_match
        return (await session.execute(select(PaperRow).where(PaperRow.owner_id == owner_id(), or_(*predicates)).limit(1))).scalar_one_or_none()

    async def _ensure_pin(self, space_id: str, paper_id: str) -> None:
        async def op():
            async with SessionLocal() as session:
                if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id())) or not await session.scalar(select(PaperRow.id).where(PaperRow.id == paper_id, PaperRow.owner_id == owner_id())):
                    raise HTTPException(404, 'Resource not found')
                if await session.scalar(select(Pin.id).where(Pin.space_id == space_id, Pin.paper_id == paper_id).limit(1)):
                    return
                session.add(Pin(id=str(uuid4()), space_id=space_id, paper_id=paper_id))
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    if await session.scalar(select(Pin.id).where(Pin.space_id == space_id, Pin.paper_id == paper_id).limit(1)):
                        return
                    raise
        await retry_sqlite_locked(op)

    async def _pin_exists(self, space_id: str, paper_id: str) -> bool:
        async with SessionLocal() as session:
            return bool(await session.scalar(select(Pin.id).join(ResearchSpace, ResearchSpace.id == Pin.space_id).join(PaperRow, PaperRow.id == Pin.paper_id).where(Pin.space_id == space_id, Pin.paper_id == paper_id, ResearchSpace.user_id == owner_id(), PaperRow.owner_id == owner_id()).limit(1)))

    async def get(self, paper_id):
        async with SessionLocal() as session:
            paper = await session.scalar(select(PaperRow).where(PaperRow.id == paper_id, PaperRow.owner_id == owner_id()))
        if not paper:
            return None
        return Paper(id=paper.id, doi=paper.doi, arxiv_id=paper.arxiv_id, pmid=paper.pmid, openalex_id=paper.openalex_id, title=paper.title, authors=paper.authors, year=paper.year, venue=paper.venue, abstract=paper.abstract, citation_count=paper.citation_count, oa_status=paper.oa_status, pdf_url=paper.pdf_url, source=paper.source, raw_payload=paper.raw_payload)

    async def unpin(self, space_id: str, paper_id: str):
        async def op():
            async with SessionLocal() as session:
                await session.execute(delete(Pin).where(Pin.space_id == space_id, Pin.paper_id == paper_id, Pin.space_id.in_(select(ResearchSpace.id).where(ResearchSpace.user_id == owner_id())), Pin.paper_id.in_(select(PaperRow.id).where(PaperRow.owner_id == owner_id()))))
                await session.commit()
        await retry_sqlite_locked(op)
        ingest_store.remove_paper_from_space(space_id, paper_id)
        return {'space_id': space_id, 'paper_id': paper_id, 'unpinned': True}

    async def unpin_many(self, space_id: str, paper_ids: list[str]):
        """Unpin several papers in one transaction; ids not pinned to this owned space are ignored."""
        wanted = list(dict.fromkeys(paper_ids))
        async def op():
            async with SessionLocal() as session:
                owned = select(Pin.paper_id).join(ResearchSpace, ResearchSpace.id == Pin.space_id).join(PaperRow, PaperRow.id == Pin.paper_id).where(
                    Pin.space_id == space_id, Pin.paper_id.in_(wanted), ResearchSpace.user_id == owner_id(), PaperRow.owner_id == owner_id())
                removed = list((await session.execute(owned)).scalars().all())
                if removed:
                    await session.execute(delete(Pin).where(Pin.space_id == space_id, Pin.paper_id.in_(removed)))
                    await session.commit()
                return removed
        removed = await retry_sqlite_locked(op) if wanted else []
        for paper_id in removed:
            ingest_store.remove_paper_from_space(space_id, paper_id)
        return {'space_id': space_id, 'unpinned': removed}

    async def _load_chunks(self, space_id: str, paper_id: str) -> list[ScoredChunk]:
        async with SessionLocal() as session:
            if not await self._pin_exists(space_id, paper_id):
                raise HTTPException(404, 'Resource not found')
            rows = (await session.execute(select(Chunk, PaperRow.title).join(PaperRow, PaperRow.id == Chunk.paper_id).where(Chunk.paper_id == paper_id, PaperRow.owner_id == owner_id(), Chunk.embedding_json.is_not(None)).order_by(Chunk.ordinal))).all()
        if not rows:
            return []
        chunks = [ScoredChunk(chunk_id=c.id, paper_id=c.paper_id, text=c.text, section=c.section, page=c.page, source=title, metadata={'ordinal': c.ordinal}) for c, title in rows]
        vectors = [c.embedding_json for c, _ in rows]
        ingest_store.remove_paper_from_space(space_id, paper_id)
        await ingest_store.vector_store.upsert(space_id, chunks, vectors)
        ingest_store.register_chunks(space_id, chunks)
        return chunks

    async def _update_status(self, paper_id: str, status: IngestStatus) -> None:
        async def op():
            async with SessionLocal() as session:
                paper = await session.scalar(select(PaperRow).where(PaperRow.id == paper_id, PaperRow.owner_id == owner_id()))
                if paper:
                    paper.ingest_status = status.value
                    await session.commit()
        await retry_sqlite_locked(op)

    async def get_status(self, paper_id: str) -> str | None:
        async with SessionLocal() as session:
            return await session.scalar(select(PaperRow.ingest_status).where(PaperRow.id == paper_id, PaperRow.owner_id == owner_id()).limit(1))

    async def _set_content_hash(self, paper_id: str, content_hash: str) -> None:
        async def op():
            async with SessionLocal() as session:
                paper = await session.scalar(select(PaperRow).where(PaperRow.id == paper_id, PaperRow.owner_id == owner_id()))
                if paper and not paper.content_hash:
                    paper.content_hash = content_hash
                    try:
                        await session.commit()
                    except IntegrityError:
                        await session.rollback()
        await retry_sqlite_locked(op)

    async def _get_content_hash(self, paper_id: str) -> str | None:
        async with SessionLocal() as session:
            return await session.scalar(select(PaperRow.content_hash).where(PaperRow.id == paper_id, PaperRow.owner_id == owner_id()).limit(1))

    async def _get_web_content_hash(self, url: str) -> str | None:
        async with SessionLocal() as session:
            return await session.scalar(select(PaperRow.content_hash).where(PaperRow.owner_id == owner_id(), PaperRow.source == 'web', PaperRow.pdf_url == url).limit(1))

    async def _clear_chunks(self, paper_id: str, space_id: str) -> None:
        async def op():
            async with SessionLocal() as session:
                await session.execute(delete(Chunk).where(Chunk.paper_id == paper_id, Chunk.paper_id.in_(select(PaperRow.id).where(PaperRow.owner_id == owner_id()))))
                await session.commit()
        await retry_sqlite_locked(op)
        ingest_store.remove_paper_from_space(space_id, paper_id)

    async def _persist_chunks(self, paper_id: str, chunks: list[ScoredChunk], vectors: list[list[float]]) -> None:
        async def op():
            async with SessionLocal() as session:
                if not await session.scalar(select(PaperRow.id).where(PaperRow.id == paper_id, PaperRow.owner_id == owner_id())):
                    raise HTTPException(404, 'Resource not found')
                for chunk, vector in zip(chunks, vectors, strict=True):
                    session.add(Chunk(id=chunk.chunk_id, paper_id=paper_id, ordinal=chunk.metadata['ordinal'], text=chunk.text,
                                      section=chunk.section, page=chunk.page,
                                      token_count=len(chunk.text.split()), vector_id=chunk.chunk_id, embedding_json=vector))
                await session.commit()
        await retry_sqlite_locked(op)
