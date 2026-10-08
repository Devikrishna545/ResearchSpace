"""Background compare jobs: persisted phases, progress, cancellation and resumable evidence."""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import owner_id
from app.core.config import Settings
from app.db.session import SessionLocal
from app.modules.compare.grounded import PARSER_VERSION
from app.modules.compare.grounded.deterministic import DeterministicComparator, PaperEvidence
from app.modules.compare.grounded.evidence import EvidenceBuilder, load_artifacts
from app.modules.compare.grounded.extraction import EXTRACT_PROMPT_VERSION, FactExtractor, JobCancelled, load_facts
from app.modules.compare.grounded.gaps import GAP_PROMPT_VERSION, GapAnalyzer
from app.modules.compare.grounded.llm import GroundedLLM
from app.modules.compare.grounded.novelty import NOVELTY_PROMPT_VERSION, CorpusService, NoveltyAssessor
from app.modules.compare.grounded.report import build_report
from app.modules.compare.grounded.retrieval import Retriever
from app.modules.compare.grounded.semantic import SEMANTIC_PROMPT_VERSION, SemanticComparator
from app.modules.compare.grounded.tiers import tier_config
from app.modules.compare.grounded.validation import VALIDATE_PROMPT_VERSION, FactValidator
from app.modules.compare.grounded.verifier import VERIFY_PROMPT_VERSION, FindingVerifier, apply_display_policy
from app.platform.llm.ollama_client import get_ollama_client
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.compare.orm.grounded import AnalysisJob, ComparisonFinding
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.compare.schemas.grounded import JOB_PHASES, TERMINAL_STATES, CompareJobRequest, JobDTO
from app.db.retry import retry_sqlite_locked

logger = logging.getLogger(__name__)
PROMPT_VERSIONS = {"extract": EXTRACT_PROMPT_VERSION, "validate": VALIDATE_PROMPT_VERSION, "semantic": SEMANTIC_PROMPT_VERSION,
                   "verify": VERIFY_PROMPT_VERSION, "gaps": GAP_PROMPT_VERSION, "novelty": NOVELTY_PROMPT_VERSION}
PHASE_PROGRESS = {"queued": 0.0, "parsing": 0.03, "indexing": 0.2, "extracting_facts": 0.25, "validating_facts": 0.55,
                  "comparing": 0.7, "computing_numerics": 0.76, "verifying_findings": 0.8, "identifying_candidate_gaps": 0.88,
                  "checking_novelty_optional": 0.93, "rendering_report": 0.97}
REPORT_SECTIONS = {"extracting_facts": "Evidence ledger", "comparing": "Deterministic comparison table",
                   "computing_numerics": "Numerical and dataset analysis", "verifying_findings": "Commonalities, differences and contradictions",
                   "identifying_candidate_gaps": "Candidate gaps", "checking_novelty_optional": "Novelty assessment",
                   "rendering_report": "Report"}
INTERRUPTED = "Interrupted (the server restarted). Re-run the comparison: completed evidence builds and facts are reused."

_tasks: dict[str, asyncio.Task] = {}
_cancelled: set[str] = set()
_slots: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def _slot() -> asyncio.Semaphore:
    # One job at a time: local models share one GPU.
    loop = asyncio.get_running_loop()
    if loop not in _slots:
        _slots[loop] = asyncio.Semaphore(1)
    return _slots[loop]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def facts_fingerprint(papers) -> str:
    """Changes whenever a fact is added, re-extracted or re-validated, invalidating cached reports."""
    parts = sorted(f"{f.id}:{f.extraction_status}" for p in papers for f in p.facts)
    parts += sorted(f"{p.paper_id}:{t}:{s.get('status')}" for p in papers for t, s in (p.extraction_state or {}).items())
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def pending_sections(job: AnalysisJob) -> list[str]:
    if job.state in TERMINAL_STATES:
        return []
    current = JOB_PHASES.index(job.state) if job.state in JOB_PHASES else 0
    wanted = [phase for phase in REPORT_SECTIONS if JOB_PHASES.index(phase) >= current]
    if not (job.params or {}).get("check_novelty"):
        wanted = [p for p in wanted if p != "checking_novelty_optional"]
    return [REPORT_SECTIONS[p] for p in wanted]


