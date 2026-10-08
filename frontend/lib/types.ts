export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface ApiList<T> { value: T[]; Count?: number }
export type ListResponse<T> = T[] | ApiList<T>;

export interface ComponentHealth { status: string; detail?: string | null; status_code?: number | null }
/** The API returns a map of component name -> health, with no top-level status field. */
export type HealthStatus = Record<string, ComponentHealth>;
export interface ModelInfo { [key: string]: unknown }

export interface Pin { id: string; title: string; doi?: string | null; arxiv_id?: string | null; year?: number | null; venue?: string | null }
export interface SpaceSummary { id: string; name: string; status?: string; pin_count?: number; pins?: Pin[]; memory_summary?: string | null; updated_at?: string | null; created_at?: string | null }
export interface SpaceDetail extends SpaceSummary { pins: Pin[]; memory_summary?: string | null }

export interface Citation { chunk_id: string; quote?: string | null; claim_text?: string | null; match_score?: number | null; paper_id?: string | null; page?: number | string | null; section?: string | null }
export interface SessionMention { id: string; title: string }
export interface Turn { id: string; role: "user" | "assistant" | string; content: string; created_at?: string; citations?: Citation[]; session_id?: string | null; mentions?: SessionMention[]; verification?: Pick<ChatResponse, "confidence" | "iterations" | "verified" | "low_confidence_warning" | "verification_url"> | null }
export interface ChatResponse { turn_id: string; answer: string; citations: Citation[]; confidence?: number | null; iterations?: number | null; verified?: boolean | null; low_confidence_warning?: string | null; verification_url?: string | null; session_id?: string | null }
export type ChatSessionStatus = "active" | "archived" | "all";
export interface ChatSession { id: string; space_id: string; title: string; pinned: boolean; archived: boolean; summary?: string | null; summary_turn_count: number; summary_updated_at?: string | null; turn_count: number; last_message?: string | null; match?: string | null; created_at?: string | null; updated_at?: string | null }
export interface ChatSessionUpdate { title?: string; pinned?: boolean; archived?: boolean }
/** What the paper reader should open: a paper, optionally focused on a note or a cited passage. */
export interface ReaderTarget { paperId: string; noteId?: string; chunkId?: string | null; quote?: string | null; page?: number | null }

export interface RawPaperRecord { source: string; title: string; authors?: string[]; year?: number | null; venue?: string | null; abstract?: string | null; doi?: string | null; arxiv_id?: string | null; pmid?: string | null; openalex_id?: string | null; citation_count?: number | null; oa_status?: string | null; pdf_url?: string | null; url?: string | null; raw_payload?: JsonValue }
export interface SearchResult { paper: RawPaperRecord; score?: number | null; rank_explanation?: string | null }
export interface SourceHealth { source: string; status: string; error?: string | null; retry_after_seconds?: number | null; cached?: boolean }
export interface SearchResponse { results: SearchResult[]; web_results?: SearchResult[]; source_health?: SourceHealth[] }
export interface DomainTag { tag: string; label: string; aliases?: string[]; description?: string }
export interface IngestJob { job_id?: string; paper_id: string; status: string; message?: string | null }
export interface PaperStatus { paper_id?: string; status: string; message?: string | null; progress?: number | null }

export interface ComparisonSummary { id: string; paper_ids: string[]; generated_at?: string | null; report_kind?: string | null }

