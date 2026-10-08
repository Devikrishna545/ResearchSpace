import hashlib
import json
import os
import subprocess
import sys
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
from cryptography.fernet import Fernet


def test_bootstrap_sessions_csrf_and_cross_user_resources(tmp_path, monkeypatch):
    if not os.environ.get("AUTH_TEST_ISOLATED"):
        env = {**os.environ, "AUTH_TEST_ISOLATED": "1", "DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'research.db').as_posix()}"}
        isolated = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(Path(__file__).resolve()), "-k", "test_bootstrap_sessions_csrf_and_cross_user_resources"],
            cwd=Path(__file__).resolve().parents[3], env=env, capture_output=True, text=True,
        )
        assert isolated.returncode == 0, isolated.stdout + isolated.stderr
        return
    from sqlalchemy.engine import make_url
    database = Path(make_url(os.environ["DATABASE_URL"]).database)
    tmp_path = database.parent
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[3],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    from app.main import app
    from app.core.config import get_settings
    from app.modules.sharing import api as linkedin
    token = "isolated-one-time-secret"
    (tmp_path / "setup-token").write_text(hashlib.sha256(token.encode()).hexdigest())
    origin = {"Origin": "http://localhost:3000"}
    with TestClient(app, base_url="http://localhost:8321") as admin:
        status = admin.get("/v1/auth/status", headers=origin)
        assert status.status_code == 200
        assert status.json()["setup_required"]
        csrf = {**origin, "X-CSRF-Token": status.json()["csrf_token"]}
        rotated = subprocess.run(
            [sys.executable, "-m", "scripts.reset_setup_token"],
            cwd=Path(__file__).resolve().parents[3], env=env, capture_output=True, text=True,
        )
        assert rotated.returncode == 0, rotated.stdout + rotated.stderr
        token = rotated.stdout.strip().split("ONE-TIME FIRST-ADMIN SETUP TOKEN: ")[1]
        assert token not in (tmp_path / "setup-token-audit.log").read_text()
        missing_csrf = admin.post("/v1/auth/bootstrap", json={"token": token, "email": "admin@example.com", "password": "long-password-for-admin"}, headers=origin)
        assert missing_csrf.status_code == 403, missing_csrf.text
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("INSERT INTO pins(id,space_id,paper_id,pinned_at) VALUES ('broken','missing','missing','2026-01-01')")
        with closing(sqlite3.connect(database)) as db, db:
            assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
            db.execute("INSERT INTO research_spaces(id,name,status,created_at,updated_at) VALUES ('legacy-space','Legacy','active','2026-01-01','2026-01-01')")
            db.execute("INSERT INTO papers(id,doi,title,authors,citation_count,ingest_status,raw_payload,created_at) VALUES ('legacy-paper','10/legacy','Historic','[]',0,'READY','{}','2026-01-01')")
            db.execute("INSERT INTO chunks(id,paper_id,ordinal,text,token_count,embedding_json) VALUES ('legacy-chunk','legacy-paper',0,'Original preserved evidence',3,'[0.5,0.3]')")
            db.execute("INSERT INTO pins(id,space_id,paper_id,pinned_at) VALUES ('legacy-pin','legacy-space','legacy-paper','2026-01-01')")
            db.execute("INSERT INTO notes(id,space_id,paper_id,content,source,created_at,updated_at) VALUES ('legacy-note','legacy-space','legacy-paper','Original preserved note','manual','2026-01-01','2026-01-01')")
            db.execute("INSERT INTO comparison_reports(id,space_id,paper_ids,matrix,commonalities,contradictions,gaps,confidence,generated_at) VALUES ('legacy-report','legacy-space','[\"missing-paper\"]','{}','[{\"text\":\"Unverified legacy claim\"}]','[]','[]',1.0,'2026-01-01')")
            before_violations = db.execute("PRAGMA foreign_key_check").fetchall()
        first = admin.post("/v1/auth/bootstrap", json={"token": token, "email": "admin@example.com", "password": "long-password-for-admin"}, headers=csrf)
        assert first.status_code == 200, first.text
        assert first.json()["is_admin"]
        assert first.json()["claim"] == {"spaces": 1, "papers": 1, "unreferenced_papers": 0, "foreign_key_violations": 2, "comparison_orphans": 1}
        assert admin.get("/v1/auth/status", headers=origin).json()["legacy_warning"]["comparison_orphans"] == 1
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("PRAGMA foreign_key_check").fetchall() == before_violations
            assert db.execute("SELECT COUNT(*) FROM legacy_claim_audits").fetchone()[0] == 1
        assert admin.get("/v1/spaces/legacy-space", headers=origin).status_code == 200
        assert admin.get("/v1/papers/legacy-paper", headers=origin).status_code == 200
        assert admin.get("/v1/notes/legacy-note", headers=origin).json()["content"] == "Original preserved note"
        degraded = admin.get("/v1/comparisons/legacy-report", headers=origin)
        assert degraded.status_code == 410 and "profile-only" in degraded.json()["detail"]
        from app.platform.retrieval.ingest_store import get_chunks
        assert [chunk.chunk_id for chunk in get_chunks("legacy-space")] == ["legacy-chunk"]
        assert not (tmp_path / "setup-token").exists()
        assert subprocess.run(
            [sys.executable, "-m", "scripts.reset_setup_token"],
            cwd=Path(__file__).resolve().parents[3], env=env, capture_output=True,
        ).returncode != 0
        assert admin.post("/v1/auth/bootstrap", json={"token": token, "email": "again@example.com", "password": "long-password-for-admin"}, headers=csrf).status_code == 409
        created = admin.post("/v1/auth/users", json={"email": "reader@example.com", "password": "long-password-for-reader"}, headers=csrf)
        assert created.status_code == 200, created.text
        assert not created.json()["is_admin"]
        own = admin.post("/v1/spaces", json={"name": "Admin private space"}, headers=csrf)
        assert own.status_code == 200, own.text
        space_id = own.json()["id"]
        note = admin.post(f"/v1/spaces/{space_id}/notes", json={"content": "Private draft that must never be sent"}, headers=csrf)
        assert note.status_code == 200, note.text
        settings = get_settings()
        settings.linkedin_member_social_enabled = True
        settings.linkedin_client_id = "test-client"
        settings.linkedin_client_secret = "test-secret"
        settings.linkedin_token_key = Fernet.generate_key().decode()
        settings.linkedin_redirect_uri = "https://approved.example.com/v1/linkedin/callback"
        assert admin.get("/v1/linkedin/status", headers=origin).json()["connected"] is False
        connect = admin.post("/v1/linkedin/connect", headers=csrf)
        assert connect.status_code == 200, connect.text
        auth_url = connect.json()["authorization_url"]
        assert auth_url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
        state = parse_qs(urlparse(auth_url).query)["state"][0]
        requests_sent = []
        post_mode = {"value": "ok"}

        def linked_in(request: httpx.Request):
            requests_sent.append(request)
            if request.url.path.endswith("/accessToken"):
                return httpx.Response(200, json={"access_token": "mock-secret-token", "expires_in": 3600, "scope": "openid profile w_member_social"})
            if request.url.path.endswith("/userinfo"):
                assert request.headers["authorization"] == "Bearer mock-secret-token"
                return httpx.Response(200, json={"sub": "member-123"})
            if request.url.path.endswith("/posts"):
                assert request.headers["authorization"] == "Bearer mock-secret-token"
                if post_mode["value"] == "timeout":
                    raise httpx.ReadTimeout("outcome unknown")
                if post_mode["value"] == "connect_failure":
                    raise httpx.ConnectError("request not sent")
                return httpx.Response(201, headers={"x-restli-id": "urn:li:share:123"})
            raise AssertionError(f"Unexpected request: {request.url}")

        real_client = httpx.AsyncClient
        monkeypatch.setattr(linkedin.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(linked_in), **kwargs))
        callback = admin.get("/v1/linkedin/callback", params={"state": state, "code": "one-use-code"}, headers=origin, follow_redirects=False)
        assert callback.status_code == 303, callback.text
        assert admin.get("/v1/linkedin/callback", params={"state": state, "code": "replay"}, headers=origin, follow_redirects=False).status_code == 403
        assert admin.get("/v1/linkedin/status", headers=origin).json()["connected"]
        with closing(sqlite3.connect(database)) as db:
            saved = db.execute("SELECT encrypted_token FROM linkedin_connections").fetchone()[0]
            assert "mock-secret-token" not in saved
        post = {
            "source_type": "note", "source_id": note.json()["id"],
            "text": "Edited and redacted text only", "visibility": "CONNECTIONS",
            "confirmed": True, "request_id": str(uuid4()),
        }
        published = admin.post("/v1/linkedin/publish", json=post, headers=csrf)
        assert published.status_code == 200, published.text
        sent = [r for r in requests_sent if r.url.path.endswith("/posts")]
        assert len(sent) == 1
        outgoing = json.loads(sent[0].content)
        assert outgoing["commentary"] == post["text"]
        assert outgoing["visibility"] == "CONNECTIONS"
        assert outgoing["author"] == "urn:li:person:member-123"
        assert "Private draft" not in json.dumps(outgoing)
        assert admin.post("/v1/linkedin/publish", json=post, headers=csrf).status_code == 409
        assert len([r for r in requests_sent if r.url.path.endswith("/posts")]) == 1
        legacy_finding = {**post, "source_type": "finding", "source_id": "legacy-report", "finding_kind": "commonality", "finding_index": 0, "request_id": str(uuid4())}
        assert admin.post("/v1/linkedin/publish", json=legacy_finding, headers=csrf).status_code == 404
        assert len([r for r in requests_sent if r.url.path.endswith("/posts")]) == 1
        post_mode["value"] = "timeout"
        timeout_post = {**post, "request_id": str(uuid4())}
        uncertain = admin.post("/v1/linkedin/publish", json=timeout_post, headers=csrf)
        assert uncertain.status_code == 502 and "unknown" in uncertain.json()["detail"]
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT status FROM linkedin_post_attempts WHERE request_id=?", (timeout_post["request_id"],)).fetchone()[0] == "uncertain"
        assert admin.post("/v1/linkedin/publish", json=timeout_post, headers=csrf).status_code == 409
        assert len([r for r in requests_sent if r.url.path.endswith("/posts")]) == 2
        post_mode["value"] = "connect_failure"
        not_sent_post = {**post, "request_id": str(uuid4())}
        assert admin.post("/v1/linkedin/publish", json=not_sent_post, headers=csrf).status_code == 503
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT status FROM linkedin_post_attempts WHERE request_id=?", (not_sent_post["request_id"],)).fetchone()[0] == "not_sent"
        assert admin.post("/v1/linkedin/publish", json=not_sent_post, headers=csrf).status_code == 409
        assert admin.post("/v1/linkedin/disconnect", headers=csrf).status_code == 200
        assert not admin.get("/v1/linkedin/status", headers=origin).json()["connected"]
        assert admin.get(f"/v1/spaces/{space_id}", headers=origin).status_code == 200
        chat_session = admin.post(f"/v1/spaces/{space_id}/chat-sessions", json={"title": "Private thread"}, headers=csrf)
        assert chat_session.status_code == 200, chat_session.text
        chat_session_id = chat_session.json()["id"]
        assert admin.patch(f"/v1/chat-sessions/{chat_session_id}", json={"pinned": True}, headers=csrf).json()["pinned"]
        assert admin.post("/v1/spaces", json={"name": "Blocked"}, headers=origin).status_code == 403
        assert admin.post("/v1/spaces", json={"name": "Blocked"}, headers={**csrf, "Origin": "https://attacker.example"}).status_code == 403
        assert admin.get("/v1/spaces", headers={**origin, "Cookie": ""}).status_code == 401
        with TestClient(app, base_url="http://localhost:8321") as reader:
            handshake = reader.get("/v1/auth/status", headers=origin)
            reader_csrf = {**origin, "X-CSRF-Token": handshake.json()["csrf_token"]}
            assert reader.get(f"/v1/spaces/{space_id}", headers=origin).status_code == 401
            signed_in = reader.post("/v1/auth/login", json={"email": "reader@example.com", "password": "long-password-for-reader"}, headers=reader_csrf)
            assert signed_in.status_code == 200, signed_in.text
            assert reader.get(f"/v1/spaces/{space_id}", headers=origin).status_code == 404
            assert reader.get("/v1/spaces/legacy-space", headers=origin).status_code == 404
            assert reader.get("/v1/papers/legacy-paper", headers=origin).status_code == 404
            assert reader.get("/v1/notes/legacy-note", headers=origin).status_code == 404
            assert reader.get("/v1/spaces", headers=origin).json() == []
            assert reader.post("/v1/auth/users", json={"email": "no@example.com", "password": "long-password-for-user"}, headers=reader_csrf).status_code == 403
            assert reader.post(f"/v1/spaces/{space_id}/search", json={"query": "secret"}, headers=reader_csrf).status_code == 404
            assert reader.get(f"/v1/spaces/{space_id}/notes", headers=origin).status_code == 404
            assert reader.get(f"/v1/spaces/{space_id}/memory", headers=origin).status_code == 404
            assert reader.get(f"/v1/spaces/{space_id}/comparisons", headers=origin).status_code == 404
            assert reader.get(f"/v1/spaces/{space_id}/chat-sessions", headers=origin).status_code == 404
            assert reader.get(f"/v1/chat-sessions/{chat_session_id}", headers=origin).status_code == 404
            assert reader.get(f"/v1/chat-sessions/{chat_session_id}/turns", headers=origin).status_code == 404
            assert reader.patch(f"/v1/chat-sessions/{chat_session_id}", json={"title": "Taken"}, headers=reader_csrf).status_code == 404
            assert reader.delete(f"/v1/chat-sessions/{chat_session_id}", headers=reader_csrf).status_code == 404
            assert reader.post(f"/v1/chat-sessions/{chat_session_id}/compress", headers=reader_csrf).status_code == 404
            assert reader.post(f"/v1/spaces/{space_id}/papers/unpin", json={"paper_ids": ["legacy-paper"]}, headers=reader_csrf).status_code == 404
            assert reader.post("/v1/linkedin/publish", json={**post, "request_id": str(uuid4())}, headers=reader_csrf).status_code == 404
            with TestClient(app, base_url="http://localhost:8321") as other_session:
                other_csrf = {**origin, "X-CSRF-Token": other_session.get("/v1/auth/status", headers=origin).json()["csrf_token"]}
                credentials = {"email": "reader@example.com", "password": "long-password-for-reader"}
                assert other_session.post("/v1/auth/login", json=credentials, headers=other_csrf).status_code == 200
                assert reader.post("/v1/auth/logout", headers=reader_csrf).status_code == 200
                assert other_session.get("/v1/spaces", headers=origin).status_code == 200
                assert reader.post("/v1/auth/login", json=credentials, headers=reader_csrf).status_code == 200
                assert other_session.post("/v1/auth/logout-all", headers=other_csrf).status_code == 200
                assert reader.get("/v1/spaces", headers=origin).status_code == 401
            reset = admin.post(f"/v1/auth/users/{created.json()['id']}/reset-password", json={"password": "new-reader-password-long"}, headers=csrf)
            assert reset.status_code == 200
            assert reader.post("/v1/auth/login", json={"email": "reader@example.com", "password": "long-password-for-reader"}, headers=reader_csrf).status_code == 401
            assert reader.post("/v1/auth/login", json={"email": "reader@example.com", "password": "new-reader-password-long"}, headers=reader_csrf).status_code == 200
            with closing(sqlite3.connect(database)) as db, db:
                db.execute("UPDATE auth_sessions SET idle_expires_at='2000-01-01 00:00:00' WHERE user_id=?", (created.json()["id"],))
            assert reader.get("/v1/spaces", headers=origin).status_code == 401
        assert admin.get(f"/v1/spaces/{space_id}", headers=origin).status_code == 200
        assert admin.post("/v1/auth/logout", headers=csrf).status_code == 200
        assert admin.get("/v1/spaces", headers=origin).status_code == 401