def to_dto(job: AnalysisJob) -> JobDTO:
    return JobDTO(id=job.id, space_id=job.space_id, state=job.state, progress=job.progress, params=job.params or {},
                  phase_log=job.phase_log or [], warnings=job.warnings or [], error=job.error, report_id=job.report_id,
                  cancel_requested=job.cancel_requested, pending_sections=pending_sections(job), created_at=job.created_at,
                  updated_at=job.updated_at, finished_at=job.finished_at)


class CompareJobService:
    def __init__(self, settings: Settings, client=None, pipeline_factory=None):
        self.settings = settings
        self.client = client or get_ollama_client()
        self.pipeline_factory = pipeline_factory or (lambda job_id, tier: GroundedComparePipeline(settings, self.client, job_id, tier))

    async def start(self, space_id: str, request: CompareJobRequest) -> JobDTO:
        paper_ids = sorted({str(p) for p in request.paper_ids if str(p).strip()})
        if len(paper_ids) < 2:
            raise HTTPException(422, "at least two distinct paper_ids are required")
        await validate_pins(space_id, paper_ids)
        tier = tier_config(self.settings, request.tier)
        job = AnalysisJob(id=str(uuid4()), owner_id=owner_id(), space_id=space_id, kind="compare", state="queued", progress=0.0,
                          params={**request.model_dump(), "paper_ids": paper_ids}, model_config_json=tier.as_dict(),
                          phase_log=[{"phase": "queued", "at": _now().isoformat(), "message": "Waiting for the local model queue"}],
                          warnings=[], cancel_requested=False, created_at=_now(), updated_at=_now())

        async def op():
            async with SessionLocal() as session:
                session.add(job)
                await session.commit()
        await retry_sqlite_locked(op)
        # The task copies this request's context, so owner_id() stays bound inside it.
        task = asyncio.create_task(self._run(job.id, request.tier))
        _tasks[job.id] = task
        task.add_done_callback(lambda _: _tasks.pop(job.id, None))
        return to_dto(job)

    async def _run(self, job_id: str, tier: str | None, factory=None):
        # Terminal writes are shielded so a second cancel cannot interrupt them mid-write.
        try:
            async with _slot():
                if job_id in _cancelled:
                    await asyncio.shield(update_job(job_id, state="cancelled", finished=True, message="Cancelled before start"))
                    return
                await (factory or self.pipeline_factory)(job_id, tier).run()
        except (asyncio.CancelledError, JobCancelled):
            await asyncio.shield(update_job(job_id, state="cancelled", finished=True, message="Cancelled"))
        except Exception as exc:
            logger.exception("Grounded compare job %s failed", job_id)
            await asyncio.shield(update_job(job_id, state="failed", finished=True, error=f"{type(exc).__name__}: {exc}"[:2000]))
        finally:
            _cancelled.discard(job_id)

    async def start_rebuild(self, paper_id: str, tier_name: str | None = None) -> JobDTO:
        async with SessionLocal() as session:
            space_id = await session.scalar(select(Pin.space_id).join(ResearchSpace, ResearchSpace.id == Pin.space_id)
                                            .join(Paper, Paper.id == Pin.paper_id)
                                            .where(Pin.paper_id == paper_id, Paper.owner_id == owner_id(), ResearchSpace.user_id == owner_id()).limit(1))
        if not space_id:
            raise HTTPException(404, "Resource not found")
        tier = tier_config(self.settings, tier_name)
        job = AnalysisJob(id=str(uuid4()), owner_id=owner_id(), space_id=space_id, kind="evidence_rebuild", state="queued",
                          progress=0.0, params={"paper_ids": [paper_id], "refresh": True, "tier": tier_name},
                          model_config_json=tier.as_dict(), phase_log=[{"phase": "queued", "at": _now().isoformat(), "message": "Queued"}],
                          warnings=[], cancel_requested=False, created_at=_now(), updated_at=_now())

        async def op():
            async with SessionLocal() as session:
                session.add(job)
                await session.commit()
        await retry_sqlite_locked(op)
        task = asyncio.create_task(self._run(job.id, tier_name, factory=lambda job_id, tier: EvidenceRebuildPipeline(self.settings, self.client, job_id, tier)))
        _tasks[job.id] = task
        task.add_done_callback(lambda _: _tasks.pop(job.id, None))
        return to_dto(job)

    async def get(self, job_id: str) -> JobDTO:
        job = await owned_job(job_id)
        if job.state not in TERMINAL_STATES and job_id not in _tasks:
            if job.cancel_requested:
                await update_job(job_id, state="cancelled", finished=True, message="Cancelled")
            else:
                await update_job(job_id, state="failed", finished=True, error=INTERRUPTED)
            job = await owned_job(job_id)
        return to_dto(job)

    async def list(self, space_id: str) -> list[JobDTO]:
        async with SessionLocal() as session:
            rows = (await session.execute(select(AnalysisJob).where(AnalysisJob.space_id == space_id, AnalysisJob.owner_id == owner_id())
                                          .order_by(AnalysisJob.created_at.desc()).limit(20))).scalars().all()
        return [to_dto(r) for r in rows]

    async def cancel(self, job_id: str) -> JobDTO:
        job = await owned_job(job_id)
        if job.state in TERMINAL_STATES:
            return to_dto(job)
        _cancelled.add(job_id)
        await update_job(job_id, cancel_requested=True, message="Cancellation requested")
        task = _tasks.get(job_id)
        if task is None:
            await update_job(job_id, state="cancelled", finished=True, message="Cancelled")
        else:
            # Stops an in-flight model call immediately; completed evidence stays reusable.
            task.cancel()
        return to_dto(await owned_job(job_id))


