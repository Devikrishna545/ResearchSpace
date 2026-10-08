"""Evidence-grounded comparison storage: source artifacts, typed facts, findings and jobs."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class PaperEvidenceBuild(Base):
    """One versioned parse of a paper. Facts and artifacts belong to exactly one build."""

    __tablename__ = "paper_evidence_builds"
    __table_args__ = (UniqueConstraint("paper_id", "version", name="uq_evidence_build_paper_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="building")
    parser_version: Mapped[str] = mapped_column(String, nullable=False)
    embed_model: Mapped[str | None] = mapped_column(String, nullable=True)
    text_source: Mapped[str] = mapped_column(String, nullable=False)
    pdf_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scanned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    doc_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DocumentArtifact(Base):
    """A page-aware source unit (text chunk, table, figure or rendered page) created before any LLM call."""

    __tablename__ = "document_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    build_id: Mapped[str] = mapped_column(String, ForeignKey("paper_evidence_builds.id"), nullable=False, index=True)
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cells: Mapped[list | None] = mapped_column(JSON, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_status: Mapped[str] = mapped_column(String, nullable=False, default="parsed")
    quality_flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parser_version: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    embedding_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String, nullable=True)


class EvidenceFact(Base):
    """An atomic, typed, source-bound fact about one paper."""

    __tablename__ = "evidence_facts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    build_id: Mapped[str] = mapped_column(String, ForeignKey("paper_evidence_builds.id"), nullable=False, index=True)
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"), nullable=False, index=True)
    fact_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(String, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_status: Mapped[str] = mapped_column(String, nullable=False, default="candidate")
    provenance_validation: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    type_validation: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    ownership_validation: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    dimension_validation: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    validation_notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class LLMCallLog(Base):
    """Raw model output retained after normalization so parser and model failures stay distinguishable."""

    __tablename__ = "llm_call_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    paper_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    model_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parse_status: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String, ForeignKey("research_spaces.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="compare")
    state: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    phase_log: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_id: Mapped[str | None] = mapped_column(String, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComparisonFinding(Base):
    __tablename__ = "comparison_findings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    report_id: Mapped[str] = mapped_column(String, ForeignKey("comparison_reports.id"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    paper_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fact_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    computed: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_status: Mapped[str] = mapped_column(String, nullable=False)
    verification_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    display_status: Mapped[str] = mapped_column(String, nullable=False, default="candidate")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LiteratureCorpusItem(Base):
    """An authorized literature item for novelty retrieval, with permission provenance."""

    __tablename__ = "literature_corpus_items"
    __table_args__ = (UniqueConstraint("owner_id", "corpus_id", "dedupe_key", name="uq_corpus_item"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    corpus_id: Mapped[str] = mapped_column(String, nullable=False, default="default")
    dedupe_key: Mapped[str] = mapped_column(String, nullable=False)
    paper_id: Mapped[str | None] = mapped_column(String, ForeignKey("papers.id"), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(String, nullable=True)
    field: Mapped[str | None] = mapped_column(String, nullable=True)
    item_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    permission: Mapped[str] = mapped_column(String, nullable=False)
    permission_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
