import type { CompareJob, GroundedFinding, GroundedReport, SourceArtifact } from "@/lib/types";

export const TERMINAL_JOB_STATES = ["completed", "completed_with_warnings", "failed", "cancelled"] as const;

export const JOB_PHASES: Array<{ id: string; label: string }> = [
  { id: "queued", label: "Queued" },
  { id: "parsing", label: "Parsing PDFs" },
  { id: "indexing", label: "Indexing evidence" },
  { id: "extracting_facts", label: "Extracting typed facts" },
  { id: "validating_facts", label: "Validating facts" },
  { id: "comparing", label: "Comparing" },
  { id: "computing_numerics", label: "Computing numerics" },
  { id: "verifying_findings", label: "Verifying findings" },
  { id: "identifying_candidate_gaps", label: "Candidate gaps" },
  { id: "checking_novelty_optional", label: "Novelty (optional)" },
  { id: "rendering_report", label: "Rendering report" },
];

export const STATUS_META: Record<string, { label: string; tone: "emerald" | "indigo" | "sky" | "amber" | "muted"; basis: string }> = {
  DIRECTLY_EVIDENCED: { label: "Directly evidenced", tone: "emerald", basis: "Stated in the cited source spans of every named paper." },
  NUMERICALLY_VERIFIED: { label: "Computed in code", tone: "indigo", basis: "Calculated or checked in Python from source values." },
  EVIDENCE_BACKED_INTERPRETATION: { label: "Evidence-backed interpretation", tone: "sky", basis: "An interpretation the verifier found supported by the cited spans." },
  PARTIALLY_SUPPORTED: { label: "Partially supported", tone: "amber", basis: "Only part of the statement is supported." },
  INSUFFICIENT_EVIDENCE: { label: "Insufficient evidence", tone: "muted", basis: "The papers do not provide enough validated evidence." },
  UNSUPPORTED: { label: "Unsupported", tone: "muted", basis: "The cited evidence does not support the statement." },
};

export const BASIS_LABELS: Record<string, string> = {
  direct_evidence: "Direct evidence",
  code_calculation: "Code-verified calculation",
  interpretation: "Interpretation",
};

export const KIND_LABELS: Record<string, string> = {
  commonality: "Commonality",
  difference: "Difference",
  direct_contradiction_candidate: "Direct contradiction (candidate)",
  apparent_contradiction: "Apparent contradiction",
  not_directly_comparable: "Not directly comparable",
  numeric_comparison: "Numeric comparison",
  statistical_check: "Statistical check",
  candidate_gap: "Candidate gap",
  insufficient_evidence: "Insufficient evidence",
};

export const NOVELTY_LABELS: Record<string, string> = {
  novelty_not_assessed: "Novelty not assessed",
  possibly_novel_in_available_corpus: "Possibly novel in the available corpus",
  partially_addressed_in_retrieved_work: "Partially addressed in retrieved work",
  already_addressed_in_retrieved_work: "Already addressed in retrieved work",
  insufficient_literature_coverage: "Insufficient literature coverage",
};

export const REPORT_SECTIONS: Array<{ key: keyof GroundedReport["sections"]; title: string; shareKind: "commonality" | "difference" | "contradiction" | "numerical" | "gap" }> = [
  { key: "commonalities", title: "Commonalities", shareKind: "commonality" },
  { key: "differences", title: "Differences and comparability conditions", shareKind: "difference" },
  { key: "contradictions", title: "Contradictions and apparent contradictions", shareKind: "contradiction" },
  { key: "numerical", title: "Numerical and dataset analysis", shareKind: "numerical" },
  { key: "candidate_gaps", title: "Candidate gaps", shareKind: "gap" },
];

export function isTerminalJob(job: Pick<CompareJob, "state"> | null | undefined): boolean {
  return Boolean(job && (TERMINAL_JOB_STATES as readonly string[]).includes(job.state));
}

export function phaseIndex(state: string): number {
  const index = JOB_PHASES.findIndex((phase) => phase.id === state);
  return index === -1 ? (isTerminalJob({ state }) ? JOB_PHASES.length : 0) : index;
}

export function statusMeta(status: string) {
  return STATUS_META[status] ?? { label: status.replace(/_/g, " ").toLowerCase(), tone: "muted" as const, basis: "" };
}

/** Source artifacts a finding cites, in citation order, skipping anything not in the appendix. */
export function findingSources(report: Pick<GroundedReport, "evidence_appendix">, finding: Pick<GroundedFinding, "source_ids">): SourceArtifact[] {
  return finding.source_ids.map((id) => report.evidence_appendix[id]).filter((source): source is SourceArtifact => Boolean(source));
}

export function paperLabel(report: Pick<GroundedReport, "papers">, paperId: string): string {
  const paper = report.papers.find((item) => item.paper_id === paperId);
  return paper ? `${paper.label} · ${paper.title}` : paperId;
}

export function sourceLocation(source: Pick<SourceArtifact, "page" | "section" | "label" | "kind">): string {
  const parts = [source.label || (source.kind === "text" ? null : source.kind), source.page ? `p. ${source.page}` : "page unknown", source.section];
  return parts.filter(Boolean).join(" · ");
}
