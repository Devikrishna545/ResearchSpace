"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Plus, RefreshCw, Share2, Sparkles, Trash2 } from "lucide-react";
import { api, asList } from "@/lib/api/client";
import type { Note, Pin, ReaderTarget } from "@/lib/types";
import { dateLabel, shortId } from "@/lib/utils";
import { Markdown } from "@/components/ui/markdown";
import { ModuleLayout, PanelHeader, RailCard } from "@/components/ui/module-layout";
import { SharePreview, type ShareItem } from "./share-preview";
import { useWorkspaceState } from "@/features/spaces/use-workspace-state";
import { isRecord } from "@/features/spaces/workspace-state";
import { CONTEXT_EVENT, notifyTask } from "@/lib/task-events";

interface NotesView { content: string; paperId: string; editing: Record<string, string>; refreshAuto: boolean; pendingAuto?: string | null }
function validNotesView(value: unknown): value is NotesView {
  return isRecord(value) && typeof value.content === "string" && typeof value.paperId === "string" && typeof value.refreshAuto === "boolean"
    && isRecord(value.editing) && Object.values(value.editing).every((item) => typeof item === "string")
    && (value.pendingAuto === undefined || value.pendingAuto === null || typeof value.pendingAuto === "string");
}

export function NotesPanel({ spaceId, pins, openReader, active = true }: { spaceId: string; pins: Pin[]; openReader: (target: ReaderTarget) => void; active?: boolean }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [view, setView, ready] = useWorkspaceState<NotesView>(spaceId, "notes", { content: "", paperId: "", editing: {}, refreshAuto: false }, validNotesView);
  const { content, paperId, editing, refreshAuto } = view;
  const setContent = (value: string) => setView((old) => ({ ...old, content: value }));
  const setPaperId = (value: string) => setView((old) => ({ ...old, paperId: value }));
  const setEditing = (update: (previous: Record<string, string>) => Record<string, string>) => setView((old) => ({ ...old, editing: update(old.editing) }));
  const setRefreshAuto = (value: boolean) => setView((old) => ({ ...old, refreshAuto: value }));
  const [generating, setGenerating] = useState<string | null>(null);
  const [sharing, setSharing] = useState<ShareItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const working = useRef(false);
  const alive = useRef(true);
  const pinTitles = new Map(pins.map((pin) => [pin.id, pin.title]));
  const load = useCallback(async () => {
    try { const loaded = await api.notes(spaceId); if (alive.current) setNotes(asList(loaded)); }
    catch (err) { if (alive.current) setError(err instanceof Error ? err.message : "Unable to refresh notes. Previously loaded notes are retained."); }
  }, [spaceId]);
  useEffect(() => {
    alive.current = true;
    void load();
    const changed = (event: Event) => { if ((event as CustomEvent<{ spaceId: string }>).detail.spaceId === spaceId) void load(); };
    window.addEventListener(CONTEXT_EVENT, changed);
    return () => { alive.current = false; window.removeEventListener(CONTEXT_EVENT, changed); };
  }, [load, spaceId]);
  async function change(id: string, title: string, action: () => Promise<unknown>, done?: () => void) {
    if (working.current) return;
    working.current = true;
    setBusy(id);
    setError(null);
    try {
      await action();
      if (!alive.current) return;
      done?.();
      notifyTask({ id: `notes:${id}:${Date.now()}`, spaceId, module: "notes", title, status: "success" });
    } catch (err) {
      if (!alive.current) return;
      const message = err instanceof Error ? err.message : "The note operation failed. Your draft is retained.";
      setError(message);
      notifyTask({ id: `notes:${id}:${Date.now()}`, spaceId, module: "notes", title: "Note operation failed", message, status: "error" });
    } finally { working.current = false; if (alive.current) { setBusy(null); setGenerating(null); setView((old) => old.pendingAuto === id ? { ...old, pendingAuto: null } : old); } }
  }
  async function create() {
    if (!content.trim()) return;
    await change("new", "Note saved", () => api.createNote(spaceId, content.trim(), paperId || null), () => setContent(""));
  }
  if (!ready) return <div className="skeleton h-64" />;
  return <ModuleLayout
    header={<PanelHeader eyebrow="Notebook" title="Notes and annotations" text="Write manual notes or generate structured paper notes locally." />}
    main={<>
      {error ? <p role="alert" className="rounded-2xl border border-rose/20 bg-rose/5 p-3 text-sm text-rose">{error}</p> : null}
      {view.pendingAuto && !generating ? <div role="status" className="rounded-2xl border border-amber/30 bg-amber/10 p-3 text-sm">
        <p>A note-generation request was interrupted by navigation or reload. It may still finish on the server; no request has been resent.</p>
        <div className="mt-2 flex flex-wrap gap-2"><button className="btn" onClick={() => void load()}>Check saved notes</button><button className="btn" onClick={() => setView((old) => ({ ...old, pendingAuto: null }))}>Dismiss notice</button></div>
      </div> : null}
      <div className="panel p-5"><div className="grid min-w-0 gap-4 md:grid-cols-2">
        <div className="min-w-0"><label className="mb-2 block text-sm font-medium" htmlFor="note">Markdown note</label>
          <textarea id="note" className="input min-h-52" value={content} onChange={(e) => setContent(e.target.value)} placeholder="# Observation" disabled={busy === "new"} />
          <select aria-label="Attach note to paper" className="input mt-3" value={paperId} onChange={(e) => setPaperId(e.target.value)} disabled={busy === "new"}><option value="">Space-level note</option>{pins.map((pin) => <option key={pin.id} value={pin.id}>{pin.title}</option>)}</select>
          <button className="btn btn-primary mt-3" disabled={Boolean(busy) || !content.trim()} onClick={() => void create()}><Plus className="h-4 w-4" />{busy === "new" ? "Saving..." : "Save note"}</button>
          <p className="mt-2 text-xs text-muted">Drafts are kept in this browser tab. Save a note to add it to your research space.</p>
        </div>
        <div className="min-w-0 rounded-2xl border border-line bg-paper p-4"><p className="eyebrow mb-3">Preview</p><Markdown content={content || "_Your preview will appear here._"} /></div>
      </div></div>
      {!notes.length ? <p className="rounded-2xl border border-dashed border-line p-5 text-sm text-muted">Your saved notes and paper annotations will appear here.</p> : null}
      <div className="grid min-w-0 gap-4">{notes.map((note) => <article key={note.id} className="paper-card min-w-0 p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted">{note.source ?? "manual"} · {dateLabel(note.updated_at ?? note.created_at)} {note.paper_id ? `· ${pinTitles.get(note.paper_id) ?? shortId(note.paper_id)}` : ""}</p>
          <div className="flex flex-wrap gap-2">
            {note.paper_id && note.chunk_id ? <button className="btn h-9 px-3" onClick={() => { if (note.paper_id) openReader({ paperId: note.paper_id, noteId: note.id }); }}>Open in paper</button> : null}
            <button type="button" className="btn h-9 px-3" disabled={!note.content.trim() && !note.anchor_quote?.trim()} onClick={() => setSharing({ id: note.id, source: { type: "note", id: note.id }, kind: "Saved note", text: note.content || note.anchor_quote || "", citation: note.paper_id ? pinTitles.get(note.paper_id) : undefined })}><Share2 className="h-4 w-4" />Share note</button>
            <button className="btn h-9 px-3" disabled={Boolean(busy)} onClick={() => setEditing((prev) => ({ ...prev, [note.id]: prev[note.id] ?? note.content }))}>Edit</button>
            <button className="btn h-9 px-3 text-rose" aria-label="Delete note" disabled={Boolean(busy)} onClick={() => void change(note.id, "Note deleted", () => api.deleteNote(note.id), () => setEditing((prev) => { const next = { ...prev }; delete next[note.id]; return next; }))}><Trash2 className="h-4 w-4" /></button>
          </div>
        </div>
        {note.anchor_quote ? <blockquote className="mb-3 rounded-2xl border-l-4 border-amber bg-amber/10 p-3 font-serif text-sm">“{note.anchor_quote}”</blockquote> : null}
        {editing[note.id] !== undefined ? <div>
          <textarea aria-label="Edit note" className="input min-h-44" disabled={busy === note.id} value={editing[note.id]} onChange={(e) => setEditing((prev) => ({ ...prev, [note.id]: e.target.value }))} />
          <button className="btn btn-primary mt-3" disabled={Boolean(busy)} onClick={() => void change(note.id, "Note updated", () => api.updateNote(note.id, editing[note.id]), () => setEditing((prev) => { const next = { ...prev }; delete next[note.id]; return next; }))}><Check className="h-4 w-4" />Update</button>
        </div> : note.content ? <Markdown content={note.content} /> : <p className="text-sm text-muted">Highlight only.</p>}
      </article>)}</div>
      {sharing && active ? <SharePreview key={sharing.id} item={sharing} onClose={() => setSharing(null)} /> : null}
    </>}
    aside={<>
      <RailCard title="Auto notes" icon={<Sparkles className="h-5 w-5 text-indigo-deep" />}>
        <p className="mb-3 text-sm text-muted">Generate structured notes (summary, contributions, methodology, results, limitations) locally. Usually 10&ndash;40 seconds.</p>
        <label className="mb-3 flex items-center gap-2 text-sm text-muted"><input type="checkbox" checked={refreshAuto} onChange={(e) => setRefreshAuto(e.target.checked)} /> Regenerate if a note already exists</label>
        {pins.length === 0 ? <p className="text-sm text-muted">Pin papers to generate notes.</p> : null}
        <div className="max-h-72 space-y-2 overflow-y-auto pr-1">{pins.map((pin) => <button key={pin.id} className="btn w-full justify-start text-left" disabled={Boolean(busy)} title={`Generate notes for ${pin.title}`} onClick={() => { if (working.current) return; setGenerating(pin.id); setView((old) => ({ ...old, pendingAuto: pin.id })); void change(pin.id, "Paper notes generated", () => api.autoNote(spaceId, pin.id, refreshAuto)); }}>{generating === pin.id ? <RefreshCw className="h-4 w-4 shrink-0 animate-spin" /> : <Sparkles className="h-4 w-4 shrink-0" />}<span className="truncate">{generating === pin.id ? "Generating notes..." : pin.title}</span></button>)}</div>
        {generating ? <p className="mt-3 text-sm text-muted">Reading the paper and drafting notes locally — this can take up to a minute.</p> : null}
      </RailCard>
    </>} />;
}
