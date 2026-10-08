import type { ChatResponse, ChatSession, ChatSessionStatus, ChatSessionUpdate, CompareJob, ComparisonReport, ComparisonSummary, ContentHit, CorpusResponse, DomainTag, EvidenceLedger, GroundedTier, HealthStatus, IngestJob, JsonValue, ListResponse, Memory, ModelInfo, Note, NoteCreate, PaperContent, PaperStatus, RawPaperRecord, SearchResponse, SpaceDetail, SpaceSummary, Turn, VerificationTrail } from "@/lib/types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8321").replace(/\/$/, "");
export type AuthUser = { id: string; email: string; is_admin?: boolean; role?: string };
export type OpenAlexConsent = { state: "unset" | "granted" | "declined"; contact_email: string | null; updated_at: string | null };
export type OpenAlexConsentChoice =
  | { choice: "account"; consent: true }
  | { choice: "custom"; contact_email: string; consent: true }
  | { choice: "decline"; consent: false };
export type AuthStatus = { setup_required: boolean; authenticated: boolean; user: AuthUser | null; csrf_token: string | null; legacy_warning?: { foreign_key_violations: number; comparison_orphans: number; message: string } | null; openalex_consent?: OpenAlexConsent | null };
export type LinkedInStatus = { available: boolean; connected: boolean; expires_at?: string | null; reason?: string };
export type LinkedInSource = { type: "note"; id: string } | { type: "finding"; id: string; kind: "commonality" | "contradiction" | "gap" | "difference" | "numerical"; index: number };

let csrfToken: string | null = null;
export function setCsrfToken(token: string | null) { csrfToken = token; }

