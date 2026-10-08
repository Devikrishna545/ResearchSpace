"""Acquire publicly accessible originals and audit every page before benchmarking."""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import asdict
from pathlib import Path
from time import sleep
from urllib.parse import urlparse

import httpx
import pdfplumber
from pypdf import PdfReader

from .corpus import LOCAL, ROOT, Document, clean, digest, pdf_blocks, read_json, write_json

ALLOWED_HOSTS = {"arxiv.org", "www.arxiv.org", "export.arxiv.org",
                 "aclanthology.org", "www.aclanthology.org"}
MAX_BYTES = 30 * 1024 * 1024
DATASET = LOCAL / "corpora" / "fullpdf-20261002"


def validate_url(url: str) -> None:
    value = urlparse(url)
    if (value.scheme != "https" or value.hostname not in ALLOWED_HOSTS
            or value.username or value.password or value.port not in (None, 443)):
        raise ValueError(f"Refusing an unapproved paper-download destination: {url}")


def fetch_pdf(client: httpx.Client, url: str, target: Path) -> dict:
    validate_url(url)
    provenance = target.with_suffix(".download.json")
    if target.exists():
        prior = read_json(provenance)
        if prior["requested_url"] != url or prior["sha256"] != hashlib.sha256(target.read_bytes()).hexdigest():
            raise ValueError(f"Existing download provenance/checksum mismatch: {target}")
        return prior
    current = url
    data = bytearray()
    final_url = ""
    for _ in range(6):
        validate_url(current)
        with client.stream("GET", current) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Paper redirect has no Location header.")
                current = str(response.url.join(location))
                continue
            response.raise_for_status()
            if "html" in response.headers.get("content-type", "").lower():
                raise ValueError(f"Repository returned HTML instead of PDF: {current}")
            for block in response.iter_bytes():
                data.extend(block)
                if len(data) > MAX_BYTES:
                    raise ValueError("Paper download exceeds the 30 MiB experiment limit.")
            final_url = str(response.url)
            break
    if not final_url or not data.startswith(b"%PDF-"):
        raise ValueError(f"Download is not a PDF or redirect limit exceeded: {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".pdf.tmp")
    temporary.write_bytes(data)
    try:
        reader = PdfReader(temporary)
        if not 1 < len(reader.pages) <= 300:
            raise ValueError("Expected an untruncated multipage research paper, at most 300 pages.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    record = {"requested_url": url, "final_url": final_url,
              "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
              "pages": len(reader.pages)}
    write_json(provenance, record)
    return record


def audit_pdf(path: Path, identity_pattern: str, blocks: list) -> dict:
    reader = PdfReader(path)
    if not re.search(identity_pattern, clean(reader.pages[0].extract_text() or ""), re.I):
        raise ValueError(f"Downloaded paper failed first-page identity check: {path.name}")
    page_audit = []
    with pdfplumber.open(path) as layout:
        if len(layout.pages) != len(reader.pages):
            raise ValueError("PDF parsers disagree about the page count.")
        for number, page in enumerate(reader.pages, 1):
            text = clean(page.extract_text() or "")
            page_blocks = [b for b in blocks if b.page == number]
            if len(text) < 40 or not page_blocks:
                raise ValueError(f"Page {number} has insufficient extractable text; no silent OCR/abstract fallback.")
            page_audit.append({
                "page": number, "raw_text_characters": len(text), "blocks": len(page_blocks),
                "images": len(layout.pages[number - 1].images),
                "table_units": sum(b.kind == "table" for b in page_blocks),
                "figure_units": sum(b.kind == "figure" for b in page_blocks),
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            })
    return {
        "total_pdf_pages": len(reader.pages), "processed_pages": len(page_audit),
        "empty_or_skipped_pages": [], "first_page_identity_verified": True,
        "page_audit": page_audit,
        "scope": "Every PDF page parsed; digital text and detected tables/captions retained. Figure pixels/equations are not guaranteed lossless; no vision model used.",
    }


def build(destination: Path = DATASET) -> dict:
    sources = read_json(ROOT / "pdf_sources.json")
    corpus_path = destination / "corpus.json"
    if corpus_path.exists():
        raise FileExistsError(f"Frozen full-PDF corpus already exists: {corpus_path}")
    docs = []
    checks = []
    with httpx.Client(timeout=120, follow_redirects=False, trust_env=False,
                      headers={"User-Agent": "R.Space local research benchmark (authorized PDF retrieval)"}) as client:
        for source in sources["documents"]:
            path = destination / "pdfs" / (source["doc_id"] + ".pdf")
            print("DOWNLOAD", source["title"], flush=True)
            for attempt in range(3):
                try:
                    download = fetch_pdf(client, source["pdf_url"], path)
                    break
                except httpx.HTTPError as exc:
                    print(f"Download attempt {attempt + 1} failed: {exc}", flush=True)
                    if attempt == 2:
                        raise
                    sleep(5 * (attempt + 1))
            blocks, flags = pdf_blocks(path)
            audit = audit_pdf(path, source["identity_pattern"], blocks)
            doc = Document(source["doc_id"], source["title"], "original_full_pdf", blocks, flags)
            doc.finalize()
            docs.append(asdict(doc))
            checks.append({**source, **download, **audit,
                           "ambiguous_table_pages": [f for f in flags if f.startswith("ambiguous_table")],
                           "known_section_count": len({b.section for b in blocks if b.section != "Unknown"})})
            print("EXTRACTED", source["doc_id"], "pages", audit["processed_pages"],
                  "blocks", len(blocks), "flags", flags, flush=True)
            sleep(3)
    payload = {"version": 2, "documents": docs, "source_checks": checks,
               "source_manifest_sha256": digest(sources), "source_policy": sources["access_policy"]}
    payload["sha256"] = digest(payload)
    write_json(corpus_path, payload)
    coverage = {"corpus_sha256": payload["sha256"],
                "documents": [{k: v for k, v in row.items() if k != "identity_pattern"} for row in checks]}
    write_json(destination / "extraction_audit.json", coverage)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DATASET)
    args = parser.parse_args()
    destination = args.destination.resolve()
    if not destination.is_relative_to(LOCAL.resolve()):
        raise ValueError("Full-PDF corpus must stay inside ignored research-local storage.")
    build(destination)


if __name__ == "__main__":
    main()
