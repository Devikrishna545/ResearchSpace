import type { CompareJob } from "@/lib/types";

export const CORPUS_PERMISSIONS = ["user_library", "user_upload", "university_licensed", "open_access", "metadata_only"] as const;

export interface CompareWorkspaceState {
  version: 1;
  selected: string[];
  selectionInitialized: boolean;
  refresh: boolean;
  checkNovelty: boolean;
  reportId: string | null;
  jobId: string | null;
  jobPending: boolean;
  pendingReportJobId: string | null;
  openPanels: string[];
  corpusPermission: string;
}

export function initialCompareState(selected: string[] = []): CompareWorkspaceState {
  return {
    version: 1, selected, selectionInitialized: selected.length > 0, refresh: false, checkNovelty: false,
    reportId: null, jobId: null, jobPending: false, pendingReportJobId: null, openPanels: [],
    corpusPermission: "user_library",
  };
}

function isId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 512;
}

function isIds(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 1000 && value.every(isId) && new Set(value).size === value.length;
}

export function isCompareWorkspaceState(value: unknown): value is CompareWorkspaceState {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const state = value as Record<string, unknown>;
  const keys = Object.keys(initialCompareState());
  return Object.keys(state).length === keys.length && keys.every((key) => key in state)
    && state.version === 1 && isIds(state.selected) && typeof state.selectionInitialized === "boolean"
    && typeof state.refresh === "boolean" && typeof state.checkNovelty === "boolean"
    && (state.reportId === null || isId(state.reportId)) && (state.jobId === null || isId(state.jobId))
    && typeof state.jobPending === "boolean" && (!state.jobPending || state.jobId !== null)
    && (state.pendingReportJobId === null || (isId(state.pendingReportJobId) && state.pendingReportJobId === state.jobId && state.jobPending))
    && isIds(state.openPanels) && typeof state.corpusPermission === "string"
    && (CORPUS_PERMISSIONS as readonly string[]).includes(state.corpusPermission);
}

export function comparisonTerminalNotice(job: Pick<CompareJob, "id" | "state" | "error" | "warnings">) {
  const id = `compare-job:${job.id}:terminal`;
  switch (job.state) {
    case "completed":
    case "completed_with_warnings":
      return { id, status: "success" as const, title: job.state === "completed" ? "Comparison completed" : "Comparison completed with warnings", message: job.warnings.join(" ") || undefined };
    case "failed":
      return { id, status: "error" as const, title: "Comparison failed", message: job.error || "Open Compare to review the job details." };
    case "cancelled":
      return { id, status: "info" as const, title: "Comparison cancelled" };
    default:
      return null;
  }
}

/** A historical report selection wins over a background job finishing later. */
export function completedReportId(state: CompareWorkspaceState, job: Pick<CompareJob, "id" | "state" | "report_id">): string | null {
  return state.pendingReportJobId === job.id && (job.state === "completed" || job.state === "completed_with_warnings")
    ? job.report_id ?? null : null;
}

export function settledCompareState(state: CompareWorkspaceState, job: Pick<CompareJob, "id" | "state" | "report_id">): CompareWorkspaceState {
  const reportId = completedReportId(state, job);
  return {
    ...state, jobId: job.id, jobPending: false, pendingReportJobId: null,
    ...(reportId ? { reportId, openPanels: [] } : {}),
  };
}
