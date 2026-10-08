from datetime import datetime

from pydantic import BaseModel, Field

# User-facing evidence statuses (plan section 13).
DIRECTLY_EVIDENCED = "DIRECTLY_EVIDENCED"
NUMERICALLY_VERIFIED = "NUMERICALLY_VERIFIED"
EVIDENCE_BACKED_INTERPRETATION = "EVIDENCE_BACKED_INTERPRETATION"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
UNSUPPORTED = "UNSUPPORTED"
SHOWN_STATUSES = {DIRECTLY_EVIDENCED, NUMERICALLY_VERIFIED, EVIDENCE_BACKED_INTERPRETATION, PARTIALLY_SUPPORTED}

# Finding kinds.
COMMONALITY = "commonality"
DIFFERENCE = "difference"
DIRECT_CONTRADICTION = "direct_contradiction_candidate"
APPARENT_CONTRADICTION = "apparent_contradiction"
NOT_COMPARABLE = "not_directly_comparable"
NUMERIC_COMPARISON = "numeric_comparison"
STATISTICAL_CHECK = "statistical_check"
INSUFFICIENT = "insufficient_evidence"
CANDIDATE_GAP = "candidate_gap"

NOVELTY_LABELS = ("novelty_not_assessed", "possibly_novel_in_available_corpus", "partially_addressed_in_retrieved_work",
                  "already_addressed_in_retrieved_work", "insufficient_literature_coverage")

JOB_PHASES = ("queued", "parsing", "indexing", "extracting_facts", "validating_facts", "comparing", "computing_numerics",
              "verifying_findings", "identifying_candidate_gaps", "checking_novelty_optional", "rendering_report")
TERMINAL_STATES = ("completed", "completed_with_warnings", "failed", "cancelled")


class Finding(BaseModel):
    finding_id: str
    kind: str
    dimension: str
    statement: str
    paper_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    computed: dict = Field(default_factory=dict)
    evidence_status: str = INSUFFICIENT_EVIDENCE
    verification_status: str = "pending"
    display_status: str = "candidate"
    reason: str | None = None
    basis: str = "direct_evidence"  # direct_evidence | code_calculation | interpretation
    category: str | None = None
    coverage_note: str | None = None
    novelty: dict | None = None


class CompareJobRequest(BaseModel):
    paper_ids: list[str]
    refresh: bool = False
    check_novelty: bool = False
    tier: str | None = Field(default=None, pattern="^(weak|student|deep)$")
    corpus_id: str = "default"


class JobDTO(BaseModel):
    id: str
    space_id: str
    state: str
    progress: float
    params: dict = Field(default_factory=dict)
    phase_log: list = Field(default_factory=list)
    warnings: list = Field(default_factory=list)
    error: str | None = None
    report_id: str | None = None
    cancel_requested: bool = False
    pending_sections: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None


class CorpusAddRequest(BaseModel):
    corpus_id: str = "default"
    paper_ids: list[str] = Field(default_factory=list)
    permission: str = Field(default="user_library", pattern="^(user_upload|user_library|university_licensed|open_access|metadata_only)$")
    permission_note: str | None = None
    field: str | None = None


class CorpusMetadataItem(BaseModel):
    title: str
    abstract: str | None = None
    year: int | None = None
    doi: str | None = None
    field: str | None = None
    permission: str = Field(default="metadata_only", pattern="^(user_upload|user_library|university_licensed|open_access|metadata_only)$")
    permission_note: str | None = None


class CorpusMetadataRequest(BaseModel):
    corpus_id: str = "default"
    items: list[CorpusMetadataItem]
