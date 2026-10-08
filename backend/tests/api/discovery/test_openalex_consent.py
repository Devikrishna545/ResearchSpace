import hashlib
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient


def test_per_user_consent_controls_openalex_requests(tmp_path, monkeypatch):
    if not os.environ.get("OPENALEX_TEST_ISOLATED"):
        env = {
            **os.environ,
            "OPENALEX_TEST_ISOLATED": "1",
            "DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'consent.db').as_posix()}",
        }
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(Path(__file__).resolve())],
            cwd=Path(__file__).resolve().parents[3], env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return

    backend = Path(__file__).resolve().parents[3]
    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend, env=dict(os.environ), capture_output=True, text=True,
    )
    assert migration.returncode == 0, migration.stdout + migration.stderr

    from sqlalchemy.engine import make_url
    from app.modules.discovery import api as search_routes
    from app.core.config import get_settings
    from app.main import app
    from app.platform.http import client as source_http

    get_settings().source_user_agent = "research-assistant/0.1 (mailto:local@example.invalid)"
    token = "isolated-consent-setup-token"
    database = Path(make_url(os.environ["DATABASE_URL"]).database)
    (database.parent / "setup-token").write_text(hashlib.sha256(token.encode()).hexdigest())
    origin = {"Origin": "http://localhost:3000"}
    requested = []

    def reply(request: httpx.Request):
        requested.append((request.url.params.get("mailto"), request.headers["user-agent"]))
        return httpx.Response(200, request=request, json={"results": []})

    source_client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    def mocked_source_client():
        return source_client
    mocked_source_client.cache_info = lambda: SimpleNamespace(currsize=0)
    monkeypatch.setattr(source_http, "get_source_client", mocked_source_client)

    class OpenAlexOnly:
        def __init__(self, registry):
            self.adapter = next(adapter for adapter in registry.adapters if adapter.name == "openalex")

        async def discover(self, body):
            await self.adapter.search(body)
            return {"ok": True}

    monkeypatch.setattr(search_routes, "DiscoveryService", OpenAlexOnly)
    with TestClient(app, base_url="http://localhost:8321") as admin:
        csrf = {**origin, "X-CSRF-Token": admin.get("/v1/auth/status", headers=origin).json()["csrf_token"]}
        setup = admin.post("/v1/auth/bootstrap", headers=csrf, json={
            "token": token, "email": "admin@research-institution.edu", "password": "long-admin-password",
        })
        assert setup.status_code == 200, setup.text
        assert admin.get("/v1/auth/status", headers=origin).json()["openalex_consent"]["state"] == "unset"
        admin_space = admin.post("/v1/spaces", headers=csrf, json={"name": "Own admin space"}).json()["id"]
        provision = admin.post("/v1/auth/users", headers=csrf, json={
            "email": "reader@research-institution.edu", "password": "long-reader-password",
        })
        assert provision.status_code == 200, provision.text
        with TestClient(app, base_url="http://localhost:8321") as reader:
            reader_csrf = {**origin, "X-CSRF-Token": reader.get("/v1/auth/status", headers=origin).json()["csrf_token"]}
            login = reader.post("/v1/auth/login", headers=reader_csrf, json={
                "email": "reader@research-institution.edu", "password": "long-reader-password",
            })
            assert login.status_code == 200, login.text
            assert reader.get("/v1/auth/openalex-consent", headers=origin).json()["state"] == "unset"
            reader_space = reader.post("/v1/spaces", headers=reader_csrf, json={"name": "Own reader space"}).json()["id"]

            def search(client, space, headers):
                response = client.post(f"/v1/spaces/{space}/search", headers=headers, json={"query": "research", "limit": 1})
                assert response.status_code == 200, response.text
                return requested[-1]

            assert search(reader, reader_space, reader_csrf)[0] is None
            assert admin.put("/v1/auth/openalex-consent", headers=csrf, json={"choice": "account"}).status_code == 422
            grant = admin.put("/v1/auth/openalex-consent", headers=csrf, json={"choice": "account", "consent": True})
            assert grant.status_code == 200, grant.text
            assert grant.json()["state"] == "granted"
            admin_contact = search(admin, admin_space, csrf)[0]
            assert admin_contact == "admin@research-institution.edu"
            no_contact, reader_agent = search(reader, reader_space, reader_csrf)
            assert no_contact is None and "mailto:" not in reader_agent

            decline = reader.put("/v1/auth/openalex-consent", headers=reader_csrf, json={"choice": "decline"})
            assert decline.status_code == 200 and decline.json()["contact_email"] is None
            assert search(reader, reader_space, reader_csrf)[0] is None
            change = reader.put("/v1/auth/openalex-consent", headers=reader_csrf, json={
                "choice": "custom", "contact_email": "custom@research-institution.edu", "consent": True,
            })
            assert change.status_code == 200, change.text
            assert search(reader, reader_space, reader_csrf)[0] == "custom@research-institution.edu"
            assert admin.get("/v1/auth/openalex-consent", headers=origin).json()["contact_email"] == admin_contact

            revoke = admin.put("/v1/auth/openalex-consent", headers=csrf, json={"choice": "decline"})
            assert revoke.status_code == 200 and revoke.json()["contact_email"] is None
            assert search(admin, admin_space, csrf)[0] is None
            assert search(reader, reader_space, reader_csrf)[0] == "custom@research-institution.edu"

    import asyncio
    asyncio.run(source_client.aclose())
