"""Deterministic PDF parsing into page-aware source units. No LLM is called here."""

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.papers.service import NUMBERED_HEADING, _canonical_heading, _section_segments

logger = logging.getLogger(__name__)

TARGET_TOKENS = 700
MIN_TOKENS = 500
MAX_TOKENS = 1000
SCANNED_CHAR_THRESHOLD = 40
DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;)])", re.I)
TABLE_CAPTION = re.compile(r"^\s*(?:TABLE|Table)\s+([0-9]+|[IVXL]+)\s*[.:|]?\s*(.*)$")
FIGURE_CAPTION = re.compile(r"^\s*(?:FIGURE|Figure|Fig\.)\s+([0-9]+)\s*[.:|]?\s*(.*)$")


def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.33) + 1


def content_hash(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()


@dataclass
class ParsedTable:
    page: int
    index: int
    cells: list[list[str]]
    bbox: tuple[float, float, float, float] | None = None
    label: str | None = None
    caption: str | None = None


@dataclass
class Caption:
    page: int
    kind: str
    number: str
    text: str


@dataclass
class ParsedDocument:
    pages: list[str]
    page_has_images: list[bool]
    tables: list[ParsedTable] = field(default_factory=list)
    captions: list[Caption] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    total_pages: int = 0
    flags: list[str] = field(default_factory=list)

    @property
    def scanned_pages(self) -> list[int]:
        return [i + 1 for i, (text, images) in enumerate(zip(self.pages, self.page_has_images))
                if len(text.strip()) < SCANNED_CHAR_THRESHOLD and images]

    @property
    def is_scanned(self) -> bool:
        return bool(self.pages) and len(self.scanned_pages) >= max(1, len(self.pages) // 2)


def _captions(page_number: int, text: str) -> list[Caption]:
    found = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for kind, pattern in (("table", TABLE_CAPTION), ("figure", FIGURE_CAPTION)):
            match = pattern.match(line)
            if not match:
                continue
            body = match.group(2).strip()
            j = i + 1
            while j < len(lines) and len(body) < 300 and lines[j].strip() and not body.endswith("."):
                body = f"{body} {lines[j].strip()}".strip()
                j += 1
            label = f"{'Table' if kind == 'table' else 'Figure'} {match.group(1)}"
            found.append(Caption(page=page_number, kind=kind, number=match.group(1), text=f"{label}: {body}" if body else label))
    unique = {}
    for caption in found:
        unique.setdefault((caption.kind, caption.number), caption)
    return list(unique.values())


def _page_texts(data: bytes, max_pages: int) -> list[str]:
    """pypdf keeps two-column reading order (and matches the app's ingestion text); pdfplumber
    interleaves columns line by line and, at its default tolerance, merges words."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return [(page.extract_text() or "").strip() for page in reader.pages[:max_pages]]
    except Exception:
        logger.warning("pypdf text extraction failed; falling back to pdfplumber", exc_info=True)
        return []


def parse_pdf_bytes(data: bytes, max_pages: int = 300) -> ParsedDocument:
    """Extract per-page text, tables with cell grids, captions and metadata."""
    import pdfplumber

    pages, images, tables, captions, flags = [], [], [], [], []
    metadata: dict = {}
    total = 0
    primary = _page_texts(data, max_pages)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        total = len(pdf.pages)
        info = pdf.metadata or {}
        metadata = {k: str(v) for k, v in {"title": info.get("Title"), "authors": info.get("Author"),
                                             "creation_date": info.get("CreationDate")}.items() if v}
        if total > max_pages:
            flags.append("page_limit_truncated")
        for number, page in enumerate(pdf.pages[:max_pages], start=1):
            text = primary[number - 1] if number - 1 < len(primary) else ""
            if not text:
                try:
                    text = page.extract_text(x_tolerance=1.5) or ""
                except Exception:
                    text = ""
                    flags.append(f"text_extraction_failed:p{number}")
            pages.append(text.strip())
            images.append(bool(page.images))
            page_captions = _captions(number, text)
            captions.extend(page_captions)
            try:
                found = page.find_tables()
            except Exception:
                found = []
                flags.append(f"table_detection_failed:p{number}")
            table_captions = [c for c in page_captions if c.kind == "table"]
            for index, table in enumerate(found):
                grid = [["" if cell is None else " ".join(str(cell).split()) for cell in row] for row in (table.extract() or [])]
                grid = [row for row in grid if any(row)]
                if len(grid) < 2 or max((len(r) for r in grid), default=0) < 2:
                    continue
                caption = table_captions[index] if index < len(table_captions) else None
                tables.append(ParsedTable(page=number, index=index, cells=grid, bbox=tuple(table.bbox),
                                          label=caption and caption.text.split(":")[0], caption=caption and caption.text))
    doi = next((m.group(1) for text in pages[:2] for m in [DOI.search(text)] if m), None)
    if doi:
        metadata["doi"] = doi
    year = re.search(r"D:(\d{4})", metadata.get("creation_date", ""))
    if year:
        metadata["year_from_pdf_metadata"] = int(year.group(1))
    metadata["page_count"] = total
    if not any(p.strip() for p in pages):
        flags.append("no_extractable_text")
    empty = [i + 1 for i, (text, has_image) in enumerate(zip(pages, images)) if not text.strip() and not has_image]
    if empty:
        flags.append(f"missing_pages:{','.join(map(str, empty[:20]))}")
    return ParsedDocument(pages=pages, page_has_images=images, tables=tables, captions=captions,
                          metadata=metadata, total_pages=total, flags=flags)


def _paragraphs(text: str) -> list[str]:
    """Split PDF text into paragraphs using blank lines, else short sentence-final lines."""
    if re.search(r"\n\s*\n", text):
        return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    lines = [line.rstrip() for line in text.splitlines()]
    if not lines:
        return []
    lengths = sorted(len(line) for line in lines if line.strip())
    typical = lengths[len(lengths) // 2] if lengths else 0
    paragraphs, current = [], []
    for line in lines:
        if not line.strip():
            continue
        current.append(line.strip())
        if line.rstrip().endswith((".", "?", "!", ":")) and len(line.strip()) < 0.8 * typical:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _split_long(paragraph: str) -> list[str]:
    if estimate_tokens(paragraph) <= MAX_TOKENS:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    pieces, current = [], ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and estimate_tokens(candidate) > TARGET_TOKENS:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    out = []
    step = int(TARGET_TOKENS / 1.33)
    for piece in pieces:
        if estimate_tokens(piece) > MAX_TOKENS:
            words = piece.split()
            out.extend(" ".join(words[i:i + step]) for i in range(0, len(words), step))
        else:
            out.append(piece)
    return out


def text_units(pages: list[str]) -> tuple[list[dict], list[str]]:
    """Paragraph-aligned chunks of roughly 500-1,000 tokens that never cross a page boundary.

    Headings are detected on raw lines before flattening; a section heading carries
    over onto the next page until a new heading appears.
    """
    flags = []
    has_numbered_outline = any(
        (match := NUMBERED_HEADING.fullmatch(" ".join(line.split())))
        and match.group("number") == "1"
        and _canonical_heading(match.group("title")) in {"Introduction", "Method"}
        for page in pages for line in page.splitlines()
    )
    units: list[dict] = []
    carried: str | None = None
    headings = 0
    for page_number, page_text in enumerate(pages, start=1):
        segments = _section_segments(page_text, allow_numbered=has_numbered_outline)
        for position, (segment_text, section) in enumerate(segments):
            if section:
                headings += 1
                carried = section
            elif position == 0 and carried:
                section = carried
            buffer: list[str] = []
            for paragraph in _paragraphs(segment_text):
                for piece in _split_long(paragraph):
                    candidate = " ".join([*buffer, piece])
                    if buffer and estimate_tokens(candidate) > MAX_TOKENS:
                        units.append({"text": " ".join(buffer), "page": page_number, "section": section})
                        buffer = [piece]
                    else:
                        buffer.append(piece)
                    if estimate_tokens(" ".join(buffer)) >= TARGET_TOKENS:
                        units.append({"text": " ".join(buffer), "page": page_number, "section": section})
                        buffer = []
            if buffer:
                units.append({"text": " ".join(buffer), "page": page_number, "section": section})
            if section and section.startswith("References"):
                carried = section
    if pages and not headings:
        flags.append("no_headings_detected")
    return [u for u in units if u["text"].strip()], flags


def table_text(cells: list[list[str]], caption: str | None = None) -> str:
    lines = [caption] if caption else []
    lines.extend(" | ".join(row) for row in cells)
    return "\n".join(lines)


def render_pages(data: bytes, page_numbers: list[int], directory: Path, prefix: str, scale: float = 2.0) -> dict[int, Path]:
    """Render only the requested pages to PNG for the vision model."""
    import pypdfium2 as pdfium

    directory.mkdir(parents=True, exist_ok=True)
    out = {}
    pdf = pdfium.PdfDocument(data)
    try:
        for number in sorted(set(page_numbers)):
            if not 1 <= number <= len(pdf):
                continue
            page = pdf[number - 1]
            try:
                image = page.render(scale=scale).to_pil()
                path = directory / f"{prefix}-p{number:03d}.png"
                image.save(path, format="PNG")
                out[number] = path
            finally:
                page.close()
    finally:
        pdf.close()
    return out
