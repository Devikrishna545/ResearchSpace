from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.session import configure_sqlite_pragmas
from app.db.models import Base
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.auth.orm.user import User
from app.modules.compare import service as compare_service
from app.modules.compare.service import CompareService


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = configure_sqlite_pragmas(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compare.db'}", future=True))
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        session.add(User(id="test-owner", email="owner@example.com", is_admin=False))
        await session.flush()
        session.add(ResearchSpace(id="s1", user_id="test-owner", name="S"))
        await session.commit()
    monkeypatch.setattr(compare_service, "SessionLocal", session_local)
    yield session_local
    await engine.dispose()


async def test_reports_list_only_grounded_newest_first_and_legacy_is_retired(db):
    now = datetime.now(timezone.utc)
    async with db() as session:
        session.add(ComparisonReport(id="legacy", space_id="s1", paper_ids=["a", "b"], matrix={}, confidence=0.9, generated_at=now))
        session.add(ComparisonReport(id="old", space_id="s1", paper_ids=["a", "b"], report_kind="grounded", report_json={"builds": {}},
                                     generated_at=now - timedelta(hours=1)))
        session.add(ComparisonReport(id="new", space_id="s1", paper_ids=["a", "b"], report_kind="grounded",
                                     report_json={"builds": {}, "internal_audit": {"x": 1}, "coverage": {"warnings": ["w"]}}, generated_at=now))
        await session.commit()
    service = CompareService(Settings())
    assert [r.id for r in await service.list_reports("s1")] == ["new", "old"]
    report = await service.get_report("new")
    assert report["report_kind"] == "grounded" and "internal_audit" not in report
    assert "no longer in your library" in report["warnings"][-1]
    with pytest.raises(HTTPException) as retired:
        await service.get_report("legacy")
    assert retired.value.status_code == 410
    with pytest.raises(HTTPException) as missing:
        await service.list_reports("other-space")
    assert missing.value.status_code == 404


def test_legacy_sync_compare_route_is_removed():
    from app.main import create_app

    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    assert "/v1/spaces/{space_id}/compare" not in paths
    assert "/v1/spaces/{space_id}/comparisons" in paths
    assert "/v1/comparisons/{report_id}" in paths
    assert "/v1/spaces/{space_id}/compare-jobs" in paths
