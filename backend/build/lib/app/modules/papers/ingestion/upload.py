import asyncio
import hashlib
import os
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.auth import owner_id
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.core.ownership import ensure_space_owned
from app.modules.papers.orm.chunk import Chunk
from app.modules.papers.orm.paper import Paper as PaperRow
from app.modules.spaces.orm.pin import Pin
from app.modules.papers.schemas.paper import IngestJob, IngestStatus
from app.modules.papers.service import MAX_PDF_BYTES, MAX_PDF_PAGES, PaperService, _chunk_pages, _validate_vectors
from app.db.retry import retry_sqlite_locked
from app.shared.text import clean_metadata_text

UPLOAD_BLOCK_BYTES = 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[5]


def _owner_directory(*, create: bool = False) -> Path:
    root = get_settings().upload_dir.expanduser().resolve()
    if root == PROJECT_ROOT or root.is_relative_to(PROJECT_ROOT):
        raise RuntimeError("Upload storage must be outside the repository")
    directory = root / hashlib.sha256(owner_id().encode("utf-8")).hexdigest()
    if os.name == "nt" and len(str(directory)) + 40 >= 248:
        raise RuntimeError("UPLOAD_DIR path is too long for Windows; choose a shorter directory")
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or (directory.exists() and directory.resolve().parent != root):
        raise RuntimeError("Upload storage owner directory is unsafe")
    return directory


def uploaded_pdf_path(paper_id: str) -> Path:
    return _owner_directory() / (hashlib.sha256(paper_id.encode("utf-8")).hexdigest()[:32] + ".pdf")


def _read_pdf(path: Path) -> tuple[list[str], str | None]:
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        if len(reader.pages) > MAX_PDF_PAGES:
            raise HTTPException(422, f"PDF exceeds the {MAX_PDF_PAGES}-page limit")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        metadata_title = clean_metadata_text(reader.metadata.title) if reader.metadata else None
    return pages, metadata_title


def _title(supplied: str | None, metadata: str | None, filename: str | None) -> str:
    safe_filename = PureWindowsPath(filename or "Uploaded paper.pdf").stem
    value = clean_metadata_text(supplied or metadata or safe_filename)
    value = " ".join("".join(char if char.isprintable() else " " for char in value).split()) if value else None
    if not value or len(value) > 300:
        raise HTTPException(422, "Enter a readable title of at most 300 characters")
    return value


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(UPLOAD_BLOCK_BYTES):
            digest.update(block)
    return digest.hexdigest()


class PdfUploadService(PaperService):
    async def ingest(self, space_id: str, uploaded: UploadFile, title: str | None = None) -> IngestJob:
        async with SessionLocal() as session:
            await ensure_space_owned(session, space_id)

        directory = _owner_directory(create=True)
        temporary = directory / (uuid4().hex + ".upload")
        digest = hashlib.sha256()
        first_bytes = b""
        length = 0
        try:
            with temporary.open("xb") as destination:
                temporary.chmod(0o600)
                try:
                    while block := await uploaded.read(UPLOAD_BLOCK_BYTES):
                        length += len(block)
                        if length > MAX_PDF_BYTES:
                            raise HTTPException(413, "PDF exceeds the 30 MB limit")
                        if len(first_bytes) < 5:
                            first_bytes += block[:5 - len(first_bytes)]
                        digest.update(block)
                        await asyncio.to_thread(destination.write, block)
                finally:
                    await uploaded.close()
            if first_bytes != b"%PDF-":
                raise HTTPException(422, "Upload must be a real PDF")
            try:
                pages, metadata_title = await asyncio.to_thread(_read_pdf, temporary)
            except (PdfReadError, ValueError, KeyError) as exc:
                raise HTTPException(422, "PDF could not be parsed") from exc
            name = _title(title, metadata_title, uploaded.filename)
            parts = _chunk_pages(pages)
            chunks = [part for part in parts if part["text"].strip()]
            vectors = await self.llm.embed([part["text"] for part in chunks], self.settings.ollama_model_embed) if chunks else []
            if chunks:
                from app.modules.chat.schemas.chat import ScoredChunk

                probe = [
                    ScoredChunk(chunk_id=str(i), paper_id="pending", text=part["text"])
                    for i, part in enumerate(chunks)
                ]
                _validate_vectors(probe, vectors)
            return await self._save(space_id, name, digest.hexdigest(), temporary, pages, chunks, vectors)
        finally:
            temporary.unlink(missing_ok=True)

    async def _save(
        self, space_id: str, title: str, content_hash: str, temporary: Path,
        pages: list[str], parts: list[dict], vectors: list[list[float]],
    ) -> IngestJob:
        owner = owner_id()

        async def persist():
            created_file: Path | None = None
            try:
                async with SessionLocal() as session:
                    async with session.begin():
                        await ensure_space_owned(session, space_id)
                        paper = await session.scalar(
                            select(PaperRow).where(PaperRow.owner_id == owner, PaperRow.content_hash == content_hash)
                        )
                        reused = paper is not None
                        if paper is None:
                            paper = PaperRow(
                                id=str(uuid4()), owner_id=owner, title=title, authors=[],
                                source="upload", content_hash=content_hash,
                                ingest_status=IngestStatus.READY.value if parts else IngestStatus.DEGRADED.value,
                                raw_payload={"capture_kind": "local_pdf"},
                            )
                            session.add(paper)
                            await session.flush()

                        destination = uploaded_pdf_path(paper.id)
                        if destination.exists():
                            if await asyncio.to_thread(_file_hash, destination) != content_hash:
                                raise RuntimeError("Stored PDF does not match the existing paper")
                        else:
                            await asyncio.to_thread(os.link, temporary, destination)
                            created_file = destination

                        pin = await session.scalar(
                            select(Pin.id).where(Pin.space_id == space_id, Pin.paper_id == paper.id)
                        )
                        if not pin:
                            session.add(Pin(id=str(uuid4()), space_id=space_id, paper_id=paper.id))

                        existing = (await session.execute(select(Chunk.id).where(Chunk.paper_id == paper.id).limit(1))).first()
                        if parts and not existing:
                            paper.ingest_status = IngestStatus.READY.value
                            for i, (part, vector) in enumerate(zip(parts, vectors, strict=True)):
                                chunk_id = f"{paper.id}-{i}"
                                session.add(Chunk(
                                    id=chunk_id, paper_id=paper.id, ordinal=i,
                                    section=part["section"], page=part["page"] if len(pages) > 1 else None,
                                    text=part["text"], token_count=len(part["text"].split()),
                                    vector_id=chunk_id, embedding_json=vector,
                                ))
                        await session.flush()
                        result = paper.id, paper.ingest_status, reused
                return result
            except Exception:
                if created_file:
                    created_file.unlink(missing_ok=True)
                raise

        try:
            paper_id, status, reused = await retry_sqlite_locked(persist)
        except IntegrityError:
            paper_id, status, reused = await retry_sqlite_locked(persist)
        if status != IngestStatus.READY.value:
            message = "PDF saved, but no extractable text was found. Run OCR before this paper can be cited."
        else:
            await self._load_chunks(space_id, paper_id)
            message = "Existing PDF reused" if reused else f"Uploaded and indexed {len(parts)} chunks"
        return IngestJob(job_id=str(uuid4()), paper_id=paper_id, status=IngestStatus(status), message=message)
