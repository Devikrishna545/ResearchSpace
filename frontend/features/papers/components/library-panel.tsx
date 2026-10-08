"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Check, CircleCheck, ExternalLink, Globe, GraduationCap, LoaderCircle, Plus, Search, X } from "lucide-react";
import { EmptyInset, ModuleLayout, PanelHeader, SelectAllToggle } from "@/components/ui/module-layout";
import { PdfUpload } from "@/features/papers/components/pdf-upload";
import { useWorkspaceState } from "@/features/spaces/use-workspace-state";
import { api, ApiError } from "@/lib/api/client";
import { notifyTask } from "@/lib/task-events";
import type { DomainTag, Pin, ReaderTarget, SearchResult } from "@/lib/types";
import { cn } from "@/lib/utils";
import { allSelected, mapWithConcurrency, toggleAll, toggleOne } from "@/lib/utils/selection";
import {
  appendSearchHistory, clearRecentSearch, compactResults, defaultFilters, filterResults, initialLibraryState,
  isIngestionTerminal, isLibraryState, isPollingJob, paperIdentity, paperIsPinned, pruneJobs,
  queryTags, recoverLibraryState, scholarUrl, terminalNotice, toggleQueryTag,
  type LibraryFilters, type LibraryJob, type LibraryState,
} from "../library-state";
import { useIngestionPolling } from "../use-ingestion-polling";

export interface LibraryPanelProps {
  spaceId: string;
  pins: Pin[];
  refreshSpace: () => Promise<void>;
  openReader: (target: ReaderTarget) => void;
}

const statusLabels: Record<string, string> = {
  PINNING: "Saving to space…", QUEUED: "Queued for indexing", FETCHING: "Fetching PDF", PARSING: "Reading PDF",
  CHUNKING: "Splitting passages", EMBEDDING: "Embedding", PROFILING: "Profiling",
  READY: "Ready to cite", DEGRADED: "Abstract only", FAILED: "Indexing failed", INTERRUPTED: "Save not confirmed",
};

export function LibraryPanel(props: LibraryPanelProps) {
  return <LibraryPanelContent key={props.spaceId} {...props} />;
}

