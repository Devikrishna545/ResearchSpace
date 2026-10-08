"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, BookOpen, FileText, Library, MessageSquare, Search, X } from "lucide-react";
import { api, asList, ApiError } from "@/lib/api/client";
import type { ContentHit, ReaderTarget, SpaceDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ComparePanel } from "@/features/compare/components/grounded-compare";
import { LibraryPanel } from "@/features/papers/components/library-panel";
import { PinnedPapers } from "@/features/papers/components/pinned-papers";
import { PaperReader } from "@/features/papers/components/paper-reader";
import { NotesPanel } from "@/features/notes/components/notes-panel";
import { ChatPanel, type ChatFocus, type ChatPrefill } from "@/features/chat/components/chat-panel";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { SpaceContext } from "./space-context";
import { useWorkspaceState } from "../use-workspace-state";
import { isRecord, isStringArray } from "../workspace-state";
import { CONTEXT_EVENT } from "@/lib/task-events";

type Tab = "library" | "chat" | "compare" | "notes";
// Library is the opening module of a research space; Chat follows it.
const tabs: Array<{ id: Tab; label: string; icon: typeof MessageSquare }> = [
  { id: "library", label: "Library", icon: Library },
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "compare", label: "Compare", icon: BookOpen },
  { id: "notes", label: "Notes", icon: FileText }
];

interface WorkspaceView { activeTab: Tab; visited: string[] }
function validView(value: unknown): value is WorkspaceView {
  return isRecord(value) && tabs.some((tab) => tab.id === value.activeTab) && isStringArray(value.visited)
    && value.visited.every((id) => tabs.some((tab) => tab.id === id));
}

export function SpaceWorkspace({ spaceId }: { spaceId: string }) {
  return <Workspace key={spaceId} spaceId={spaceId} />;
}

