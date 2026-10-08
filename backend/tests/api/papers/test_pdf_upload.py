import asyncio
import io
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest


def pdf_bytes(*texts: str, title: str | None = None) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            content = DecodedStreamObject()
            content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(content)
    if title:
        writer.add_metadata({"/Title": title})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_upload_auth_and_owner_isolation(tmp_path, monkeypatch):
    if not os.environ.get("UPLOAD_TEST_ISOLATED"):
        env = {
            **os.environ, "UPLOAD_TEST_ISOLATED": "1",
            "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'upload.db'}",
            "UPLOAD_DIR": str(tmp_path / "owner-uploads"),
        }
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(Path(__file__).resolve()), "-k", "test_upload_auth_and_owner_isolation"],
            cwd=Path(__file__).resolve().parents[3], env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return

    from app.core.auth import password_hash
    from app.db.session import SessionLocal
    from app.main import app
    from app.modules.spaces.orm.research_space import ResearchSpace
    from app.modules.auth.orm.user import User
    from app.modules.papers import api as papers
    from app.core import upload_limit
    from app.modules.papers.ingestion import upload as pdf_upload

    database = Path(os.environ["DATABASE_URL"].split("///", 1)[1])
    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[3], env=os.environ, capture_output=True, text=True,
    )
    assert migration.returncode == 0, migration.stdout + migration.stderr

    async def seed():
        async with SessionLocal() as session:
            session.add_all([
                User(id="alice", email="alice@example.com", password_hash=password_hash("alice-password-long")),
                User(id="bob", email="bob@example.com", password_hash=password_hash("bob-password-long")),
            ])
            await session.flush()
            session.add_all([
                ResearchSpace(id="alice-space", user_id="alice", name="Private library"),
                ResearchSpace(id="alice-other", user_id="alice", name="Other library"),
                ResearchSpace(id="bob-space", user_id="bob", name="Separate library"),
            ])
            await session.commit()

    asyncio.run(seed())

    class Embedder:
        async def embed(self, texts, model):
            assert model
            return [[float(i + 1), 1.0] for i in range(len(texts))]

    monkeypatch.setattr(papers._upload_service, "llm", Embedder())
    origin = {"Origin": "http://localhost:3000"}

    def sign_in(client: TestClient, email: str, password: str):
        csrf = client.get("/v1/auth/status", headers=origin).json()["csrf_token"]
        headers = {**origin, "X-CSRF-Token": csrf}
        response = client.post("/v1/auth/login", json={"email": email, "password": password}, headers=headers)
        assert response.status_code == 200, response.text
        return headers

    ready_pdf = pdf_bytes("Original scientific evidence on page one.", "More evidence on page two.", title="Metadata title")
    with TestClient(app, base_url="http://localhost:8321") as alice, TestClient(app, base_url="http://localhost:8321") as bob:
        unauth = alice.post("/v1/spaces/alice-space/papers/upload", files={"file": ("paper.pdf", ready_pdf, "application/pdf")}, headers=origin)
        assert unauth.status_code == 401
        alice_headers = sign_in(alice, "alice@example.com", "alice-password-long")
        bob_headers = sign_in(bob, "bob@example.com", "bob-password-long")
        no_csrf = alice.post("/v1/spaces/alice-space/papers/upload", files={"file": ("paper.pdf", ready_pdf, "application/pdf")}, headers=origin)
        assert no_csrf.status_code == 403
        wrong_origin = alice.post("/v1/spaces/alice-space/papers/upload", files={"file": ("paper.pdf", ready_pdf, "application/pdf")}, headers={**alice_headers, "Origin": "https://attacker.example"})
        assert wrong_origin.status_code == 403
        denied = bob.post("/v1/spaces/alice-space/papers/upload", files={"file": ("paper.pdf", ready_pdf, "application/pdf")}, headers=bob_headers)
        assert denied.status_code == 404

        uploaded = alice.post("/v1/spaces/alice-space/papers/upload",
                              files={"file": ("paper.pdf", ready_pdf, "application/pdf")},
                              data={"title": "Custom <i>research</i> title"}, headers=alice_headers)
        assert uploaded.status_code == 200, uploaded.text
        job = uploaded.json()
        assert job["status"] == "READY"
        content = alice.get(f"/v1/papers/{job['paper_id']}/content?space_id=alice-space", headers=origin).json()
        assert content["paper"]["title"] == "Custom research title"
        assert content["paper"]["local_pdf_available"]
        assert [item["page"] for item in content["chunks"]] == [1, 2]
        assert "scientific evidence" in content["chunks"][0]["text"]
        stored_pdf = alice.get(f"/v1/papers/{job['paper_id']}/file", headers=origin)
        assert stored_pdf.status_code == 200 and stored_pdf.content == ready_pdf
        assert bob.get(f"/v1/papers/{job['paper_id']}/file", headers=origin).status_code == 404
        assert bob.get(f"/v1/papers/{job['paper_id']}/content", headers=origin).status_code == 404

        repeated = alice.post("/v1/spaces/alice-other/papers/upload",
                              files={"file": ("again.pdf", ready_pdf, "application/pdf")}, headers=alice_headers)
        assert repeated.status_code == 200 and repeated.json()["paper_id"] == job["paper_id"]
        assert repeated.json()["status"] == "READY"
        other_owner = bob.post("/v1/spaces/bob-space/papers/upload",
                               files={"file": ("same.pdf", ready_pdf, "application/pdf")}, headers=bob_headers)
        assert other_owner.status_code == 200 and other_owner.json()["paper_id"] != job["paper_id"]
        assert alice.get(f"/v1/papers/{other_owner.json()['paper_id']}/file", headers=origin).status_code == 404

        invalid = alice.post("/v1/spaces/alice-space/papers/upload",
                             files={"file": ("looks-like.pdf", b"<html>not a PDF</html>", "application/pdf")}, headers=alice_headers)
        assert invalid.status_code == 422
        corrupt = alice.post("/v1/spaces/alice-space/papers/upload",
                             files={"file": ("broken.pdf", b"%PDF-<html>not a valid PDF</html>", "application/pdf")}, headers=alice_headers)
        assert corrupt.status_code == 422

        scanned = alice.post("/v1/spaces/alice-space/papers/upload",
                             files={"file": ("../../escape.pdf", pdf_bytes(""), "application/pdf")}, headers=alice_headers)
        assert scanned.status_code == 200, scanned.text
        assert scanned.json()["status"] == "DEGRADED" and "OCR" in scanned.json()["message"]
        scanned_content = alice.get(f"/v1/papers/{scanned.json()['paper_id']}/content?space_id=alice-space", headers=origin).json()
        assert scanned_content["chunks"] == [] and scanned_content["paper"]["title"] == "escape"
        assert alice.get(f"/v1/papers/{scanned.json()['paper_id']}/file", headers=origin).content.startswith(b"%PDF-")

        with monkeypatch.context() as cap:
            cap.setattr(pdf_upload, "MAX_PDF_BYTES", 1024)
            too_big = alice.post("/v1/spaces/alice-space/papers/upload",
                                 files={"file": ("big.pdf", b"%PDF-" + b"x" * 1100, "application/pdf")}, headers=alice_headers)
            assert too_big.status_code == 413
        with monkeypatch.context() as cap:
            cap.setattr(upload_limit, "MAX_UPLOAD_BODY_BYTES", 100)
            envelope_too_big = alice.post("/v1/spaces/alice-space/papers/upload",
                                           files={"file": ("file.pdf", ready_pdf, "application/pdf")}, headers=alice_headers)
            assert envelope_too_big.status_code == 413

    with sqlite3.connect(database) as session:
        assert session.execute("SELECT count(*) FROM papers").fetchone()[0] == 3
        assert session.execute("SELECT count(*) FROM chunks").fetchone()[0] == 4
        assert session.execute("SELECT count(*) FROM pins").fetchone()[0] == 4
    storage = Path(os.environ["UPLOAD_DIR"])
    files = list(storage.rglob("*.pdf"))
    assert len(files) == 3
    assert all(f.parent != storage and f.name.endswith(".pdf") and len(f.stem) == 32 for f in files)
    assert not (tmp_path / "escape.pdf").exists()


