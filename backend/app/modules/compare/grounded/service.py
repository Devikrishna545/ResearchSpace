"""Read-side helpers for evidence ledgers, artifacts, grounded reports and job diagnostics."""

from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.auth import owner_id
from app.core.config import Settings
from app.db.session import SessionLocal
from app.modules.compare.grounded.evidence import load_artifacts, stale_reason
from app.modules.compare.grounded.extraction import load_facts
from app.modules.compare.grounded.report import artifact_dict, fact_dict
from app.modules.compare.orm.grounded import AnalysisJob, DocumentArtifact, LLMCallLog, PaperEvidenceBuild
from app.modules.papers.orm.paper import Paper


async def evidence_ledger(settings: Settings, paper_id: str) -> dict:
    async with SessionLocal() as session:
        paper = await session.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_id == owner_id()))
        if not paper:
            raise HTTPException(404, "Resource not found")
        build = await session.scalar(select(PaperEvidenceBuild).where(PaperEvidenceBuild.paper_id == paper_id,
                                                                      PaperEvidenceBuild.is_current.is_(True)).limit(1))
        versions = (await session.execute(select(PaperEvidenceBuild.version, PaperEvidenceBuild.created_at, PaperEvidenceBuild.status)
                                           .where(PaperEvidenceBuild.paper_id == paper_id).order_by(PaperEvidenceBuild.version.desc()))).all()
    if build is None:
        return {"paper_id": paper_id, "title": paper.title, "build": None, "stale_reason": "no evidence build", "facts": [], "audit": []}
    stale = stale_reason(build, paper, settings.grounded_embed_model)
    facts = await load_facts(build.id)
    artifacts = await load_artifacts(build.id)
    kinds: dict[str, int] = {}
    for artifact in artifacts:
        kinds[artifact.kind] = kinds.get(artifact.kind, 0) + 1
    return {
        "paper_id": paper_id, "title": paper.title, "stale_reason": stale,
        "build": {"build_id": build.id, "version": build.version, "status": build.status, "text_source": build.text_source,
                  "page_count": build.page_count, "scanned": build.scanned, "quality_flags": build.quality_flags or [],
                  "parser_version": build.parser_version, "embed_model": build.embed_model,
                  "detected_metadata": (build.doc_metadata or {}).get("detected", {}),
                  "extraction": (build.doc_metadata or {}).get("extraction", {}), "artifact_counts": kinds,
                  "created_at": build.created_at.isoformat() if build.created_at else None},
        "versions": [{"version": v, "created_at": c.isoformat() if c else None, "status": s} for v, c, s in versions],
        "facts": [fact_dict(f) for f in facts if f.extraction_status == "validated"],
        "audit": [fact_dict(f) for f in facts if f.extraction_status != "validated"],
    }


async def owned_artifact(artifact_id: str) -> DocumentArtifact:
    async with SessionLocal() as session:
        artifact = await session.scalar(select(DocumentArtifact).join(Paper, Paper.id == DocumentArtifact.paper_id)
                                        .where(DocumentArtifact.id == artifact_id, Paper.owner_id == owner_id()))
    if not artifact:
        raise HTTPException(404, "Resource not found")
    return artifact


async def artifact_image(artifact_id: str) -> Path:
    from app.modules.papers.ingestion.upload import _owner_directory

    artifact = await owned_artifact(artifact_id)
    if not artifact.image_path:
        raise HTTPException(404, "No rendered image for this source")
    path = Path(artifact.image_path).resolve()
    root = _owner_directory().resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise HTTPException(404, "Rendered image unavailable")
    return path


async def artifact_detail(artifact_id: str) -> dict:
    return artifact_dict(await owned_artifact(artifact_id))


async def job_diagnostics(job_id: str) -> dict:
    """Parser defects, model failures and source-extraction problems, counted separately."""
    async with SessionLocal() as session:
        if not await session.scalar(select(AnalysisJob.id).where(AnalysisJob.id == job_id, AnalysisJob.owner_id == owner_id())):
            raise HTTPException(404, "job not found")
        rows = (await session.execute(select(LLMCallLog.purpose, LLMCallLog.parse_status, func.count(), func.avg(LLMCallLog.latency_ms))
                                      .where(LLMCallLog.job_id == job_id).group_by(LLMCallLog.purpose, LLMCallLog.parse_status))).all()
    by_status: dict[str, int] = {}
    calls = []
    for purpose, status, count, latency in rows:
        by_status[status] = by_status.get(status, 0) + count
        calls.append({"purpose": purpose, "parse_status": status, "count": count, "avg_latency_ms": int(latency or 0)})
    return {"job_id": job_id, "by_parse_status": by_status,
            "parser_defects": by_status.get("parser_defect", 0),
            "model_failures": sum(by_status.get(s, 0) for s in ("model_error", "model_invalid_json", "model_empty")),
            "calls": calls}