function Workspace({ spaceId }: { spaceId: string }) {
  const [space, setSpace] = useState<SpaceDetail | null>(null);
  const [view, setView, ready] = useWorkspaceState<WorkspaceView>(spaceId, "navigation", { activeTab: "library", visited: ["library"] }, validView);
  const [pinsOpen, setPinsOpen] = useWorkspaceState(spaceId, "mobile-pins", false, (value): value is boolean => typeof value === "boolean");
  const activeTab = view.activeTab;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [readerTarget, setReaderTarget] = useState<ReaderTarget | null>(null);
  const [chatPrefill, setChatPrefill] = useState<ChatPrefill | null>(null);
  const [chatFocus, setChatFocus] = useState<ChatFocus | null>(null);
  const [reportFocus, setReportFocus] = useState<{ id: string; nonce: number } | null>(null);
  const { confirm, dialog } = useConfirm();
  const setActiveTab = useCallback((tab: Tab) => setView((previous) => ({ activeTab: tab, visited: [...new Set([...previous.visited, tab])] })), [setView]);

  const refreshSpace = useCallback(async () => {
    const value = await api.space(spaceId);
    setSpace(value);
  }, [spaceId]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const loaded = await api.space(spaceId);
        if (!cancelled) setSpace(loaded);
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Unable to load this research space.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [spaceId]);

  useEffect(() => {
    const changed = (event: Event) => {
      if ((event as CustomEvent<{ spaceId: string }>).detail.spaceId !== spaceId) return;
      void refreshSpace().then(() => setRefreshError(null)).catch((err: unknown) => setRefreshError(err instanceof Error ? err.message : "Could not refresh pinned papers."));
    };
    window.addEventListener(CONTEXT_EVENT, changed);
    return () => window.removeEventListener(CONTEXT_EVENT, changed);
  }, [spaceId, refreshSpace]);

  if (loading || !ready) return <WorkspaceShellSkeleton />;
  if (error || !space) return <main className="mx-auto max-w-3xl p-8"><div className="panel p-8"><Link className="btn mb-5" href="/"><ArrowLeft className="h-4 w-4" />Dashboard</Link><h1 className="font-serif text-3xl">Unable to open space</h1><p className="mt-3 text-muted">{error ?? "The space was not found."}</p></div></main>;

  const openReader = (target: ReaderTarget) => setReaderTarget(target);
  const openChat = (sessionId: string) => { setActiveTab("chat"); setChatFocus({ sessionId, nonce: Date.now() }); };
  const pinned = <PinnedPapers spaceId={spaceId} pins={space.pins} refreshSpace={refreshSpace} openReader={openReader} confirm={confirm} />;

  return (
    <div className="workspace-shell min-h-screen bg-transparent">
      <CommandPalette spaceId={spaceId} onOpenChat={openChat} />
      <aside className="workspace-navigation border-r border-line/80 bg-paper/80 p-4 backdrop-blur">
        <div className="hidden lg:block">
        <Link className="mb-6 inline-flex items-center gap-2 text-sm text-muted hover:text-indigo-deep" href="/"><ArrowLeft className="h-4 w-4" />Dashboard</Link>
        <p className="break-words font-serif text-2xl leading-tight text-ink">{space.name}</p>
        <p className="mt-2 text-sm text-muted">{space.pins.length} pinned papers</p>
        <nav className="mt-8 space-y-2" aria-label="Space navigation">
          {tabs.map((item) => {
            const Icon = item.icon;
            return <button key={item.id} aria-current={activeTab === item.id ? "page" : undefined} className={cn("flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm transition", activeTab === item.id ? "bg-indigo text-white shadow-card" : "hover:bg-white")} onClick={() => setActiveTab(item.id)}><Icon className="h-4 w-4" />{item.label}</button>;
          })}
        </nav>
        </div>
        <div className="mt-2 min-h-0 lg:mt-4">
          <button className="flex w-full items-center justify-between py-1 text-sm font-semibold lg:hidden" aria-expanded={pinsOpen} aria-controls="sidebar-papers" onClick={() => setPinsOpen((open) => !open)}>Pinned papers ({space.pins.length})<span>{pinsOpen ? "Hide" : "Show"}</span></button>
          <div id="sidebar-papers" className={cn(!pinsOpen && "hidden lg:block")}>{pinned}</div>
        </div>
      </aside>

      <main className="workspace-main min-w-0 p-4 md:p-6">
        <div className="mb-5 flex items-center gap-3 lg:hidden">
          <Link className="btn shrink-0" href="/" aria-label="Back to dashboard"><ArrowLeft className="h-4 w-4" /></Link>
          <nav className="-mx-1 flex flex-1 gap-1 overflow-x-auto px-1 pb-1" aria-label="Space navigation">
            {tabs.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  aria-current={activeTab === item.id ? "page" : undefined}
                  className={cn(
                    "flex shrink-0 items-center gap-2 rounded-full border px-4 py-2 text-sm transition",
                    activeTab === item.id
                      ? "border-transparent bg-indigo text-white shadow-card"
                      : "border-line bg-paper text-muted hover:text-ink"
                  )}
                  onClick={() => setActiveTab(item.id)}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>
        <div className="mx-auto min-w-0 max-w-[100rem]">
          {refreshError ? <p role="alert" className="mb-4 rounded-2xl border border-rose/20 bg-rose/5 p-3 text-sm text-rose">{refreshError}</p> : null}
          <SpaceContext spaceId={spaceId} spaceName={space.name} pins={space.pins} onAsk={(text) => { setActiveTab("chat"); setChatPrefill({ text, nonce: Date.now() }); }} onOpenNotes={() => setActiveTab("notes")} onOpenChat={openChat} onOpenCompare={(id) => { setActiveTab("compare"); if (id) setReportFocus({ id, nonce: Date.now() }); }} />
          {view.visited.includes("library") ? <div hidden={activeTab !== "library"} aria-label="Library module"><LibraryPanel spaceId={spaceId} pins={space.pins} refreshSpace={refreshSpace} openReader={openReader} /></div> : null}
          {view.visited.includes("chat") ? <div hidden={activeTab !== "chat"} aria-label="Chat module"><ChatPanel active={activeTab === "chat"} spaceId={spaceId} pins={space.pins} openReader={openReader} prefill={chatPrefill} focus={chatFocus} /></div> : null}
          {view.visited.includes("compare") ? <div hidden={activeTab !== "compare"} aria-label="Compare module"><ComparePanel active={activeTab === "compare"} focusReport={reportFocus} spaceId={spaceId} pins={space.pins} onOpenReader={openReader} /></div> : null}
          {view.visited.includes("notes") ? <div hidden={activeTab !== "notes"} aria-label="Notes module"><NotesPanel active={activeTab === "notes"} spaceId={spaceId} pins={space.pins} openReader={openReader} /></div> : null}
        </div>
      </main>

      {readerTarget ? <PaperReader spaceId={spaceId} target={readerTarget} onClose={() => setReaderTarget(null)} /> : null}
      {dialog}
    </div>
  );
}

function CommandPalette({ spaceId, onOpenChat }: { spaceId: string; onOpenChat: (sessionId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<ContentHit[]>([]);
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setOpen(true); } }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, []);
  useEffect(() => { if (!open || query.trim().length < 2) { setHits([]); return; } const handle = window.setTimeout(() => { api.searchContent(spaceId, query.trim()).then((r) => setHits(asList(r))).catch(() => setHits([])); }, 250); return () => window.clearTimeout(handle); }, [open, query, spaceId]);
  if (!open) return null;
  return <div className="fixed inset-0 z-50 bg-ink/20 p-4 backdrop-blur-sm" onClick={() => setOpen(false)}><div className="mx-auto mt-20 max-w-2xl rounded-3xl border border-line bg-paper p-4 shadow-soft" onClick={(e) => e.stopPropagation()}><div className="flex items-center gap-3"><Search className="h-5 w-5 text-muted" /><input autoFocus className="w-full bg-transparent py-3 outline-none" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search notes and turns?" /><button className="btn h-9 w-9 p-0" onClick={() => setOpen(false)}><X className="h-4 w-4" /></button></div><div className="mt-3 max-h-96 overflow-auto space-y-2">{hits.map((hit) => {
    const body = <><span className="text-xs uppercase tracking-widest text-indigo-deep">{hit.type}</span><p className="mt-1 text-sm text-muted">{hit.snippet}</p></>;
    return hit.type === "turn" && hit.session_id
      ? <button key={`${hit.type}-${hit.id}`} type="button" className="block w-full rounded-2xl border border-line bg-white p-3 text-left hover:border-indigo/40" onClick={() => { onOpenChat(hit.session_id as string); setOpen(false); }}>{body}</button>
      : <div key={`${hit.type}-${hit.id}`} className="rounded-2xl border border-line bg-white p-3">{body}</div>;
  })}</div></div></div>;
}

function WorkspaceShellSkeleton() { return <main className="min-h-screen p-8"><div className="mx-auto max-w-6xl"><div className="skeleton mb-6 h-14 w-72" /><div className="panel p-6"><div className="skeleton h-96" /></div></div></main>; }
