import copy

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.legacy_claim_audit import LegacyClaimAudit
from app.modules.auth import api as auth_api
from app.modules.auth.orm.user import User
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.papers.orm.paper_profile import PaperProfile
from app.modules.spaces.orm.research_space import ResearchSpace


@pytest.fixture
async def warning_app(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'warning.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    admin = User(id="admin", email="admin@example.invalid", is_admin=True)
    async with sessions() as session:
        session.add(admin)
        await session.flush()
        session.add(ResearchSpace(id="space", user_id=admin.id, name="Test"))
        session.add(LegacyClaimAudit(
            user_id=admin.id,
            foreign_key_violations=[{"historical": n} for n in range(17)],
            comparison_orphans=[{"historical": n} for n in range(3)],
            unreferenced_paper_ids=[],
        ))
        session.add(PaperProfile(id="orphan", paper_id="missing-paper"))
        await session.commit()
    monkeypatch.setattr(auth_api, "SessionLocal", sessions)

    async def current_user(_request):
        return admin

    monkeypatch.setattr(auth_api, "current_user", current_user)
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/v1/auth")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8321",
        headers={"Origin": "http://localhost:3000"},
    ) as client:
        yield client, sessions, admin
    await engine.dispose()


async def test_warning_uses_live_references_without_overwriting_historical_audit(warning_app):
    client, sessions, _ = warning_app
    async with sessions() as session:
        audit = await session.get(LegacyClaimAudit, "admin")
        before = copy.deepcopy((audit.foreign_key_violations, audit.comparison_orphans))
    response = await client.get("/v1/auth/status")
    assert response.status_code == 200
    warning = response.json()["legacy_warning"]
    assert warning["foreign_key_violations"] == 1
    assert warning["comparison_orphans"] == 0
    async with sessions() as session:
        audit = await session.get(LegacyClaimAudit, "admin")
        assert (audit.foreign_key_violations, audit.comparison_orphans) == before
        assert await session.get(PaperProfile, "orphan") is not None


async def test_warning_clears_when_current_issues_are_resolved(warning_app):
    client, sessions, _ = warning_app
    async with sessions() as session:
        await session.execute(delete(PaperProfile))
        await session.commit()
    assert (await client.get("/v1/auth/status")).json()["legacy_warning"] is None


async def test_comparison_count_uses_current_reports_not_number_of_missing_papers(warning_app):
    client, sessions, _ = warning_app
    async with sessions() as session:
        session.add(ComparisonReport(id="report", space_id="space", paper_ids=["missing-a", "missing-b"]))
        await session.commit()
    warning = (await client.get("/v1/auth/status")).json()["legacy_warning"]
    assert warning["comparison_orphans"] == 1
    assert warning["foreign_key_violations"] == 1


async def test_warning_remains_admin_only(warning_app, monkeypatch):
    client, _, admin = warning_app
    admin.is_admin = False
    assert (await client.get("/v1/auth/status")).json()["legacy_warning"] is None

    async def anonymous(_request):
        raise HTTPException(401, "not authenticated")

    monkeypatch.setattr(auth_api, "current_user", anonymous)
    response = (await client.get("/v1/auth/status")).json()
    assert response["authenticated"] is False
    assert response["legacy_warning"] is None