def test_concurrent_bootstrap_creates_only_one_admin(tmp_path):
    if not os.environ.get("AUTH_TEST_ISOLATED"):
        env = {**os.environ, "AUTH_TEST_ISOLATED": "1", "DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'concurrent.db').as_posix()}"}
        isolated = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(Path(__file__).resolve()), "-k", "test_concurrent_bootstrap_creates_only_one_admin"],
            cwd=Path(__file__).resolve().parents[3], env=env, capture_output=True, text=True,
        )
        assert isolated.returncode == 0, isolated.stdout + isolated.stderr
        return
    from sqlalchemy.engine import make_url
    database = Path(make_url(os.environ["DATABASE_URL"]).database)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[3], env=dict(os.environ), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    from app.main import app
    token = "concurrent-one-time-token"
    (database.parent / "setup-token").write_text(hashlib.sha256(token.encode()).hexdigest())
    origin = {"Origin": "http://localhost:3000"}
    with TestClient(app, base_url="http://localhost:8321") as first, TestClient(app, base_url="http://localhost:8321") as second:
        headers = [
            {**origin, "X-CSRF-Token": client.get("/v1/auth/status", headers=origin).json()["csrf_token"]}
            for client in (first, second)
        ]
        def attempt(args):
            client, request_headers, email = args
            return client.post("/v1/auth/bootstrap", json={"token": token, "email": email, "password": "long-bootstrap-password"}, headers=request_headers).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [(first, headers[0], "first@example.com"), (second, headers[1], "second@example.com")]))
        assert results.count(200) == 1, results
        assert all(status in (200, 403, 409) for status in results), results
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT count(*) FROM users WHERE is_admin=1").fetchone()[0] == 1