export type EvidenceStatus = "DIRECTLY_EVIDENCED" | "NUMERICALLY_VERIFIED" | "EVIDENCE_BACKED_INTERPRETATION" | "PARTIALLY_SUPPORTED" | "INSUFFICIENT_EVIDENCE" | "UNSUPPORTED" | string;
export type FindingBasis = "direct_evidence" | "code_calculation" | "interpretation" | string;
export interface NoveltyAssessment { label: string; reason?: string; retrieved?: number; cited_items?: Array<{ item_id: string; title: string; year?: number | null }> }
export interface GroundedFinding {
  finding_id: string; kind: string; dimension: string; statement: string; paper_ids: string[]; fact_ids: string[]; source_ids: string[];
  computed?: Record<string, JsonValue>; evidence_status: EvidenceStatus; verification_status?: string; display_status: string; reason?: string | null;
  basis: FindingBasis; category?: string | null; coverage_note?: string | null; novelty?: NoveltyAssessment | null;
}
export interface EvidenceFactDTO {
  fact_id: string; paper_id: string; fact_type: string; label: string; value: string; attributes: Record<string, JsonValue>; source_ids: string[];
  quote: string; page?: number | null; section?: string | null; extraction_status: string; provenance_validation: string; type_validation: string;
  ownership_validation: string; dimension_validation: string; validation_notes: string[]; model_version?: string;
}
export interface SourceArtifact {
  source_id: string; paper_id: string; kind: string; page?: number | null; section?: string | null; label?: string | null; caption?: string | null;
  text: string; truncated?: boolean; cells?: string[][] | null; has_image?: boolean; extraction_status: string; quality_flags: string[];
}
export interface MatrixCellValue { fact_id: string; value: string; fact_type: string; page?: number | null; source_id?: string | null }
export interface MatrixCell { status: "evidenced" | "insufficient_evidence" | "extraction_failed" | string; values: MatrixCellValue[]; note?: string }
export interface DeterministicRow { dimension: string; label: string; cells: Record<string, MatrixCell> }
export interface GroundedPaper {
  paper_id: string; label: string; title: string; summary: Record<string, Array<{ fact_id: string; value: string; page?: number | null }>>;
  build: { build_id: string; version: number; text_source: string; page_count: number; scanned: boolean; quality_flags: string[]; parser_version: string; embed_model?: string | null };
  extraction: Record<string, { status: string; count?: number; parse_status?: string }>;
  fact_counts: { validated: number; rejected: number; uncertain: number };
}
export interface NoveltyReport { ran: boolean; status?: string; label?: string; reason?: string; coverage?: { size: number; year_range?: [number, number] | null; fields: Record<string, number>; permissions: Record<string, number>; search_limitations: string[]; excluded_compared_papers?: number } }
export interface GroundedReport {
  id: string; space_id: string; paper_ids: string[]; generated_at?: string | null; report_kind: "grounded"; job_id?: string | null;
  papers: GroundedPaper[]; paper_labels: Record<string, string>; paper_label_ids: Record<string, string>;
  evidence_ledger: Record<string, EvidenceFactDTO[]>; audit_record: Record<string, EvidenceFactDTO[]>;
  deterministic_table: DeterministicRow[];
  sections: { commonalities: GroundedFinding[]; differences: GroundedFinding[]; contradictions: GroundedFinding[]; numerical: GroundedFinding[]; candidate_gaps: GroundedFinding[] };
  candidate_gaps_empty_reason?: string | null; novelty: NoveltyReport; withheld: GroundedFinding[]; withheld_count: number;
  coverage: { insufficient: GroundedFinding[]; warnings: string[]; papers: Record<string, { quality_flags: string[]; text_source: string; scanned: boolean }> };
  evidence_appendix: Record<string, SourceArtifact>; model_metadata: Record<string, JsonValue>; tier: GroundedTier; release_gate: string;
  status_legend: Record<string, string>; stale_paper_ids: string[]; stale_warning?: string | null; warnings: string[];
}
export type ComparisonReport = GroundedReport;
export interface CompareJob {
  id: string; space_id: string; state: string; progress: number; params: Record<string, JsonValue>; phase_log: Array<{ phase: string; at: string; message: string }>;
  warnings: string[]; error?: string | null; report_id?: string | null; cancel_requested: boolean; pending_sections: string[];
  created_at?: string | null; updated_at?: string | null; finished_at?: string | null;
}
export interface GroundedTier { tier: string; text_model: string; vision_model: string; embed_model: string; final_evidence_authority: boolean; capability_note: string; limitation_note: string }
export interface EvidenceLedger { paper_id: string; title: string; stale_reason?: string | null; build: (GroundedPaper["build"] & { artifact_counts?: Record<string, number>; extraction?: GroundedPaper["extraction"] }) | null; facts: EvidenceFactDTO[]; audit: EvidenceFactDTO[] }
export interface CorpusItem { id: string; title: string; year?: number | null; doi?: string | null; field?: string | null; paper_id?: string | null; permission: string; permission_note?: string | null; embedded: boolean }
export interface CorpusResponse { coverage: NonNullable<NoveltyReport["coverage"]>; items: CorpusItem[] }

export interface Note { id: string; space_id?: string; paper_id?: string | null; content: string; source?: string | null; chunk_id?: string | null; anchor_quote?: string | null; anchor_start?: number | null; anchor_end?: number | null; color?: string | null; created_at?: string; updated_at?: string }
export interface NoteCreate { paper_id?: string | null; content: string; chunk_id?: string | null; anchor_quote?: string | null; anchor_start?: number | null; anchor_end?: number | null; color?: string | null }
export interface PaperContentChunk { chunk_id: string; ordinal: number; section?: string | null; page?: number | null; text: string }
export interface PaperContentMeta { id: string; title: string; authors: string[]; year?: number | null; venue?: string | null; doi?: string | null; arxiv_id?: string | null; source?: string | null; url?: string | null; pdf_url?: string | null; local_pdf_available?: boolean; ingest_status?: string | null }
export interface PaperContent { paper: PaperContentMeta; chunks: PaperContentChunk[] }
export interface Memory { space_id?: string; rolling_summary?: string | null; findings?: string[]; open_questions?: string[]; updated_at?: string | null }
export interface ContentHit { type: "turn" | "note" | string; id: string; snippet: string; created_at?: string | null; session_id?: string | null }

export interface ClaimFinding { claim_id?: string; claim_text?: string; status?: string; cited_chunk_ids?: string[]; evidence_quote?: string | null; issue?: string | null; suggested_correction?: string | null }
export interface Verdict { verdict?: string; overall_score?: number | null; claims?: ClaimFinding[]; global_feedback?: string | null }
export interface VerificationIteration { iteration: number; draft_text?: string | null; verdict?: Verdict | null; action_taken?: string | null; latency_ms?: number | null }
export interface VerificationTrail { turn_id: string; iterations: VerificationIteration[] }