def stop_jobs(job_ids) -> None:
    """Cancel in-process jobs, e.g. before their space is deleted, so they release the model slot."""
    for job_id in job_ids:
        _cancelled.add(job_id)
        task = _tasks.get(job_id)
        if task is not None:
            task.cancel()


async def validate_pins(space_id: str, paper_ids: list[str]) -> None:
    async with SessionLocal() as session:
        if not await session.scalar(select(ResearchSpace.id).where(ResearchSpace.id == space_id, ResearchSpace.user_id == owner_id())):
            raise HTTPException(404, "space not found")
        pinned = set((await session.execute(select(Pin.paper_id).join(Paper, Paper.id == Pin.paper_id).where(
            Pin.space_id == space_id, Pin.paper_id.in_(paper_ids), Paper.owner_id == owner_id()))).scalars().all())
    missing = [p for p in paper_ids if p not in pinned]
    if missing:
        raise HTTPException(404, f"paper not pinned to space: {', '.join(missing)}")


async def owned_job(job_id: str) -> AnalysisJob:
    async with SessionLocal() as session:
        job = await session.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id, AnalysisJob.owner_id == owner_id()))
    if not job:
        raise HTTPException(404, "job not found")
    return job


async def update_job(job_id: str, *, state: str | None = None, progress: float | None = None, message: str | None = None,
                     warning: str | None = None, error: str | None = None, report_id: str | None = None,
                     cancel_requested: bool | None = None, finished: bool = False) -> None:
    async def op():
        async with SessionLocal() as session:
            job = await session.get(AnalysisJob, job_id)
            if job is None:
                return
            if state:
                if state not in TERMINAL_STATES and job.state in TERMINAL_STATES:
                    return
                job.state = state
                if state in PHASE_PROGRESS and progress is None:
                    job.progress = max(job.progress, PHASE_PROGRESS[state])
            if progress is not None:
                job.progress = max(job.progress, min(1.0, progress))
            if message or state:
                job.phase_log = [*(job.phase_log or []), {"phase": job.state, "at": _now().isoformat(), "message": message or job.state}][-200:]
            if warning and warning not in (job.warnings or []):
                job.warnings = [*(job.warnings or []), warning]
            if error:
                job.error = error
            if report_id:
                job.report_id = report_id
            if cancel_requested is not None:
                job.cancel_requested = cancel_requested
            if finished:
                job.finished_at = _now()
                if job.state in {"completed", "completed_with_warnings"}:
                    job.progress = 1.0
            job.updated_at = _now()
            await session.commit()
    await retry_sqlite_locked(op)