function LibraryPanelContent({ spaceId, pins, refreshSpace, openReader }: LibraryPanelProps) {
  const [state, setState, ready] = useWorkspaceState<LibraryState>(spaceId, "library", initialLibraryState, isLibraryState);
  const [domainTags, setDomainTags] = useState<DomainTag[]>([]);
  const [bulkPinning, setBulkPinning] = useState(false);
  const recoveredSpace = useRef<string | null>(null);
  const saving = useRef(new Set<string>());
  const searching = useRef(false);
  const notified = useRef(new Set<string>());
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(false);
  const { query, includeWeb, results, webResults, health, recent, history, filters, jobs, selected } = state;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    let cancelled = false;
    api.domainTags().then((tags) => { if (!cancelled) setDomainTags(tags); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  useEffect(() => () => { if (refreshTimer.current) clearTimeout(refreshTimer.current); }, []);
  useEffect(() => {
    if (!ready || recoveredSpace.current === spaceId) return;
    recoveredSpace.current = spaceId;
    queueMicrotask(() => { if (alive.current) setState((previous) => recoverLibraryState(previous)); });
  }, [ready, setState, spaceId]);
  useEffect(() => {
    if (!ready) return;
    // A confirmed pin disappearing means it was removed in the shared sidebar.
    const ids = new Set(pins.map((pin) => pin.id));
    queueMicrotask(() => { if (alive.current) setState((previous) => {
      let changed = false;
      const entries = Object.entries(previous.jobs).filter(([, job]) => {
        const removed = job.confirmed && job.paper_id && !ids.has(job.paper_id);
        if (removed) changed = true;
        return !removed;
      }).map(([key, job]) => {
        if (!job.confirmed && job.paper_id && ids.has(job.paper_id)) {
          changed = true;
          return [key, { ...job, confirmed: true }];
        }
        return [key, job];
      });
      return changed ? { ...previous, jobs: Object.fromEntries(entries) } : previous;
    }); });
  }, [pins, ready, setState]);

  const scheduleRefresh = useCallback(() => {
    if (!alive.current) return;
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null;
      if (!alive.current) return;
      void refreshSpace().catch(() => {
        if (alive.current) setState((previous) => ({ ...previous, info: "The task finished, but pinned papers could not be refreshed. Try refreshing the page." }));
      });
    }, 250);
  }, [refreshSpace, setState]);

  function notifyJob(job: LibraryJob) {
    if (!alive.current || !isIngestionTerminal(job.status) || notified.current.has(job.taskId)) return;
    notified.current.add(job.taskId);
    notifyTask({ id: job.taskId, spaceId, module: "library", title: `${statusLabels[job.status]}: ${job.title}`, message: job.message ?? undefined, status: terminalNotice(job.status) });
  }

  useIngestionPolling(
    ready ? Object.values(jobs).filter(isPollingJob).map((job) => job.paper_id!) : [],
    (paperId, response) => {
      if (!alive.current) return;
      const updated = Object.values(jobs).filter((job) => job.paper_id === paperId).map((job) => ({ ...job, status: response.status, message: response.message ?? job.message, pollError: undefined }));
      updated.forEach(notifyJob);
      setState((previous) => ({ ...previous, jobs: pruneJobs(Object.fromEntries(Object.entries(previous.jobs).map(([key, job]) =>
        [key, job.paper_id === paperId ? { ...job, status: response.status, message: response.message ?? job.message, pollError: undefined } : job]))) }));
      if (isIngestionTerminal(response.status)) scheduleRefresh();
    },
    (paperId, message) => {
      if (alive.current) setState((previous) => ({ ...previous, jobs: Object.fromEntries(Object.entries(previous.jobs).map(([key, job]) => [key, job.paper_id === paperId ? { ...job, pollError: message } : job])) }));
    },
  );

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!alive.current || !ready || !query.trim() || searching.current) return;
    searching.current = true;
    const requestedQuery = query.trim();
    const requestedWeb = includeWeb;
    const taskId = `search:${spaceId}:${crypto.randomUUID()}`;
    setState((previous) => ({ ...previous, searching: true, error: null, info: null }));
    try {
      const response = await api.search(spaceId, requestedQuery, requestedWeb);
      if (!alive.current) return;
      const nextResults = compactResults(response.results ?? []);
      const nextWeb = compactResults(response.web_results ?? []);
      const nextRecent = { query: requestedQuery, includeWeb: requestedWeb, at: new Date().toISOString(), count: nextResults.length + (requestedWeb ? nextWeb.length : 0) };
      setState((previous) => ({
        ...previous, results: nextResults, webResults: nextWeb, health: response.source_health ?? [], recent: nextRecent,
        history: appendSearchHistory(previous.history, nextRecent), selected: [], searching: false,
      }));
      notifyTask({ id: taskId, spaceId, module: "library", title: "Search complete", message: `${nextRecent.count} results for “${requestedQuery}”.`, status: "success" });
    } catch (error) {
      if (!alive.current) return;
      const message = error instanceof ApiError ? error.message : "Unable to search. Please try again.";
      setState((previous) => ({ ...previous, error: message, searching: false }));
      notifyTask({ id: taskId, spaceId, module: "library", title: "Search failed", message, status: "error" });
    } finally {
      searching.current = false;
    }
  }

  async function pin(result: SearchResult) {
    if (!alive.current) return;
    const key = paperIdentity(result.paper);
    const existing = jobs[key];
    if (saving.current.has(key) || paperIsPinned(result.paper, pins, existing)
      || (existing && !["ERROR", "INTERRUPTED"].includes(existing.status))) return;
    const isWeb = result.paper.source === "web";
    const url = result.paper.url || result.paper.pdf_url || "";
    if (isWeb && !url) return;
    saving.current.add(key);
    const pending: LibraryJob = { status: "PINNING", taskId: `pin:${spaceId}:${crypto.randomUUID()}`, title: result.paper.title };
    setState((previous) => ({ ...previous, jobs: pruneJobs({ ...previous.jobs, [key]: pending }), selected: previous.selected.filter((value) => value !== key) }));
    try {
      const response = isWeb ? await api.captureWeb(spaceId, url, result.paper.title) : await api.pinPaper(spaceId, result.paper, true);
      if (!alive.current) return;
      const job = { ...pending, ...response, status: response.status.toUpperCase() };
      setState((previous) => ({ ...previous, jobs: pruneJobs({ ...previous.jobs, [key]: job }) }));
      notifyJob(job);
      scheduleRefresh();
    } catch (error) {
      if (!alive.current) return;
      const message = error instanceof ApiError ? error.message : "Could not pin this paper.";
      setState((previous) => ({ ...previous, jobs: pruneJobs({ ...previous.jobs, [key]: { ...pending, status: "ERROR", message } }) }));
      notifyTask({ id: pending.taskId, spaceId, module: "library", title: `Could not save ${pending.title}`, message, status: "error" });
    } finally {
      saving.current.delete(key);
    }
  }

  const shownPapers = filterResults(results, filters);
  const shownWeb = includeWeb ? filterResults(webResults, filters) : [];
  const shown = [...shownPapers, ...shownWeb];
  const selectable = [...new Set(shown.filter(({ paper }) => {
    const job = jobs[paperIdentity(paper)];
    return !paperIsPinned(paper, pins, job) && (!job || ["ERROR", "INTERRUPTED"].includes(job.status))
      && (paper.source !== "web" || Boolean(paper.url || paper.pdf_url));
  }).map(({ paper }) => paperIdentity(paper)))];
  const chosen = selected.filter((key) => selectable.includes(key));
  const availableResults = [...results, ...(includeWeb ? webResults : [])];
  const sources = [...new Set(availableResults.map(({ paper }) => paper.source))].sort();
  const years = [...new Set(availableResults.flatMap(({ paper }) => paper.year == null ? [] : [paper.year]))].sort((a, b) => b - a);
  const activeTags = queryTags(query);
  const fragment = /#([A-Za-z0-9_-]*)$/.exec(query)?.[1];
  const visibleTags = fragment ? domainTags.filter((tag) => `${tag.tag} ${tag.label}`.toLowerCase().includes(fragment.toLowerCase())) : domainTags;
  const updateFilters = (patch: Partial<LibraryFilters>) => setState((previous) => ({ ...previous, filters: { ...previous.filters, ...patch } }));

  async function pinSelected() {
    if (!alive.current || bulkPinning) return;
    const unique = new Map(shown.filter(({ paper }) => chosen.includes(paperIdentity(paper))).map((result) => [paperIdentity(result.paper), result]));
    setBulkPinning(true);
    try { await mapWithConcurrency([...unique.values()], 3, pin); } finally { if (alive.current) setBulkPinning(false); }
  }

  function renderCard(result: SearchResult, index: number) {
    const key = paperIdentity(result.paper);
    return <SearchResultCard key={`${key}:${index}`} result={result} pinned={paperIsPinned(result.paper, pins, jobs[key])} job={jobs[key]}
      selectable={selectable.includes(key)} selected={chosen.includes(key)} onSelect={(on) => setState((previous) => ({ ...previous, selected: toggleOne(previous.selected, key, on) }))}
      onPin={() => void pin(result)} />;
  }

  return <ModuleLayout
    header={<PanelHeader eyebrow="Discovery" title="Search and pin papers" text="Find scholarly sources, refine recent results, and pin papers into this space." />}
    aside={<PdfUpload spaceId={spaceId} refreshSpace={refreshSpace} openReader={(paperId) => openReader({ paperId })} />}
    main={<>
      <form className="panel space-y-3 p-4" onSubmit={(event) => void search(event)}>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input className="input" aria-label="Search scholarly sources" value={query} disabled={!ready} onChange={(event) => setState((previous) => ({ ...previous, query: event.target.value }))} placeholder="#ml retrieval augmented generation" list={`domain-tags-${spaceId}`} />
          <button className="btn btn-primary" disabled={!ready || state.searching || !query.trim()}>{state.searching ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}Search</button>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="inline-flex items-center gap-2 text-muted"><input type="checkbox" checked={includeWeb} disabled={!ready || state.searching} onChange={(event) => setState((previous) => ({ ...previous, includeWeb: event.target.checked }))} />Include web results</label>
          {query.trim() ? <a className="inline-flex items-center gap-1 text-indigo-deep hover:underline" href={scholarUrl(query)} target="_blank" rel="noreferrer"><GraduationCap className="h-4 w-4" />Open in Google Scholar</a> : null}
        </div>
        <datalist id={`domain-tags-${spaceId}`}>{domainTags.map((tag) => <option key={tag.tag} value={tag.tag}>{tag.label}</option>)}</datalist>
        {activeTags.length ? <div className="flex flex-wrap items-center gap-2 text-sm"><span className="text-muted">Active domains</span>{activeTags.map((tag) => <button key={tag} type="button" className="rounded-full bg-indigo px-3 py-1 text-white" onClick={() => setState((previous) => ({ ...previous, query: toggleQueryTag(previous.query, tag) }))}>{tag}<X className="ml-1 inline h-3 w-3" /></button>)}</div> : null}
        <div className="max-h-28 overflow-y-auto"><p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted">Domain tags</p><div className="flex flex-wrap gap-2">{visibleTags.map((tag) => <button key={tag.tag} type="button" disabled={!ready} title={tag.description} className={cn("rounded-full border px-3 py-1.5 text-sm", activeTags.includes(tag.tag.toLowerCase()) ? "border-indigo bg-indigo text-white" : "border-line bg-white text-muted")} onClick={() => setState((previous) => ({ ...previous, query: toggleQueryTag(previous.query, tag.tag) }))}>{tag.tag} <span className="hidden sm:inline">{tag.label}</span></button>)}</div></div>
        {history.length ? <details className="text-sm text-muted"><summary className="cursor-pointer">Search history ({history.length})</summary><ul className="mt-2 space-y-1">{history.map((entry) => <li key={`${entry.query}:${entry.includeWeb}`}><button type="button" className="text-left text-indigo-deep hover:underline" disabled={state.searching} onClick={() => setState((previous) => ({ ...previous, query: entry.query, includeWeb: entry.includeWeb }))}>{entry.query}</button><span className="ml-2 text-xs">{entry.count} results · {entry.includeWeb ? "scholarly + web" : "scholarly"} · {new Date(entry.at).toLocaleDateString()}</span></li>)}</ul><p className="mt-2 text-xs">Choose a query, then Search to run it again.</p></details> : null}
      </form>
      {state.error ? <p role="alert" className="rounded-2xl bg-rose/10 p-3 text-sm text-rose">{state.error}</p> : null}
      {state.info ? <p role="status" className="rounded-2xl bg-indigo-soft p-3 text-sm">{state.info}</p> : null}
      {state.searching ? <p role="status" className="flex items-center gap-2 text-sm text-muted"><LoaderCircle className="h-4 w-4 animate-spin" />Searching sources… Previous results remain available below.</p> : null}
      <section className="space-y-4" aria-label="Recent search">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h3 className="font-serif text-2xl">Recent search</h3>{recent ? <p className="mt-1 break-words text-sm text-muted">“{recent.query}” · {recent.count} fetched · {new Date(recent.at).toLocaleString()}</p> : null}</div>
          {recent || history.length ? <button type="button" className="btn h-9 px-3" disabled={state.searching} onClick={() => setState(clearRecentSearch)}><X className="h-4 w-4" />Clear recent search</button> : null}
        </div>
        {recent ? <>
          <div className="panel grid gap-3 p-4 sm:grid-cols-2">
            <label className="text-sm">Sort results<select className="input mt-1" value={filters.sort} onChange={(event) => updateFilters({ sort: event.target.value as LibraryFilters["sort"] })}><option value="relevance">Relevance</option><option value="newest">Year: newest first</option><option value="oldest">Year: oldest first</option><option value="authors">Authors: A–Z</option></select></label>
            <label className="text-sm">Filter by author<input className="input mt-1" value={filters.author} onChange={(event) => updateFilters({ author: event.target.value })} placeholder="Any author" /></label>
            <label className="text-sm">Filter by year<select className="input mt-1" value={filters.year} onChange={(event) => updateFilters({ year: event.target.value })}><option value="">All years</option>{filters.year && filters.year !== "unknown" && !years.includes(Number(filters.year)) ? <option value={filters.year}>{filters.year} (no results)</option> : null}{years.map((year) => <option key={year} value={year}>{year}</option>)}<option value="unknown">Unknown year</option></select></label>
            <label className="text-sm">Filter by source<select className="input mt-1" value={filters.source} onChange={(event) => updateFilters({ source: event.target.value })}><option value="">All sources</option>{filters.source && !sources.includes(filters.source) ? <option value={filters.source}>{filters.source} (no results)</option> : null}{sources.map((source) => <option key={source} value={source}>{source}</option>)}</select></label>
            <div className="flex flex-wrap items-center justify-between gap-2 sm:col-span-2"><p className="text-xs text-muted">{shown.length} shown. These controls only refine fetched results; source ranking is unchanged.</p><button type="button" className="text-sm text-indigo-deep hover:underline" onClick={() => setState((previous) => ({ ...previous, filters: defaultFilters }))}>Reset filters</button></div>
          </div>
          {health.filter((source) => !["ok", "healthy"].includes(source.status)).map((source) => <p key={source.source} className="rounded-2xl bg-amber/10 p-3 text-sm text-amber">{source.source}: {source.error ?? source.status}</p>)}
          {shown.length ? <div className="panel flex flex-wrap items-center gap-3 px-4 py-3">
            <SelectAllToggle checked={allSelected(chosen, selectable)} indeterminate={chosen.length > 0} disabled={!selectable.length || bulkPinning} onToggle={() => setState((previous) => ({ ...previous, selected: toggleAll(previous.selected, selectable) }))} label="Select visible" />
            <span className="text-sm text-muted">{chosen.length} selected</span>
            <button type="button" className="btn btn-primary ml-auto h-9 px-3" disabled={!chosen.length || bulkPinning} onClick={() => void pinSelected()}>{bulkPinning ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Pin selected</button>
          </div> : null}
          <SearchSection title="Papers" count={shownPapers.length}>{shownPapers.map(renderCard)}</SearchSection>
          {includeWeb ? <SearchSection title="From the web" count={shownWeb.length}>{shownWeb.map(renderCard)}</SearchSection> : null}
          {includeWeb && !recent.includeWeb ? <p className="text-sm text-muted">Search again with web results enabled to fetch web sources.</p> : null}
        </> : <EmptyInset title="No recent search" text="Run a search to discover papers. Pinned papers are available in the sidebar." />}
      </section>
      {Object.values(jobs).some((job) => isPollingJob(job) || ["PINNING", "INTERRUPTED", "ERROR", "FAILED"].includes(job.status)) ? <section className="panel space-y-2 p-4" aria-label="Library tasks"><h3 className="font-medium">Library tasks</h3>{Object.entries(jobs).filter(([, job]) => isPollingJob(job) || ["PINNING", "INTERRUPTED", "ERROR", "FAILED"].includes(job.status)).map(([key, job]) => <div key={key} className="text-sm"><p>{job.title}: {statusLabels[job.status] ?? job.status}</p>{job.pollError || job.message ? <p role={job.pollError || ["ERROR", "FAILED"].includes(job.status) ? "alert" : "status"} className="text-xs text-muted">{job.pollError || job.message}</p> : null}</div>)}</section> : null}
    </>} />;
}

