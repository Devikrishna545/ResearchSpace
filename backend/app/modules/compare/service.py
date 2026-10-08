"""Read side for comparison reports.

Reports are produced by grounded compare jobs (app/modules/compare/grounded/jobs.py). Historical
profile-only reports stay untouched in the database but are hidden: they compared
generated profiles rather than source evidence.
"""

from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import owner_id
from app.core.config import Settings
from app.db.session import SessionLocal
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.compare.orm.grounded import PaperEvidenceBuild
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.compare.schemas.comparison import GROUNDED_REPORT_KIND, LEGACY_REPORT_GONE, ComparisonReportSummary


class CompareService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def list_reports(self, space_id: str) -> list[ComparisonReportSummary]:
        async with SessionLocal() as session:
            if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id()).limit(1)):
                raise HTTPException(status_code=404, detail="space not found")
            rows = (await session.execute(select(ComparisonReport).where(
                ComparisonReport.space_id == space_id, ComparisonReport.report_kind == GROUNDED_REPORT_KIND)
                .order_by(ComparisonReport.generated_at.desc()))).scalars().all()
        return [ComparisonReportSummary(id=row.id, paper_ids=row.paper_ids, generated_at=row.generated_at, report_kind=row.report_kind)
                for row in rows]

    async def get_report(self, report_id: str) -> dict:
        async with SessionLocal() as session:
            row = await session.scalar(select(ComparisonReport).join(ResearchSpace, ComparisonReport.space_id == ResearchSpace.id)
                                       .where(ComparisonReport.id == report_id, ResearchSpace.user_id == owner_id()))
            if not row:
                raise HTTPException(status_code=404, detail="comparison report not found")
            if row.report_kind != GROUNDED_REPORT_KIND:
                raise HTTPException(status_code=410, detail=LEGACY_REPORT_GONE)
            referenced = set(row.paper_ids or [])
            available = set((await session.scalars(select(Paper.id).where(Paper.id.in_(referenced), Paper.owner_id == owner_id()))).all())
            current_builds = dict((await session.execute(select(PaperEvidenceBuild.paper_id, PaperEvidenceBuild.id).where(
                PaperEvidenceBuild.paper_id.in_(referenced), PaperEvidenceBuild.is_current.is_(True)))).all())
        data = dict(row.report_json or {})
        used = data.get("builds") or {}
        stale = sorted(pid for pid, build_id in used.items() if current_builds.get(pid) != build_id)
        warnings = list((data.get("coverage") or {}).get("warnings") or [])
        if referenced - available:
            warnings.append("This report references papers that are no longer in your library.")
        data.pop("internal_audit", None)
        return {**data, "id": row.id, "space_id": row.space_id, "paper_ids": row.paper_ids, "generated_at": row.generated_at,
                "report_kind": GROUNDED_REPORT_KIND, "job_id": row.job_id, "stale_paper_ids": stale, "warnings": warnings,
                "stale_warning": "Evidence for some papers was rebuilt after this report; re-run the comparison to refresh it." if stale else None}