class GroundedComparePipeline:
    def __init__(self, settings: Settings, client, job_id: str, tier_name: str | None = None):
        self.settings = settings
        self.client = client
        self.job_id = job_id
        self.tier = tier_config(settings, tier_name)
        self.llm = GroundedLLM(client, self.tier, job_id=job_id, timeout_s=settings.grounded_llm_timeout_s)
        self.warnings: list[str] = []

    async def embedder(self, texts: list[str], model: str) -> list[list[float]]:
        return await self.client.embed(texts, model)

    async def cancelled(self) -> bool:
        if self.job_id in _cancelled:
            return True
        async with SessionLocal() as session:
            flag = await session.scalar(select(AnalysisJob.cancel_requested).where(AnalysisJob.id == self.job_id))
        # A missing row means the space (and its jobs) was deleted.
        return flag is None or bool(flag)

    async def checkpoint(self, state: str, message: str | None = None, progress: float | None = None):
        if await self.cancelled():
            raise JobCancelled()
        await update_job(self.job_id, state=state, message=message, progress=progress)

    async def warn(self, text: str):
        if text not in self.warnings:
            self.warnings.append(text)
            await update_job(self.job_id, warning=text)

    async def run(self) -> None:
        job = await owned_job(self.job_id)
        params = job.params or {}
        paper_ids: list[str] = params["paper_ids"]
        refresh = bool(params.get("refresh"))
        await self.checkpoint("parsing", f"Preparing source evidence for {len(paper_ids)} papers")
        builder = EvidenceBuilder(self.settings, self.llm, self.embedder)
        builds = {}
        for index, paper_id in enumerate(paper_ids):
            async def note(message, paper_id=paper_id):
                await update_job(self.job_id, message=message)
            build, rebuilt = await builder.ensure(paper_id, force=refresh, progress=note)
            builds[paper_id] = build
            await update_job(self.job_id, message=f"{'Rebuilt' if rebuilt else 'Reused'} evidence build v{build.version} for paper {index + 1}",
                             progress=0.03 + 0.17 * (index + 1) / len(paper_ids))
            for flag in build.quality_flags or []:
                if flag.startswith(("ocr_uncertain", "abstract_only", "no_pdf_available", "no_source_text", "pdf_parse_failed",
                                    "missing_pages", "page_limit_truncated", "vision_page_budget_exhausted", "no_headings_detected")):
                    await self.warn(f"Paper {index + 1}: extraction warning “{flag}”.")
        await self.checkpoint("indexing", "Evidence index uses " + self.tier.embed_model)
        papers = await self._load_papers(paper_ids, builds)
        retriever = Retriever(self.embedder, self.tier.embed_model, self.settings.grounded_retrieval_k)
        validator = FactValidator(self.llm)
        extractor = FactExtractor(self.llm, retriever, validator, check_cancel=self.cancelled)
        await self.checkpoint("extracting_facts", "Extracting typed facts per paper (completed types are reused)")
        for index, paper in enumerate(papers):
            async def note(message, index=index):
                await update_job(self.job_id, message=message, progress=0.25 + 0.3 * (index + 0.5) / len(papers))
            artifacts = list(paper.artifacts_by_id.values())
            paper.extraction_state = await extractor.ensure_facts(paper.build, artifacts, paper.title, progress=note)
        await self.checkpoint("validating_facts", "Validating provenance, type, ownership and dimension")
        for index, paper in enumerate(papers):
            async def note(message, index=index):
                await update_job(self.job_id, message=message, progress=0.55 + 0.15 * (index + 0.5) / len(papers))
            unvalidated = await extractor.validate_pending(paper.build, list(paper.artifacts_by_id.values()), paper.title, progress=note)
            for name in unvalidated:
                # Shown as "extraction failed" in the table: a model failure is not absence of evidence.
                paper.extraction_state[name] = {**(paper.extraction_state.get(name) or {}), "status": "failed", "validation": "failed"}
            paper.facts = await load_facts(paper.build.id)
            failed = [t for t, s in paper.extraction_state.items() if s.get("status") == "failed"]
            if failed:
                await self.warn(f"{paper.short}: extraction or validation failed for {', '.join(failed)}; those cells show “extraction failed”, "
                                "not absence. Re-run to retry them.")
            partial = [t for t, s in paper.extraction_state.items() if s.get("status") == "partial"]
            if partial:
                await self.warn(f"{paper.short}: model output for {', '.join(partial)} was cut off at the token limit; only the complete "
                                "items were kept, so some facts may be missing.")
        fingerprint = facts_fingerprint(papers)
        cached = None if refresh else await self._cached_report(job.space_id, paper_ids, builds, fingerprint)
        if cached:
            await update_job(self.job_id, state="completed_with_warnings" if self.warnings else "completed", report_id=cached, finished=True,
                             message="Reused an existing grounded report built from the same evidence, facts and models")
            return
        await self.checkpoint("comparing", "Deterministic comparison of validated facts")
        comparator = DeterministicComparator(papers)
        matrix = comparator.matrix()
        entity_findings = comparator.compare_entities()
        semantic = SemanticComparator(self.llm)
        semantic_findings = await semantic.compare(papers, comparator.comparable_pairs(entity_findings), check_cancel=self.cancelled)
        await self.checkpoint("computing_numerics", "Computing numeric, split and statistical comparisons in Python")
        numeric_findings = comparator.compare_numerics()
        await self.checkpoint("verifying_findings", "Verifying interpretive findings against source spans")
        verifier = FindingVerifier(self.llm, papers)
        for finding in semantic_findings:
            if finding.display_status != "coverage":
                if await self.cancelled():
                    raise JobCancelled()
                await verifier.verify(finding)
        findings = [apply_display_policy(f, self.tier.final_evidence_authority) for f in [*entity_findings, *numeric_findings, *semantic_findings]]
        await self.checkpoint("identifying_candidate_gaps", "Identifying candidate gaps from validated facts")
        gap_analyzer = GapAnalyzer(self.llm)
        gaps = await gap_analyzer.candidates(papers, [f for f in findings if f.display_status == "shown"])
        for gap in gaps:
            if await self.cancelled():
                raise JobCancelled()
            apply_display_policy(await verifier.verify(gap), self.tier.final_evidence_authority)
        if gap_analyzer.empty_reason and not gaps:
            await self.warn(gap_analyzer.empty_reason)
        findings.extend(gaps)
        novelty = {"ran": False, "label": "novelty_not_assessed",
                   "reason": "Novelty needs a broader literature search; enable it and add an authorized corpus to run it."}
        shown_gaps = [g for g in gaps if g.display_status in {"shown", "shown_with_caveat"}]
        if params.get("check_novelty"):
            await self.checkpoint("checking_novelty_optional", "Searching the authorized literature corpus")
            corpus = CorpusService(self.embedder, self.tier.embed_model)
            assessor = NoveltyAssessor(self.llm, corpus, self.settings.grounded_novelty_min_corpus, self.settings.grounded_novelty_top_k)
            dois = {str(p.build.doc_metadata.get("doi") or "").casefold() for p in papers} - {""}
            novelty = await assessor.assess(params.get("corpus_id") or "default", shown_gaps, paper_ids, dois)
            if novelty.get("status") == "insufficient_literature_coverage":
                await self.warn("Novelty: the literature corpus is too small; gaps are labelled “insufficient literature coverage”.")
        else:
            for gap in shown_gaps:
                gap.novelty = {"label": "novelty_not_assessed"}
        await self.checkpoint("rendering_report", "Rendering the page-linked report")
        stats = dict(self.llm.stats)
        if stats.get("parser_defect"):
            await self.warn(f"{stats['parser_defect']} model responses had valid JSON in an unrecognised shape (parser defect, logged).")
        model_metadata = await self._model_metadata(stats)
        report = build_report(papers, matrix, findings, gaps_empty_reason=gap_analyzer.empty_reason, novelty=novelty,
                              warnings=list(self.warnings), model_metadata=model_metadata, tier=self.tier.as_dict(),
                              audit={"semantic": semantic.audit, "gaps": gap_analyzer.audit})
        report["facts_fingerprint"] = fingerprint
        report_id = await self._persist(job.space_id, paper_ids, report, findings)
        state = "completed_with_warnings" if self.warnings else "completed"
        await update_job(self.job_id, state=state, report_id=report_id, finished=True, message="Report ready")

    async def _load_papers(self, paper_ids: list[str], builds: dict) -> list[PaperEvidence]:
        async with SessionLocal() as session:
            titles = dict((await session.execute(select(Paper.id, Paper.title).where(Paper.id.in_(paper_ids)))).all())
        papers = []
        for index, paper_id in enumerate(paper_ids):
            build = builds[paper_id]
            artifacts = await load_artifacts(build.id)
            papers.append(PaperEvidence(paper_id=paper_id, label=f"P{index + 1}", title=titles.get(paper_id) or paper_id, build=build,
                                        artifacts_by_id={a.id: a for a in artifacts}, facts=await load_facts(build.id),
                                        extraction_state=dict((build.doc_metadata or {}).get("extraction", {}))))
        return papers

    def _fingerprint(self) -> dict:
        return {"tier": self.tier.tier, "text_model": self.tier.text_model, "vision_model": self.tier.vision_model,
                "embed_model": self.tier.embed_model, "prompts": PROMPT_VERSIONS, "parser_version": PARSER_VERSION}

    async def _cached_report(self, space_id: str, paper_ids: list[str], builds: dict, fingerprint: str) -> str | None:
        async with SessionLocal() as session:
            rows = (await session.execute(select(ComparisonReport).where(
                ComparisonReport.space_id == space_id, ComparisonReport.report_kind == "grounded")
                .order_by(ComparisonReport.generated_at.desc()))).scalars().all()
        wanted_builds = {pid: b.id for pid, b in builds.items()}
        job = await owned_job(self.job_id)
        for row in rows:
            data = row.report_json or {}
            if (list(row.paper_ids or []) == paper_ids and data.get("builds") == wanted_builds
                    and data.get("facts_fingerprint") == fingerprint
                    and (data.get("model_metadata") or {}).get("fingerprint") == self._fingerprint()
                    and bool((data.get("novelty") or {}).get("ran")) == bool((job.params or {}).get("check_novelty"))):
                return row.id
        return None

    async def _model_metadata(self, stats: dict) -> dict:
        digests = await self.llm.digests()
        version = None
        getter = getattr(self.client, "version", None)
        if getter:
            version = await getter()
        models = {self.tier.text_model, self.tier.vision_model, self.tier.embed_model}
        return {"pipeline": "grounded", "fingerprint": self._fingerprint(), "ollama_version": version, "seed": self.tier.seed,
                "model_digests": {m: digests.get(m, "") for m in models}, "parse_stats": stats, "job_id": self.job_id,
                "missing_models": sorted(m for m in models if digests and m not in digests)}

    async def _persist(self, space_id: str, paper_ids: list[str], report: dict, findings) -> str:
        report_id = str(uuid4())

        async def op():
            async with SessionLocal() as session:
                session.add(ComparisonReport(id=report_id, space_id=space_id, paper_ids=paper_ids, matrix={}, commonalities=[],
                                             contradictions=[], gaps=[], confidence=0.0, report_kind="grounded",
                                             report_json=report, job_id=self.job_id, generated_at=_now()))
                await session.flush()
                for ordinal, f in enumerate(findings):
                    session.add(ComparisonFinding(
                        id=f"{report_id}-{f.finding_id}", report_id=report_id, ordinal=ordinal, kind=f.kind, dimension=f.dimension,
                        statement=f.statement, paper_ids=f.paper_ids, fact_ids=f.fact_ids, source_ids=f.source_ids,
                        computed={**f.computed, **({"novelty": f.novelty} if f.novelty else {})}, evidence_status=f.evidence_status,
                        verification_status=f.verification_status, display_status=f.display_status, reason=f.reason))
                await session.commit()
        await retry_sqlite_locked(op)
        return report_id

