export const MAX_PDF_BYTES = 30 * 1024 * 1024;

export function pdfUploadError(file: Pick<File, "name" | "size">): string | null {
  if (!file.name.toLowerCase().endsWith(".pdf")) return "Choose a PDF file.";
  if (file.size > MAX_PDF_BYTES) return "PDFs must be 30 MB or smaller.";
  if (file.size === 0) return "The selected file is empty.";
  return null;
}

export type UploadState = {
  title: string;
  fileName: string;
  uploading: boolean;
  taskId: string | null;
  job: { paper_id: string; status: string; message?: string | null } | null;
  error: string | null;
  info: string | null;
};
export const initialUploadState: UploadState = { title: "", fileName: "", uploading: false, taskId: null, job: null, error: null, info: null };

export function isUploadState(value: unknown): value is UploadState {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const state = value as Record<string, unknown>;
  const optionalString = (item: unknown) => item === null || typeof item === "string";
  if (typeof state.title !== "string" || typeof state.fileName !== "string" || typeof state.uploading !== "boolean"
    || !optionalString(state.taskId) || !optionalString(state.error) || !optionalString(state.info)) return false;
  if (state.job === null) return true;
  if (!state.job || typeof state.job !== "object" || Array.isArray(state.job)) return false;
  const job = state.job as Record<string, unknown>;
  return typeof job.paper_id === "string" && typeof job.status === "string"
    && (job.message == null || typeof job.message === "string");
}

export function recoverUploadState(state: UploadState): UploadState {
  if (state.uploading) return {
    ...state, uploading: false, info: "Upload interrupted before confirmation. Check pinned papers first; if it is missing, choose the PDF again. Browsers cannot restore file selections after a reload.",
  };
  if (state.fileName && !state.job) return { ...state, info: `Choose “${state.fileName}” again to upload it. File selections cannot be restored after a reload.` };
  return state;
}
