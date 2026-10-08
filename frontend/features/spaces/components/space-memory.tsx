"use client";

import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { ChevronDown, ChevronsDownUp, ChevronsUpDown, CircleCheck, MessageSquare, RotateCcw } from "lucide-react";
import { hasMoreDetail, memoryHeadline, memoryKey } from "@/features/spaces/memory-items";
import { cn, dateLabel } from "@/lib/utils";
import { Markdown } from "@/components/ui/markdown";
import { useWorkspaceState } from "../use-workspace-state";
import { isRecord, isStringArray } from "../workspace-state";

export function RollingSummary({ summary, updatedAt }: { summary?: string | null; updatedAt?: string | null }) {
  const [expanded, setExpanded] = useState(false);
  if (!summary) return <p className="rounded-2xl border border-line bg-paper p-3 text-sm text-muted">No rolling summary yet.</p>;
  return <div className="rounded-2xl border border-line bg-paper p-3">
    <div className="mb-1 flex items-center justify-between text-xs text-muted"><span className="font-semibold uppercase tracking-widest">Summary</span>{updatedAt ? <span>{dateLabel(updatedAt)}</span> : null}</div>
    <div className={cn("text-sm", !expanded && "line-clamp-4")}><Markdown content={summary} /></div>
    <button type="button" className="mt-1 text-xs font-medium text-indigo-deep hover:underline" onClick={() => setExpanded((value) => !value)}>{expanded ? "Show less" : "Read full summary"}</button>
  </div>;
}

interface MemoryView { expanded: string[]; filter: string; resolved: string[] }
function validMemoryView(value: unknown): value is MemoryView {
  return isRecord(value) && isStringArray(value.expanded) && isStringArray(value.resolved) && typeof value.filter === "string";
}
export function MemorySection({ spaceId, kind, title, icon, items, empty, onAsk }: { spaceId: string; kind: "findings" | "questions"; title: string; icon: ReactNode; items: string[]; empty: string; onAsk?: (text: string) => void }) {
  const [view, setView] = useWorkspaceState<MemoryView>(spaceId, `context-${kind}`, { expanded: [], filter: "", resolved: [] }, validMemoryView);
  const expanded = useMemo(() => new Set(view.expanded), [view.expanded]);
  const resolved = useMemo(() => new Set(view.resolved), [view.resolved]);
  const filter = view.filter;
  const setFilter = (value: string) => setView((old) => ({ ...old, filter: value }));
  const setExpanded = (value: Set<string>) => setView((old) => ({ ...old, expanded: [...value] }));
  const trackable = kind === "questions";

  const entries = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const list = items.map((text, index) => ({ text, index, key: memoryKey(text) }))
      .filter((entry) => !needle || entry.text.toLowerCase().includes(needle));
    // Resolved questions sink to the bottom so open work stays in view.
    return trackable ? [...list].sort((a, b) => Number(resolved.has(a.key)) - Number(resolved.has(b.key))) : list;
  }, [filter, items, resolved, trackable]);

  const allOpen = entries.length > 0 && entries.every((entry) => expanded.has(entry.key));
  const openCount = trackable ? items.filter((text) => !resolved.has(memoryKey(text))).length : items.length;

  function toggle(key: string) {
    setView((old) => ({ ...old, expanded: old.expanded.includes(key) ? old.expanded.filter((item) => item !== key) : [...old.expanded, key] }));
  }
  function toggleResolved(key: string) {
    setView((old) => ({ ...old, resolved: old.resolved.includes(key) ? old.resolved.filter((item) => item !== key) : [...old.resolved, key] }));
  }

  return <section aria-label={title}>
    <div className="mb-2 flex items-center justify-between gap-2">
      <h4 className="flex items-center gap-2 font-serif text-lg">{icon}{title}<span className="rounded-full bg-linen px-2 py-0.5 font-sans text-xs text-muted">{trackable ? `${openCount} open` : items.length}</span></h4>
      {items.length > 1 ? <button type="button" className="inline-flex items-center gap-1 text-xs font-medium text-indigo-deep hover:underline" onClick={() => setExpanded(allOpen ? new Set() : new Set(entries.map((entry) => entry.key)))}>
        {allOpen ? <ChevronsDownUp className="h-3.5 w-3.5" /> : <ChevronsUpDown className="h-3.5 w-3.5" />}{allOpen ? "Collapse all" : "Expand all"}
      </button> : null}
    </div>
    {items.length > 5 ? <input className="input mb-2 py-2 text-xs" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={`Filter ${title.toLowerCase()}`} aria-label={`Filter ${title.toLowerCase()}`} /> : null}
    {items.length === 0 ? <p className="text-sm text-muted">{empty}</p> : null}
    {items.length > 0 && entries.length === 0 ? <p className="text-sm text-muted">No matches.</p> : null}
    <ol className="space-y-2">
      {entries.map((entry) => {
        const isOpen = expanded.has(entry.key);
        const isResolved = trackable && resolved.has(entry.key);
        const expandable = hasMoreDetail(entry.text) || Boolean(onAsk) || trackable;
        return <li key={`${entry.key}-${entry.index}`} className={cn("rounded-2xl border border-line bg-paper transition", isOpen && "border-indigo/30 bg-white", isResolved && "opacity-70")}>
          <button type="button" className="flex w-full items-start gap-2 p-3 text-left text-sm" aria-expanded={isOpen} onClick={() => expandable && toggle(entry.key)}>
            <span className={cn("mt-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[11px] font-bold", isResolved ? "bg-emerald-50 text-emerald-700" : "bg-indigo-soft text-indigo-deep")}>{isResolved ? <CircleCheck className="h-3 w-3" /> : entry.index + 1}</span>
            <span className={cn("flex-1", isResolved && "line-through decoration-muted/60")}>{isOpen ? entry.text : memoryHeadline(entry.text)}</span>
            {expandable ? <ChevronDown className={cn("mt-0.5 h-4 w-4 shrink-0 text-muted transition", isOpen && "rotate-180")} /> : null}
          </button>
          {isOpen && (onAsk || trackable) ? <div className="flex flex-wrap gap-2 px-3 pb-3">
            {onAsk ? <button type="button" className="btn h-8 px-3 text-xs" onClick={() => onAsk(kind === "questions" ? entry.text : `Tell me more about this finding: ${entry.text}`)}><MessageSquare className="h-3.5 w-3.5" />{kind === "questions" ? "Ask in chat" : "Discuss in chat"}</button> : null}
            {trackable ? <button type="button" className="btn h-8 px-3 text-xs" onClick={() => toggleResolved(entry.key)}>{isResolved ? <RotateCcw className="h-3.5 w-3.5" /> : <CircleCheck className="h-3.5 w-3.5" />}{isResolved ? "Reopen" : "Mark resolved"}</button> : null}
          </div> : null}
        </li>;
      })}
    </ol>
  </section>;
}