export class ApiError extends Error {
  status: number;
  details: unknown;
  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export function uploadPaper(spaceId: string, file: File, title: string, onProgress: (percent: number) => void): Promise<IngestJob> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/v1/spaces/${encodeURIComponent(spaceId)}/papers/upload`);
    xhr.withCredentials = true;
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => reject(new ApiError("Backend unreachable. Confirm FastAPI is running on port 8321.", 0));
    xhr.onload = () => {
      let data: { detail?: string; status?: string; paper_id?: string };
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        reject(new ApiError("Upload returned an invalid response.", xhr.status));
        return;
      }
      if (!data || typeof data !== "object") {
        reject(new ApiError("Upload returned an invalid response.", xhr.status));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        if (xhr.status === 401) {
          setCsrfToken(null);
          window.dispatchEvent(new Event("research-auth-expired"));
        }
        reject(new ApiError(typeof data.detail === "string" ? data.detail : "PDF upload failed.", xhr.status, data));
        return;
      }
      resolve(data as IngestJob);
    };
    const body = new FormData();
    body.append("file", file);
    if (title.trim()) body.append("title", title.trim());
    xhr.send(body);
  });
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if ((init.method ?? "GET").toUpperCase() !== "GET" && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include", cache: "no-store" });
  } catch (error) {
    throw new ApiError("Backend unreachable. Confirm FastAPI is running on port 8321.", 0, error);
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!response.ok) {
    if (response.status === 401 && !["/v1/auth/status", "/v1/auth/login", "/v1/auth/bootstrap"].includes(path) && typeof window !== "undefined") {
      setCsrfToken(null);
      window.dispatchEvent(new Event("research-auth-expired"));
    }
    const message = typeof data === "object" && data && "detail" in data ? JSON.stringify((data as { detail: unknown }).detail) : response.statusText;
    throw new ApiError(message, response.status, data);
  }
  return data as T;
}

export function asList<T>(response: ListResponse<T>): T[] {
  return Array.isArray(response) ? response : response.value ?? [];
}

const enc = encodeURIComponent;
export const api = {
  authStatus: async () => {
    const status = await request<AuthStatus>("/v1/auth/status");
    setCsrfToken(status.csrf_token);
    return status;
  },
  bootstrap: (token: string, email: string, password: string) => request<unknown>("/v1/auth/bootstrap", { method: "POST", body: JSON.stringify({ token, email, password }) }),
  login: (email: string, password: string) => request<unknown>("/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<unknown>("/v1/auth/logout", { method: "POST" }),
  logoutAll: () => request<unknown>("/v1/auth/logout-all", { method: "POST" }),
  listUsers: () => request<AuthUser[]>("/v1/auth/users"),
  createUser: (email: string, password: string) => request<AuthUser>("/v1/auth/users", { method: "POST", body: JSON.stringify({ email, password }) }),
  resetUserPassword: (id: string, password: string) => request<unknown>(`/v1/auth/users/${enc(id)}/reset-password`, { method: "POST", body: JSON.stringify({ password }) }),
  openAlexConsent: () => request<OpenAlexConsent>("/v1/auth/openalex-consent"),
  updateOpenAlexConsent: (choice: OpenAlexConsentChoice) => request<OpenAlexConsent>("/v1/auth/openalex-consent", { method: "PUT", body: JSON.stringify(choice) }),
  linkedinStatus: () => request<LinkedInStatus>("/v1/linkedin/status"),
  linkedinConnect: () => request<{ authorization_url: string }>("/v1/linkedin/connect", { method: "POST" }),
  linkedinDisconnect: () => request<{ connected: boolean; external_revocation: string }>("/v1/linkedin/disconnect", { method: "POST" }),
  linkedinPublish: (source: LinkedInSource, text: string, visibility: "PUBLIC" | "CONNECTIONS", request_id: string) =>
    request<{ published: boolean; post_id: string; visibility: string }>("/v1/linkedin/publish", {
      method: "POST",
      body: JSON.stringify({ source_type: source.type, source_id: source.id, finding_kind: source.type === "finding" ? source.kind : null, finding_index: source.type === "finding" ? source.index : null, text, visibility, confirmed: true, request_id })
    }),
  health: () => request<HealthStatus>("/v1/admin/health"),
  models: () => request<ModelInfo>("/v1/admin/models"),
  spaces: () => request<ListResponse<SpaceSummary>>("/v1/spaces"),
  createSpace: (name: string) => request<SpaceSummary>("/v1/spaces", { method: "POST", body: JSON.stringify({ name }) }),
  space: (id: string) => request<SpaceDetail>(`/v1/spaces/${enc(id)}`),
  renameSpace: (id: string, name: string) => request<SpaceDetail>(`/v1/spaces/${enc(id)}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  deleteSpace: (id: string) => request<JsonValue>(`/v1/spaces/${enc(id)}`, { method: "DELETE" }),
  archiveSpace: (id: string) => request<SpaceSummary>(`/v1/spaces/${enc(id)}/archive`, { method: "POST" }),
  unarchiveSpace: (id: string) => request<SpaceSummary>(`/v1/spaces/${enc(id)}/unarchive`, { method: "POST" }),
  duplicateSpace: (id: string, copy_notes: boolean, name?: string) => request<SpaceSummary>(`/v1/spaces/${enc(id)}/duplicate`, { method: "POST", body: JSON.stringify({ copy_notes, name }) }),
  turns: (id: string, limit = 100) => request<ListResponse<Turn>>(`/v1/spaces/${enc(id)}/turns?limit=${limit}`),
  chat: (id: string, question: string, options: { sessionId?: string | null; mentionedSessionIds?: string[] } = {}) =>
    request<ChatResponse>(`/v1/spaces/${enc(id)}/chat`, { method: "POST", body: JSON.stringify({ question, session_id: options.sessionId ?? null, mentioned_session_ids: options.mentionedSessionIds ?? [] }) }),
  chatSessions: (id: string, status: ChatSessionStatus = "active", q?: string) => request<ChatSession[]>(`/v1/spaces/${enc(id)}/chat-sessions?status=${status}${q?.trim() ? `&q=${enc(q.trim())}` : ""}`),
  createChatSession: (id: string, title?: string) => request<ChatSession>(`/v1/spaces/${enc(id)}/chat-sessions`, { method: "POST", body: JSON.stringify({ title: title ?? null }) }),
  chatSession: (sessionId: string) => request<ChatSession>(`/v1/chat-sessions/${enc(sessionId)}`),
  updateChatSession: (sessionId: string, update: ChatSessionUpdate) => request<ChatSession>(`/v1/chat-sessions/${enc(sessionId)}`, { method: "PATCH", body: JSON.stringify(update) }),
  deleteChatSession: (sessionId: string) => request<JsonValue>(`/v1/chat-sessions/${enc(sessionId)}`, { method: "DELETE" }),
  chatSessionTurns: (sessionId: string, limit = 200) => request<Turn[]>(`/v1/chat-sessions/${enc(sessionId)}/turns?limit=${limit}`),
  compressChatSession: (sessionId: string) => request<ChatSession>(`/v1/chat-sessions/${enc(sessionId)}/compress`, { method: "POST" }),
  verification: (turnId: string) => request<VerificationTrail>(`/v1/turns/${enc(turnId)}/verification`),
  domainTags: () => request<DomainTag[]>("/v1/search/tags"),
  search: (id: string, query: string, include_web = false) => request<SearchResponse>(`/v1/spaces/${enc(id)}/search`, { method: "POST", body: JSON.stringify({ query, include_web }) }),
  pinPaper: (id: string, paper: RawPaperRecord, background = false) => request<IngestJob>(`/v1/spaces/${enc(id)}/papers${background ? "?background=true" : ""}`, { method: "POST", body: JSON.stringify({ ...paper, raw_payload: paper.raw_payload && typeof paper.raw_payload === "object" ? paper.raw_payload : {} }) }),
  unpinPapers: (id: string, paper_ids: string[]) => request<{ space_id: string; unpinned: string[] }>(`/v1/spaces/${enc(id)}/papers/unpin`, { method: "POST", body: JSON.stringify({ paper_ids }) }),
  uploadPaper,
  uploadedFileUrl: (paperId: string) => `${API_BASE}/v1/papers/${enc(paperId)}/file`,
  captureWeb: (id: string, url: string, title?: string | null, content?: string | null) => request<IngestJob>(`/v1/spaces/${enc(id)}/web-captures`, { method: "POST", body: JSON.stringify({ url, title, content }) }),
  paperStatus: (paperId: string) => request<PaperStatus>(`/v1/papers/${enc(paperId)}/status`),
  unpinPaper: (id: string, paperId: string) => request<JsonValue>(`/v1/spaces/${enc(id)}/papers/${enc(paperId)}`, { method: "DELETE" }),
  comparisons: (id: string) => request<ListResponse<ComparisonSummary>>(`/v1/spaces/${enc(id)}/comparisons`),
  comparison: (reportId: string) => request<ComparisonReport>(`/v1/comparisons/${enc(reportId)}`),
  startCompareJob: (id: string, body: { paper_ids: string[]; refresh: boolean; check_novelty: boolean; tier?: string | null; corpus_id?: string }) =>
    request<CompareJob>(`/v1/spaces/${enc(id)}/compare-jobs`, { method: "POST", body: JSON.stringify(body) }),
  compareJobs: (id: string) => request<CompareJob[]>(`/v1/spaces/${enc(id)}/compare-jobs`),
  compareJob: (jobId: string) => request<CompareJob>(`/v1/compare-jobs/${enc(jobId)}`),
  cancelCompareJob: (jobId: string) => request<CompareJob>(`/v1/compare-jobs/${enc(jobId)}/cancel`, { method: "POST" }),
  evidenceLedger: (paperId: string) => request<EvidenceLedger>(`/v1/papers/${enc(paperId)}/evidence`),
  rebuildEvidence: (paperId: string) => request<CompareJob>(`/v1/papers/${enc(paperId)}/evidence/rebuild`, { method: "POST" }),
  artifactImageUrl: (artifactId: string) => `${API_BASE}/v1/evidence/artifacts/${enc(artifactId)}/image`,
  groundedTiers: () => request<{ active: string; tiers: GroundedTier[] }>("/v1/grounded/tiers"),
  corpus: (corpusId = "default") => request<CorpusResponse>(`/v1/corpus?corpus_id=${enc(corpusId)}`),
  addCorpusPapers: (paper_ids: string[], permission: string, permission_note?: string, corpus_id = "default") =>
    request<{ added: number; skipped_duplicates: number }>("/v1/corpus/papers", { method: "POST", body: JSON.stringify({ corpus_id, paper_ids, permission, permission_note: permission_note || null }) }),
  removeCorpusItem: (itemId: string) => request<JsonValue>(`/v1/corpus/items/${enc(itemId)}`, { method: "DELETE" }),
  notes: (id: string, paperId?: string) => request<ListResponse<Note>>(`/v1/spaces/${enc(id)}/notes${paperId ? `?paper_id=${enc(paperId)}` : ""}`),
  createNote: (id: string, content: string, paper_id?: string | null, anchor?: Omit<NoteCreate, "content" | "paper_id">) => request<Note>(`/v1/spaces/${enc(id)}/notes`, { method: "POST", body: JSON.stringify({ content, paper_id, ...anchor }) }),
  updateNote: (noteId: string, content: string) => request<Note>(`/v1/notes/${enc(noteId)}`, { method: "PUT", body: JSON.stringify({ content }) }),
  deleteNote: (noteId: string) => request<JsonValue>(`/v1/notes/${enc(noteId)}`, { method: "DELETE" }),
  autoNote: (id: string, paperId: string, refresh: boolean) => request<Note>(`/v1/spaces/${enc(id)}/papers/${enc(paperId)}/notes/auto?refresh=${refresh}`, { method: "POST" }),
  paperContent: (paperId: string, spaceId?: string, limit?: number) => {
    const params = new URLSearchParams();
    if (spaceId) params.set("space_id", spaceId);
    if (limit) params.set("limit", String(limit));
    const query = params.toString();
    return request<PaperContent>(`/v1/papers/${enc(paperId)}/content${query ? `?${query}` : ""}`);
  },
  annotations: (id: string, paperId: string) => request<ListResponse<Note>>(`/v1/spaces/${enc(id)}/papers/${enc(paperId)}/annotations`),
  memory: (id: string) => request<Memory>(`/v1/spaces/${enc(id)}/memory`),
  searchContent: (id: string, q: string) => request<ListResponse<ContentHit>>(`/v1/spaces/${enc(id)}/search-content?q=${enc(q)}`)
};