function SearchSection({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return <section><div className="mb-3 flex items-center gap-3"><h4 className="font-serif text-xl">{title}</h4><span className="rounded-full bg-linen px-3 py-1 text-xs text-muted">{count}</span></div><div className="grid gap-4">{count ? children : <p className="rounded-2xl border border-dashed border-line p-5 text-sm text-muted">No {title === "Papers" ? "papers" : "web results"} match this search and its filters.</p>}</div></section>;
}

function hostName(value?: string | null): string {
  try { return value ? new URL(value).hostname.replace(/^www\./, "") : ""; } catch { return ""; }
}

function SearchResultCard({ result, pinned, job, selectable, selected, onSelect, onPin }: {
  result: SearchResult; pinned: boolean; job?: LibraryJob; selectable: boolean; selected: boolean;
  onSelect: (on: boolean) => void; onPin: () => void;
}) {
  const { paper } = result;
  const isWeb = paper.source === "web";
  const url = paper.url || paper.pdf_url;
  const failedRequest = job && ["ERROR", "INTERRUPTED"].includes(job.status);
  const showPinned = pinned || Boolean(job && !failedRequest);
  return <article className={cn("paper-card p-5", isWeb && "border-indigo/30 bg-indigo-soft/20", job?.status === "PINNING" && "animate-pin-ring", selected && "border-indigo/50 ring-2 ring-indigo/20")}>
    <div className="flex flex-col justify-between gap-4 md:flex-row">
      <div className="flex min-w-0 gap-3">
        {selectable ? <input type="checkbox" className="mt-1.5 h-4 w-4 shrink-0" checked={selected} onChange={(event) => onSelect(event.target.checked)} aria-label={`Select ${paper.title}`} /> : null}
        <div className="min-w-0"><p className="mb-2 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-indigo-soft px-2 py-1 text-indigo-deep">{isWeb ? <Globe className="mr-1 inline h-3 w-3" /> : null}{paper.source}</span>{paper.year ? <span>{paper.year}</span> : null}{typeof result.score === "number" ? <span className="text-muted">score {result.score.toFixed(2)}</span> : null}</p><h4 className="font-serif text-2xl">{paper.title}</h4><p className="mt-1 text-sm text-muted">{isWeb ? hostName(url) : paper.authors?.join(", ") || paper.venue || "Unknown authors"}</p></div>
      </div>
      <div className="flex shrink-0 flex-col items-start gap-2 md:items-end"><div className="flex flex-wrap gap-2">
        {showPinned ? <span className="btn cursor-default border-indigo/40 bg-indigo-soft text-indigo-deep" role="status"><Check className="h-4 w-4" />{isWeb ? "Saved" : "Pinned"}</span> : <button type="button" className="btn btn-primary" disabled={!selectable} onClick={onPin}>{failedRequest ? "Retry" : isWeb ? "Save to space" : "Pin"}</button>}
        {!isWeb ? <a className="btn" href={scholarUrl(paper.title)} target="_blank" rel="noreferrer"><GraduationCap className="h-4 w-4" />Scholar</a> : url ? <a className="btn" href={url} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" />Open page</a> : null}
      </div>
        {job ? <span className={cn("inline-flex items-center gap-1 text-xs", job.status === "FAILED" || job.status === "ERROR" ? "text-rose" : "text-muted")}>{job.status === "PINNING" || isPollingJob(job) ? <LoaderCircle className="h-3 w-3 animate-spin" /> : job.status === "READY" ? <CircleCheck className="h-3 w-3" /> : null}{statusLabels[job.status] ?? job.status}</span> : null}
        {job?.pollError || job?.message ? <span role={job.pollError || failedRequest || job.status === "FAILED" ? "alert" : "status"} className="max-w-xs text-xs text-muted">{job.pollError || job.message}</span> : null}
      </div>
    </div>
    <p className="mt-4 line-clamp-3 text-sm leading-6 text-muted">{paper.abstract || result.rank_explanation || "No abstract available."}</p>
    {!isWeb && url ? <a className="mt-3 inline-flex items-center gap-1 text-sm text-indigo-deep hover:underline" href={url} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" />Open source</a> : null}
  </article>;
}
