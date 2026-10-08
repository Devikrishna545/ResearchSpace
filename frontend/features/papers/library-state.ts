import type { PaperStatus, Pin, RawPaperRecord, SearchResult, SourceHealth } from "../../lib/types";

export type LibrarySort = "relevance" | "newest" | "oldest" | "authors";
export type LibraryFilters = { sort: LibrarySort; author: string; year: string; source: string };
export type LibraryJob = {
  status: string;
  taskId: string;
  title: string;
  paper_id?: string;
  message?: string | null;
  pollError?: string;
  confirmed?: boolean;
};
export type SearchHistoryItem = { query: string; includeWeb: boolean; at: string; count: number };
export type LibraryState = {
  query: string;
  includeWeb: boolean;
  results: SearchResult[];
  webResults: SearchResult[];
  health: SourceHealth[];
  recent: SearchHistoryItem | null;
  history: SearchHistoryItem[];
  filters: LibraryFilters;
  selected: string[];
  jobs: Record<string, LibraryJob>;
  searching: boolean;
  error: string | null;
  info: string | null;
};

export const defaultFilters: LibraryFilters = { sort: "relevance", author: "", year: "", source: "" };
export const initialLibraryState: LibraryState = {
  query: "", includeWeb: false, results: [], webResults: [], health: [], recent: null,
  history: [], filters: defaultFilters, selected: [], jobs: {}, searching: false, error: null, info: null,
};
export const SEARCH_HISTORY_LIMIT = 8;
export const TERMINAL_JOB_LIMIT = 100;
const tagPattern = /(^|\s)#([A-Za-z][A-Za-z0-9_-]*)/g;

export function queryTags(query: string): string[] {
  return [...new Set(Array.from(query.matchAll(tagPattern), (match) => `#${match[2].toLowerCase()}`))];
}