def test_chunked_upload_body_is_capped_without_content_length(monkeypatch):
    from app.core import upload_limit

    monkeypatch.setattr(upload_limit, "MAX_UPLOAD_BODY_BYTES", 10)
    messages = iter([
        {"type": "http.request", "body": b"12345678", "more_body": True},
        {"type": "http.request", "body": b"90123456", "more_body": False},
    ])
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    async def app(scope, limited_receive, send_response):
        await limited_receive()
        await limited_receive()

    scope = {
        "type": "http", "method": "POST", "path": "/v1/spaces/space/papers/upload",
        "headers": [], "http_version": "1.1",
    }
    asyncio.run(upload_limit.UploadBodyLimitMiddleware(app)(scope, receive, send))
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


def test_upload_storage_refuses_paths_inside_the_repository(monkeypatch):
    from app.core.auth import _active_user_id
    from app.core.config import get_settings
    from app.modules.papers.ingestion.upload import PROJECT_ROOT, _owner_directory

    token = _active_user_id.set("synthetic-user")
    try:
        monkeypatch.setattr(get_settings(), "upload_dir", PROJECT_ROOT / "unapproved-upload-location")
        with pytest.raises(RuntimeError, match="outside the repository"):
            _owner_directory(create=True)
        assert not (PROJECT_ROOT / "unapproved-upload-location").exists()
    finally:
        _active_user_id.reset(token)
