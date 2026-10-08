"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Brain, CircleHelp, Lightbulb, RefreshCw } from "lucide-react";
import { api, asList } from "@/lib/api/client";
import type { ChatSession, GroundedReport, Memory, Note, Pin } from "@/lib/types";
import { cn, dateLabel } from "@/lib/utils";
import { CONTEXT_EVENT } from "@/lib/task-events";
import { useWorkspaceState } from "../use-workspace-state";
import { isRecord } from "../workspace-state";
import { comparisonContextFindings, recentNotes } from "../research-context";
import { MemorySection, RollingSummary } from "./space-memory";

type ContextTab = "memory" | "findings" | "questions";
const contextTabs = [
  { id: "memory", label: "Space memory", icon: Brain },
  { id: "findings", label: "Findings", icon: Lightbulb },
  { id: "questions", label: "Open questions", icon: CircleHelp },
] as const;
function isContextView(value: unknown): value is { open: ContextTab | null } {
  return isRecord(value) && (value.open === null || contextTabs.some((tab) => tab.id === value.open));
}

export function SpaceContext({ spaceId, spaceName, pins, onAsk, onOpenNotes, onOpenChat, onOpenCompare }: {
  spaceId: string; spaceName: string; pins: Pin[]; onAsk: (text: string) => void; onOpenNotes: () => void;
  onOpenChat: (id: string) => void; onOpenCompare: (reportId?: string) => void;
}) {
  const [view, setView] = useWorkspaceState(spaceId, "context", { open: null as ContextTab | null }, isContextView);
  const [memory, setMemory] = useState<Memory | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [report, setReport] = useState<GroundedReport | null>(null);
  const reportId = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const inFlight = useRef(false);
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    const failures: string[] = [];
    try {
      const data = await Promise.allSettled([api.memory(spaceId), api.notes(spaceId), api.chatSessions(spaceId, "all"), api.comparisons(spaceId)]);
      if (!alive.current) return;
      const [memoryResult, notesResult, sessionsResult, reportsResult] = data;
      if (memoryResult.status === "fulfilled") setMemory(memoryResult.value);
      else failures.push("Memory could not be refreshed.");
      if (notesResult.status === "fulfilled") setNotes(asList(notesResult.value));
      else failures.push("Notes could not be refreshed.");
      if (sessionsResult.status === "fulfilled") setSessions(sessionsResult.value);
      else failures.push("Conversation activity could not be refreshed.");
      if (reportsResult.status === "fulfilled") {
        const latest = asList(reportsResult.value)[0]?.id ?? null;
        if (!latest) { setReport(null); reportId.current = null; }
        else if (reportId.current !== latest) {
          try {
            const value = await api.comparison(latest);
            if (alive.current) { setReport(value); reportId.current = latest; }
          } catch { failures.push("Latest comparison findings could not be refreshed."); }
        }
      } else failures.push("Comparison activity could not be refreshed.");
      if (alive.current) setErrors(failures);
    } finally {
      inFlight.current = false;
      if (alive.current) setLoading(false);
    }
  }, [spaceId]);
  useEffect(() => {
    alive.current = true;
    void refresh();
    const changed = (event: Event) => {
      if ((event as CustomEvent<{ spaceId: string }>).detail.spaceId === spaceId) void refresh();
    };
    const visible = () => { if (document.visibilityState === "visible") void refresh(); };
    const interval = window.setInterval(visible, 20000);
    window.addEventListener(CONTEXT_EVENT, changed);
    document.addEventListener("visibilitychange", visible);
    return () => { alive.current = false; window.clearInterval(interval); window.removeEventListener(CONTEXT_EVENT, changed); document.removeEventListener("visibilitychange", visible); };
  }, [spaceId, refresh]);
  const findings = memory?.findings ?? [];
  const questions = memory?.open_questions ?? [];
  const comparisonFindings = comparisonContextFindings(report);
  const open = view.open;
  return <header className="mb-6 min-w-0 border-b border-line/80 pb-4" aria-label="Workspace header">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-5 gap-y-3">
      <div className="min-w-0 flex-1"><p className="mb-1 text-[11px] font-semibold uppercase tracking-widest text-muted">Workspace</p><h1 className="break-words text-lg font-semibold leading-tight text-ink">{spaceName}</h1></div>
      <div role="group" aria-label="Research context" className="flex min-w-0 flex-wrap items-center gap-1">
      {contextTabs.map(({ id, label, icon: Icon }) => <button key={id} type="button" className={cn("inline-flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-xs font-medium transition sm:text-sm", open === id ? "bg-indigo-soft text-indigo-deep" : "text-muted hover:bg-linen hover:text-ink")} aria-expanded={open === id} aria-controls="shared-context-content" onClick={() => setView({ open: open === id ? null : id })}>
        <Icon className="h-4 w-4" />{label}{id !== "memory" ? <span className="rounded-full bg-linen px-1.5 text-xs">{id === "findings" ? findings.length + comparisonFindings.length : questions.length}</span> : null}
      </button>)}
      <button type="button" className="ml-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-muted hover:bg-linen disabled:opacity-50" disabled={loading} onClick={() => void refresh()} aria-label="Refresh shared context"><RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} /></button>
      </div>
    </div>
    {errors.length ? <p role="alert" className="mt-3 text-xs text-rose">{errors.join(" ")} Previously loaded context is retained; use Refresh to retry.</p> : null}
    {open ? <div id="shared-context-content" className="mt-4 max-h-[26rem] overflow-y-auto rounded-2xl border border-line bg-paper/70 p-4">
      {open === "memory" ? <div className="grid min-w-0 gap-5 md:grid-cols-2">
        <div className="min-w-0"><h3 className="mb-2 font-serif text-xl">Conversation summary</h3><RollingSummary summary={memory?.rolling_summary} updatedAt={memory?.updated_at} /><p className="mt-2 text-xs text-muted">Existing AI summary. The live overview includes saved work from all modules without generating new claims.</p></div>
        <div className="min-w-0 space-y-3"><p className="text-sm font-medium">{pins.length} papers · {notes.length} notes · {sessions.length} conversations</p>
          <div><button className="text-sm font-semibold text-indigo-deep hover:underline" onClick={onOpenNotes}>Recent saved notes</button>{notes.length ? <ul className="mt-2 space-y-1">{recentNotes(notes).map((note) => <li key={note.id} className="line-clamp-2 text-sm text-muted">{note.content || note.anchor_quote || "Highlight"} <span className="text-xs">({note.source || "manual"})</span></li>)}</ul> : <p className="text-sm text-muted">No saved notes yet.</p>}</div>
          <div><h4 className="text-sm font-semibold">Recent conversations</h4>{sessions.slice(0, 3).map((session) => <button key={session.id} className="mt-1 block max-w-full truncate text-left text-sm text-indigo-deep hover:underline" onClick={() => onOpenChat(session.id)}>{session.title} · {session.turn_count} messages</button>)}</div>
          <button className="text-left text-sm text-indigo-deep hover:underline" onClick={() => onOpenCompare(report?.id)}>{report ? `Latest comparison · ${dateLabel(report.generated_at)} · ${report.paper_ids.length} papers` : "Open Compare to build evidence-grounded findings"}</button>
        </div>
      </div> : null}
      {open === "findings" ? <div className="grid min-w-0 gap-5 md:grid-cols-2">
        <MemorySection spaceId={spaceId} kind="findings" title="Conversation findings" icon={<Lightbulb className="h-4 w-4 text-amber" />} items={findings} empty="Findings appear after grounded answers." onAsk={onAsk} />
        <section className="min-w-0"><h3 className="font-serif text-lg">Latest comparison findings</h3><p className="mb-3 text-xs text-muted">Shown findings from the latest saved report. Candidate gaps remain candidates, not established facts.</p>
          {comparisonFindings.length ? <ul className="space-y-2">{comparisonFindings.map((finding) => <li key={finding.finding_id} className="rounded-2xl border border-line p-3"><p className="mb-1 text-xs font-medium text-indigo-deep">{finding.kind.replaceAll("_", " ")} · {finding.evidence_status.replaceAll("_", " ").toLowerCase()}</p><p className="text-sm">{finding.statement}</p><button className="mt-2 text-xs font-semibold text-indigo-deep hover:underline" onClick={() => onOpenCompare(report?.id)}>View report and sources</button></li>)}</ul> : <p className="text-sm text-muted">No displayed comparison findings yet.</p>}
        </section>
      </div> : null}
      {open === "questions" ? <MemorySection spaceId={spaceId} kind="questions" title="Open questions" icon={<CircleHelp className="h-4 w-4 text-indigo-deep" />} items={questions} empty="No open questions recorded yet." onAsk={onAsk} /> : null}
    </div> : null}
  </header>;
}