export function toggleQueryTag(query: string, tag: string): string {
  const normalized = tag.toLowerCase();
  if (!/^#[a-z][a-z0-9_-]*$/.test(normalized)) return query;
  return queryTags(query).includes(normalized)
    ? query.replace(new RegExp(`(^|\\s)${normalized}(?=\\s|$|[,.;:!?])`, "ig"), " ").replace(/\s{2,}/g, " ").trim()
    : `${normalized} ${query}`.trim();
}

export function scholarUrl(query: string): string {
  return `https://scholar.google.com/scholar?q=${encodeURIComponent(query.replace(tagPattern, " ").replace(/\s{2,}/g, " ").trim() || query)}`;
}

export function paperIdentity(paper: RawPaperRecord): string {
  if (paper.doi) return `doi:${paper.doi.toLowerCase()}`;
  if (paper.arxiv_id) return `arxiv:${paper.arxiv_id.toLowerCase()}`;
  if (paper.openalex_id) return `openalex:${paper.openalex_id}`;
  if (paper.url || paper.pdf_url) return `url:${paper.url || paper.pdf_url}`;
  return `title:${paper.title.trim().toLowerCase()}`;
}

export function paperIsPinned(paper: RawPaperRecord, pins: Pin[], job?: LibraryJob): boolean {
  return pins.some((pin) => pin.id === job?.paper_id
    || Boolean(paper.doi && pin.doi?.toLowerCase() === paper.doi.toLowerCase())
    || Boolean(paper.arxiv_id && pin.arxiv_id?.toLowerCase() === paper.arxiv_id.toLowerCase())
    || pin.title.trim().toLowerCase() === paper.title.trim().toLowerCase());
}

/** Store only discovery metadata; provider payloads can contain entire response documents. */
export function compactResults(results: SearchResult[]): SearchResult[] {
  return results.map(({ paper, score, rank_explanation }) => {
    const { source, title, authors, year, venue, abstract, doi, arxiv_id, pmid, openalex_id, citation_count, oa_status, pdf_url, url } = paper;
    return { paper: { source, title, authors, year, venue, abstract, doi, arxiv_id, pmid, openalex_id, citation_count, oa_status, pdf_url, url }, score, rank_explanation };
  });
}

export function filterResults(results: SearchResult[], filters: LibraryFilters): SearchResult[] {
  const author = filters.author.trim().toLowerCase();
  const filtered = results.filter(({ paper }) =>
    (!author || paper.authors?.some((name) => name.toLowerCase().includes(author)))
    && (!filters.year || (filters.year === "unknown" ? paper.year == null : String(paper.year) === filters.year))
    && (!filters.source || paper.source === filters.source));
  // Relevance is the API's order, not a new client-side ranking formula.
  if (filters.sort === "relevance") return filtered;
  return filtered.sort((a, b) => {
    if (filters.sort === "authors") {
      const left = a.paper.authors?.join(", ").trim();
      const right = b.paper.authors?.join(", ").trim();
      if (!left || !right) return left ? -1 : right ? 1 : 0;
      return left.localeCompare(right, undefined, { sensitivity: "base" });
    }
    if (a.paper.year == null || b.paper.year == null) return a.paper.year != null ? -1 : b.paper.year != null ? 1 : 0;
    return filters.sort === "newest" ? b.paper.year - a.paper.year : a.paper.year - b.paper.year;
  });
}

export function appendSearchHistory(history: SearchHistoryItem[], recent: SearchHistoryItem): SearchHistoryItem[] {
  return [recent, ...history.filter((entry) => entry.query !== recent.query || entry.includeWeb !== recent.includeWeb)].slice(0, SEARCH_HISTORY_LIMIT);
}

export function clearRecentSearch(state: LibraryState): LibraryState {
  return { ...state, results: [], webResults: [], health: [], recent: null, history: [], selected: [], error: null, info: "Recent search cleared. Pinned papers, uploads, and the source cache are unchanged." };
}

export function isIngestionTerminal(status: string): boolean {
  return ["READY", "DEGRADED", "FAILED"].includes(status.toUpperCase());
}

export function isPollingJob(job: LibraryJob): boolean {
  return Boolean(job.paper_id && !["PINNING", "ERROR", "INTERRUPTED"].includes(job.status.toUpperCase()) && !isIngestionTerminal(job.status));
}

export function terminalNotice(status: string): "success" | "error" | "info" {
  return status.toUpperCase() === "READY" ? "success" : status.toUpperCase() === "FAILED" ? "error" : "info";
}

export async function readIngestionStatus(paperId: string, load: (id: string) => Promise<PaperStatus>): Promise<
  { paperId: string; response: PaperStatus; error?: never } | { paperId: string; error: string; response?: never }
> {
  try {
    const response = await load(paperId);
    return { paperId, response: { ...response, status: response.status.toUpperCase() } };
  } catch (error) {
    return { paperId, error: `Status unavailable; retrying. ${error instanceof Error ? error.message : "Check your connection."}` };
  }
}

export function pruneJobs(jobs: Record<string, LibraryJob>): Record<string, LibraryJob> {
  const entries = Object.entries(jobs);
  const finished = entries.filter(([, job]) => !isPollingJob(job) && job.status !== "PINNING").slice(-TERMINAL_JOB_LIMIT);
  return Object.fromEntries([...finished, ...entries.filter(([, job]) => isPollingJob(job) || job.status === "PINNING")]);
}

export function recoverLibraryState(state: LibraryState): LibraryState {
  let interrupted = state.searching;
  const jobs = Object.fromEntries(Object.entries(state.jobs).map(([key, job]) => {
    if (job.status !== "PINNING") return [key, job];
    if (job.paper_id) return [key, { ...job, status: "QUEUED" }];
    interrupted = true;
    return [key, { ...job, status: "INTERRUPTED", message: "The page reloaded before saving was confirmed. Check pinned papers before retrying." }];
  }));
  return { ...state, searching: false, jobs, info: interrupted ? "The page reloaded before a request was confirmed. Search again if needed; check pinned papers before retrying a save." : state.info };
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
const optionalString = (value: unknown) => value == null || typeof value === "string";
const optionalNumber = (value: unknown) => value == null || (typeof value === "number" && Number.isFinite(value));
export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
export function isLibraryJob(value: unknown): value is LibraryJob {
  return isRecord(value) && typeof value.status === "string" && typeof value.taskId === "string" && typeof value.title === "string"
    && optionalString(value.paper_id) && optionalString(value.message) && optionalString(value.pollError)
    && (value.confirmed == null || typeof value.confirmed === "boolean");
}
function isSearchResult(value: unknown): value is SearchResult {
  if (!isRecord(value) || !isRecord(value.paper)) return false;
  const paper = value.paper;
  return typeof paper.title === "string" && typeof paper.source === "string" && !("raw_payload" in paper)
    && (paper.authors == null || isStringArray(paper.authors)) && optionalNumber(paper.year)
    && ["venue", "abstract", "doi", "arxiv_id", "pmid", "openalex_id", "oa_status", "pdf_url", "url"].every((key) => optionalString(paper[key]))
    && optionalNumber(paper.citation_count) && optionalNumber(value.score) && optionalString(value.rank_explanation);
}
function isHistoryItem(value: unknown): value is SearchHistoryItem {
  return isRecord(value) && typeof value.query === "string" && typeof value.includeWeb === "boolean"
    && typeof value.at === "string" && Number.isFinite(Date.parse(value.at)) && typeof value.count === "number" && value.count >= 0;
}
export function isLibraryState(value: unknown): value is LibraryState {
  if (!isRecord(value) || !isRecord(value.filters) || !isRecord(value.jobs)) return false;
  return typeof value.query === "string" && typeof value.includeWeb === "boolean" && typeof value.searching === "boolean"
    && Array.isArray(value.results) && value.results.every(isSearchResult)
    && Array.isArray(value.webResults) && value.webResults.every(isSearchResult)
    && Array.isArray(value.health) && value.health.every((item) => isRecord(item) && typeof item.source === "string" && typeof item.status === "string" && optionalString(item.error))
    && (value.recent === null || isHistoryItem(value.recent))
    && Array.isArray(value.history) && value.history.length <= SEARCH_HISTORY_LIMIT && value.history.every(isHistoryItem)
    && ["relevance", "newest", "oldest", "authors"].includes(String(value.filters.sort))
    && ["author", "year", "source"].every((key) => typeof (value.filters as Record<string, unknown>)[key] === "string")
    && isStringArray(value.selected) && Object.values(value.jobs).every(isLibraryJob)
    && optionalString(value.error) && optionalString(value.info);
}
