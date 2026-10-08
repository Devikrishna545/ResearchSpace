"""Freeze only paper evidence, never account credentials or application vectors."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
HEADINGS = re.compile(
    r"^(?:(\d+(?:\.\d+){0,3})\.?\s+)?"
    r"(abstract|introduction|background|related work|methods?|methodology|"
    r"model(?: architecture)?|experiments?|evaluation|results?|discussion|"
    r"limitations?|conclusions?|references|appendix|datasets?|training|"
    r"complexity|continuous bag.of.words.*|continuous skip.gram.*)(?:\s.*)?$", re.I,
)
NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-Z][^\n]{2,90})$")
CAPTION = re.compile(r"^(?:Table|TABLE|Figure|FIGURE|Fig\.)\s+(\d+|[IVX]+)\b")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def clean(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("\x00", "").strip()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Block:
    text: str
    page: int | None
    section: str = "Unknown"
    subsection: str = ""
    kind: str = "text"
    start: int = 0
    end: int = 0


@dataclass
class Document:
    doc_id: str
    title: str
    source_kind: str
    blocks: list[Block]
    flags: list[str] = field(default_factory=list)
    text: str = ""

    def finalize(self) -> None:
        parts: list[str] = []
        offset = 0
        for block in self.blocks:
            block.text = clean(block.text)
            block.start = offset
            parts.append(block.text)
            offset += len(block.text)
            block.end = offset
            offset += 2
        self.text = "\n\n".join(parts)


def paragraph_blocks(text: str, page: int | None, section: str = "Unknown",
                     subsection: str = "") -> tuple[list[Block], str, str]:
    result: list[Block] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            body = " ".join(pending).strip()
            kind = "figure" if re.match(r"^(?:Figure|FIGURE|Fig\.)\s", body) else (
                "table" if re.match(r"^(?:Table|TABLE)\s", body) else "text")
            result.append(Block(body, page, section, subsection, kind))
            pending.clear()

    for raw in clean(text).splitlines():
        line = raw.strip()
        numbered = NUMBERED.fullmatch(line)
        heading = len(line) < 100 and (
            HEADINGS.fullmatch(line) or
            (numbered and len(line.split()) < 12 and not re.search(r"[=;]|https?://", line))
        )
        if heading:
            flush()
            if numbered and "." in numbered.group(1):
                subsection = line
            else:
                section, subsection = line, ""
            pending.append(line)
        elif not line:
            flush()
        else:
            if CAPTION.match(line):
                flush()
            pending.append(line)
            if re.search(r"[.!?]$", line) and sum(len(s) for s in pending) >= 160:
                flush()
    flush()
    return result, section, subsection


def table_rows(table: list[list[str | None]]) -> tuple[list[list[str]], bool]:
    """Expand multiline cells only when their row counts agree exactly."""
    result: list[list[str]] = []
    ambiguous = False
    for row in table:
        cells = [clean(str(cell or "")) for cell in row]
        if not any(cells):
            continue
        lines = [[line.strip() for line in cell.splitlines() if line.strip()] for cell in cells]
        counts = {len(parts) for parts in lines}
        if len(counts) == 1 and next(iter(counts)) > 1:
            result.extend([list(parts) for parts in zip(*lines, strict=True)])
        else:
            ambiguous |= max(counts, default=0) > 1
            result.append([" ".join(cell.split()) for cell in cells])
    return result, ambiguous


def pdf_blocks(path: Path) -> tuple[list[Block], list[str]]:
    reader = PdfReader(path)
    if len(reader.pages) > 300:
        raise ValueError("Research snapshot refuses PDFs over 300 pages; choose an explicit subset.")
    blocks: list[Block] = []
    flags: list[str] = []
    section, subsection = "Unknown", ""
    with pdfplumber.open(path) as layout:
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if not text.strip():
                flags.append(f"no_text_page_{number}")
            page_blocks, section, subsection = paragraph_blocks(text, number, section, subsection)
            try:
                tables = layout.pages[number - 1].extract_tables()
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Table extraction failed on page {number}: {exc}") from exc
            grids: list[Block] = []
            for table in tables:
                rows, ambiguous = table_rows(table)
                if ambiguous:
                    flags.append(f"ambiguous_table_rows_page_{number}")
                if len(rows) >= 2 and max(map(len, rows)) >= 2:
                    grids.append(Block("\n".join(" | ".join(row) for row in rows),
                                       number, section, subsection, "table"))
            captions = [b for b in page_blocks if re.match(r"^Table\s+\d+\s*:", b.text)]
            for block in page_blocks:
                blocks.append(block)
                if block in captions and grids:
                    grid = grids.pop(0)
                    # Same caption/grid adjacency is available to every strategy.
                    block.text += "\n" + grid.text
            blocks.extend(grids)
    return blocks, flags


def merge_saved_chunks(rows: list[sqlite3.Row]) -> tuple[list[Block], int]:
    """Remove exact adjacent overlap, never invent original paragraph boundaries."""
    groups: list[tuple[int | None, str, list[str]]] = []
    removed = 0
    for row in rows:
        words = clean(row["text"]).split()
        section = row["section"] or "Unknown"
        if groups and groups[-1][:2] == (row["page"], section):
            prior = groups[-1][2]
            overlap = next((n for n in range(min(80, len(prior), len(words)), 4, -1)
                            if prior[-n:] == words[:n]), 0)
            prior.extend(words[overlap:])
            removed += overlap
        else:
            groups.append((row["page"], section, words))
    blocks: list[Block] = []
    for page, section, words in groups:
        body = " ".join(words)
        # Sentence grouping is explicitly reconstructed, not recovered PDF layout.
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", body)
        pending: list[str] = []
        for sentence in sentences:
            pending.append(sentence)
            if sum(len(s) for s in pending) >= 650:
                blocks.append(Block(" ".join(pending), page, section))
                pending.clear()
        if pending:
            blocks.append(Block(" ".join(pending), page, section))
    return blocks, removed


def snapshot(database: Path, upload_root: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError(f"Frozen snapshot already exists: {destination}")
    database = database.resolve(strict=True)
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    documents: list[Document] = []
    source_checks: list[dict] = []
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        owners = db.execute(
            "SELECT DISTINCT s.user_id FROM pins pi JOIN research_spaces s ON s.id=pi.space_id"
        ).fetchall()
        if len(owners) != 1:
            raise ValueError("Expected one pinned-paper owner; select an explicitly authorized corpus.")
        papers = db.execute(
            "SELECT DISTINCT p.id,p.owner_id,p.title,p.source,p.ingest_status FROM papers p "
            "JOIN pins pi ON pi.paper_id=p.id JOIN research_spaces s ON s.id=pi.space_id "
            "WHERE p.owner_id=s.user_id ORDER BY p.title"
        ).fetchall()
        for paper in papers:
            path = (upload_root / hashlib.sha256(paper["owner_id"].encode()).hexdigest()
                    / (hashlib.sha256(paper["id"].encode()).hexdigest()[:32] + ".pdf"))
            flags: list[str] = []
            if path.is_file():
                blocks, flags = pdf_blocks(path)
                source_kind = "local_pdf"
                source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                rows = db.execute(
                    "SELECT page,section,text,ordinal FROM chunks WHERE paper_id=? ORDER BY ordinal",
                    (paper["id"],),
                ).fetchall()
                blocks, removed = merge_saved_chunks(rows)
                source_kind = "saved_ingest_text"
                flags += ["original_pdf_layout_unavailable", "paragraphs_reconstructed",
                          f"exact_overlap_words_removed={removed}"]
                source_hash = digest([dict(r) for r in rows])
                if paper["ingest_status"] == "DEGRADED":
                    flags.append("limited_or_abstract_only")
            if not blocks:
                raise ValueError(f"No available evidence for pinned paper: {paper['title']}")
            doc = Document(paper["id"], paper["title"], source_kind, blocks, flags)
            doc.finalize()
            documents.append(doc)
            source_checks.append({"doc_id": doc.doc_id, "source_sha256": source_hash})
    finally:
        db.close()
    payload = {"version": 1, "documents": [asdict(doc) for doc in documents],
               "source_checks": source_checks}
    payload["sha256"] = digest(payload)
    write_json(destination, payload)
    return payload


def load_corpus(path: Path) -> list[Document]:
    data = read_json(path)
    expected = data.pop("sha256")
    if digest(data) != expected:
        raise ValueError("Frozen corpus checksum mismatch.")
    return [Document(**{**row, "blocks": [Block(**block) for block in row["blocks"]]})
            for row in data["documents"]]