class EvidenceRebuildPipeline(GroundedComparePipeline):
    """Rebuild one paper's source artifacts, then re-extract and re-validate its evidence ledger.

    Grounded reports that used the previous build stay immutable and are flagged stale.
    """

    async def run(self) -> None:
        job = await owned_job(self.job_id)
        paper_id = (job.params or {})["paper_ids"][0]
        await self.checkpoint("parsing", "Rebuilding source artifacts")
        builder = EvidenceBuilder(self.settings, self.llm, self.embedder)

        async def note(message):
            await update_job(self.job_id, message=message)
        build, _ = await builder.ensure(paper_id, force=True, progress=note)
        await self.checkpoint("indexing", f"Evidence build v{build.version} indexed with {self.tier.embed_model}")
        papers = await self._load_papers([paper_id], {paper_id: build})
        paper = papers[0]
        retriever = Retriever(self.embedder, self.tier.embed_model, self.settings.grounded_retrieval_k)
        extractor = FactExtractor(self.llm, retriever, FactValidator(self.llm), check_cancel=self.cancelled)
        await self.checkpoint("extracting_facts", "Extracting typed facts")
        artifacts = list(paper.artifacts_by_id.values())
        state = await extractor.ensure_facts(build, artifacts, paper.title, progress=note)
        await self.checkpoint("validating_facts", "Validating facts")
        await extractor.validate_pending(build, artifacts, paper.title, progress=note)
        failed = [t for t, s in state.items() if s.get("status") == "failed"]
        if failed:
            await self.warn(f"Extraction failed for {', '.join(failed)}.")
        await update_job(self.job_id, state="completed_with_warnings" if self.warnings else "completed", finished=True,
                         message="Evidence rebuilt; earlier reports using the old build are marked stale")
