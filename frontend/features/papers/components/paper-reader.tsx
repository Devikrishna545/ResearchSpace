"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Trash2, X } from "lucide-react";
import { api, asList } from "@/lib/api/client";
import { findQuoteRange } from "@/features/papers/quote-highlight";
import type { Note, PaperContent, PaperContentChunk, ReaderTarget } from "@/lib/types";
import { cn } from "@/lib/utils";
import { notifyTask } from "@/lib/task-events";

interface SelectionAnchor { chunkId: string; start: number; end: number; quote: string; x: number; y: number }
/** Max reader chunks the API returns; used when jumping to a cited passage that may sit deep in a paper. */
const READER_MAX_CHUNKS = 500;

export function PaperReader({ spaceId, target, onClose }: { spaceId: string; target: ReaderTarget; onClose: () => void }) {
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const [content, setContent] = useState<PaperContent | null>(null);
  const [annotations, setAnnotations] = useState<Note[]>([]);
  const [active, setActive] = useState<Note | null>(null);
  const [selection, setSelection] = useState<SelectionAnchor | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const loadAnnotations = useCallback(async () => setAnnotations(asList(await api.annotations(spaceId, target.paperId))), [spaceId, target.paperId]);
  const focusChunkId = target.chunkId ?? null;
  // Grounded evidence cites source artifacts, not reader chunks: locate those by quote, then by page.
  const locateByEvidence = !focusChunkId && Boolean(target.quote || target.page);

  useEffect(() => {
    setContent(null);
    setError(null);
    Promise.all([api.paperContent(target.paperId, spaceId, focusChunkId || locateByEvidence ? READER_MAX_CHUNKS : undefined), api.annotations(spaceId, target.paperId)])
      .then(([paperContent, notes]) => { setContent(paperContent); setAnnotations(asList(notes)); })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unable to open paper."));
  }, [spaceId, target.paperId, focusChunkId, locateByEvidence]);

  useEffect(() => {
    if (!target.noteId || !content) return;
    const timer = window.setTimeout(() => {
      const el = document.getElementById(`annotation-${target.noteId}`);
      el?.scrollIntoView({ block: "center", behavior: "smooth" });
      const note = annotations.find((item) => item.id === target.noteId);
      if (note) setActive(note);
    }, 100);
    return () => window.clearTimeout(timer);
  }, [annotations, content, target.noteId]);

  const focusedChunk = useMemo(() => {
    if (!content) return null;
    if (focusChunkId) return content.chunks.find((chunk) => chunk.chunk_id === focusChunkId) ?? null;
    if (!locateByEvidence) return null;
    return (target.quote ? content.chunks.find((chunk) => findQuoteRange(chunk.text, target.quote)) : undefined)
      ?? (target.page ? content.chunks.find((chunk) => chunk.page === target.page) : undefined)
      ?? null;
  }, [content, focusChunkId, locateByEvidence, target.quote, target.page]);
  useEffect(() => {
    if (!focusedChunk) return;
    const timer = window.setTimeout(() => {
      document.querySelector(`[data-chunk-id="${CSS.escape(focusedChunk.chunk_id)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [focusedChunk]);

  function textOffset(root: HTMLElement, node: Node, offset: number): number {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let total = 0;
    let current = walker.nextNode();
    while (current) {
      if (current === node) return total + offset;
      total += current.textContent?.length ?? 0;
      current = walker.nextNode();
    }
    return total;
  }

  function captureSelection() {
    const selected = window.getSelection();
    if (!selected || selected.rangeCount === 0 || selected.isCollapsed) return;
    const range = selected.getRangeAt(0);
    // Offsets must be measured against the body paragraph only. The chunk <section>
    // also contains a section/page label, and counting it would shift every offset.
    const startEl = range.startContainer.parentElement?.closest<HTMLElement>("[data-chunk-body]");
    const endEl = range.endContainer.parentElement?.closest<HTMLElement>("[data-chunk-body]");
    if (!startEl || !endEl || startEl.dataset.chunkBody !== endEl.dataset.chunkBody) return;
    const start = textOffset(startEl, range.startContainer, range.startOffset);
    const end = textOffset(startEl, range.endContainer, range.endOffset);
    if (end <= start) return;
    const rect = range.getBoundingClientRect();
    setSelection({ chunkId: startEl.dataset.chunkBody || "", start, end, quote: selected.toString(), x: rect.left + rect.width / 2, y: rect.top });
  }

  async function saveAnchor(noteContent: string) {
    if (!selection) return;
    try {
      const note = await api.createNote(spaceId, noteContent, target.paperId, { chunk_id: selection.chunkId, anchor_quote: selection.quote, anchor_start: selection.start, anchor_end: selection.end, color: "yellow" });
      if (!alive.current) return;
      setSelection(null);
      setDraft("");
      window.getSelection()?.removeAllRanges();
      notifyTask({ id: `annotation:${note.id}`, spaceId, module: "notes", title: "Paper annotation saved", status: "success" });
      await loadAnnotations();
    } catch (err) { if (alive.current) setError(err instanceof Error ? err.message : "Unable to save the annotation."); }
  }

  const external = content?.paper.local_pdf_available ? api.uploadedFileUrl(target.paperId) : content?.paper.url || content?.paper.pdf_url;
  return <div className="fixed inset-0 z-50 bg-ink/25 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Paper preview" onMouseUp={captureSelection} onKeyUp={captureSelection}>
    <aside className="ml-auto flex h-full w-full max-w-4xl flex-col border-l border-line bg-paper shadow-soft">
      <header className="border-b border-line bg-white/80 p-5 backdrop-blur">
        <div className="flex items-start justify-between gap-4"><div><p className="eyebrow mb-2">Paper preview</p><h2 className="font-serif text-3xl leading-tight">{content?.paper.title ?? "Loading paper"}</h2>{content ? <p className="mt-2 text-sm text-muted">{content.paper.authors.join(", ") || content.paper.venue || "Unknown authors"} {content.paper.year ? `· ${content.paper.year}` : ""}</p> : null}</div><button className="btn h-10 w-10 p-0" onClick={onClose} aria-label="Close paper preview"><X className="h-4 w-4" /></button></div>
        {content ? <div className="mt-3 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-indigo-soft px-2 py-1 text-indigo-deep">{content.paper.source ?? "paper"}</span><span className="rounded-full bg-linen px-2 py-1 text-muted">{content.paper.ingest_status ?? "UNKNOWN"}</span>{external ? <a className="rounded-full bg-white px-2 py-1 text-indigo-deep hover:underline" href={external} target="_blank" rel="noreferrer">{content.paper.local_pdf_available ? "Open original PDF" : "External link"}</a> : null}{focusedChunk ? <button type="button" className="rounded-full bg-amber/15 px-2 py-1 font-medium text-ink hover:underline" onClick={() => document.querySelector(`[data-chunk-id="${CSS.escape(focusedChunk.chunk_id)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" })}>Cited passage · {focusedChunk.section || "Section unknown"}{focusedChunk.page ? ` · p. ${focusedChunk.page}` : ""}</button> : null}</div> : null}
        {content && (focusChunkId || locateByEvidence) && !focusedChunk ? <p role="status" className="mt-3 rounded-2xl border border-amber/30 bg-amber/10 p-3 text-sm">The cited passage is no longer part of this paper&apos;s indexed text, so it cannot be highlighted.</p> : null}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6 md:px-10">
        {error ? <p className="rounded-2xl bg-rose/10 p-4 text-rose">{error}</p> : null}
        {!content && !error ? <div className="skeleton h-96" /> : null}
        {content ? <div className="mx-auto max-w-3xl space-y-8">{content.chunks.length === 0 ? <p className="rounded-2xl border border-amber/30 bg-amber/10 p-4 text-sm text-ink">No extractable text is available for citations. {content.paper.local_pdf_available ? "Open the original PDF above; scanned pages need OCR before they can be cited." : "Try an accessible PDF or abstract."}</p> : null}{content.chunks.map((chunk) => <ReaderChunk key={chunk.chunk_id} chunk={chunk} annotations={annotations.filter((note) => note.chunk_id === chunk.chunk_id)} onOpen={setActive} focused={chunk.chunk_id === focusedChunk?.chunk_id} focusQuote={chunk.chunk_id === focusedChunk?.chunk_id ? target.quote : null} />)}</div> : null}
      </div>
      {selection ? <div className="fixed z-[60] w-72 -translate-x-1/2 rounded-2xl border border-line bg-white p-3 shadow-card" style={{ left: selection.x, top: Math.max(selection.y - 12, 12) }}><p className="mb-2 line-clamp-2 text-xs text-muted">“{selection.quote}”</p><div className="flex gap-2"><button className="btn btn-primary h-9 px-3" onClick={() => void saveAnchor("")}>Highlight</button><button className="btn h-9 px-3" onClick={() => setDraft((value) => value || " ")}>Add note</button></div>{draft ? <div className="mt-2"><textarea className="input min-h-24" value={draft.trimStart()} onChange={(e) => setDraft(e.target.value)} placeholder="Attach a note" /><button className="btn btn-primary mt-2 h-9 px-3" onClick={() => void saveAnchor(draft.trim())}>Save</button></div> : null}</div> : null}
      {active ? <AnnotationCard note={active} onClose={() => setActive(null)} onDelete={async () => { try { await api.deleteNote(active.id); if (!alive.current) return; notifyTask({ id: `annotation:delete:${active.id}`, spaceId, module: "notes", title: "Annotation deleted", status: "success" }); setActive(null); await loadAnnotations(); } catch (err) { if (alive.current) setError(err instanceof Error ? err.message : "Unable to delete the annotation."); } }} onSave={async (value) => { try { const updated = await api.updateNote(active.id, value); if (!alive.current) return; setActive(updated); notifyTask({ id: `annotation:update:${active.id}:${Date.now()}`, spaceId, module: "notes", title: "Annotation updated", status: "success" }); await loadAnnotations(); } catch (err) { if (alive.current) setError(err instanceof Error ? err.message : "Unable to update the annotation."); } }} /> : null}
    </aside>
  </div>;
}

function ReaderChunk({ chunk, annotations, onOpen, focused = false, focusQuote }: { chunk: PaperContentChunk; annotations: Note[]; onOpen: (note: Note) => void; focused?: boolean; focusQuote?: string | null }) {
  const pieces: Array<{ text: string; start: number; note?: Note }> = [];
  let cursor = 0;
  const sorted = annotations
    .filter((note) => typeof note.anchor_start === "number" && typeof note.anchor_end === "number" && note.anchor_end > note.anchor_start)
    .sort((a, b) => (a.anchor_start ?? 0) - (b.anchor_start ?? 0));
  for (const note of sorted) {
    const rawStart = Math.max(0, Math.min(note.anchor_start ?? 0, chunk.text.length));
    const end = Math.max(rawStart, Math.min(note.anchor_end ?? rawStart, chunk.text.length));
    // Clip against already-painted ranges so a partially overlapping highlight still
    // renders (and stays clickable) instead of disappearing. Fully contained ranges
    // have no visible remainder; those stay reachable from the Notes tab.
    const start = Math.max(rawStart, cursor);
    if (end <= start) continue;
    if (start > cursor) pieces.push({ text: chunk.text.slice(cursor, start), start: cursor });
    pieces.push({ text: chunk.text.slice(start, end), start, note });
    cursor = end;
  }
  if (cursor < chunk.text.length) pieces.push({ text: chunk.text.slice(cursor), start: cursor });
  // The cited quote is marked inside plain text; existing annotation highlights keep priority.
  const cited = focused ? findQuoteRange(chunk.text, focusQuote) : null;
  function plain(text: string, start: number, key: string) {
    if (!cited) return <span key={key}>{text}</span>;
    const end = start + text.length;
    const from = Math.max(start, cited.start);
    const to = Math.min(end, cited.end);
    if (from >= to) return <span key={key}>{text}</span>;
    return <span key={key}>{text.slice(0, from - start)}<mark className="rounded bg-amber/35 px-0.5 text-ink ring-1 ring-amber/40">{text.slice(from - start, to - start)}</mark>{text.slice(to - start)}</span>;
  }
  return <section data-chunk-id={chunk.chunk_id} aria-current={focused ? "location" : undefined} className={cn("scroll-mt-28 rounded-3xl border border-transparent p-1 focus-within:border-indigo/30", focused && "animate-cite-flash border-amber/50 bg-amber/5 p-4 shadow-card")}><p className="mb-2 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted">{focused ? <span className="rounded-full bg-amber/20 px-2 py-0.5 tracking-normal text-ink">Cited passage</span> : null}{chunk.section || "Section unknown"}{chunk.page ? ` · p. ${chunk.page}` : ""}</p><p data-chunk-body={chunk.chunk_id} className="whitespace-pre-wrap font-serif text-lg leading-9 text-ink">{pieces.map((piece, index) => {
    const note = piece.note;
    return note ? <button id={`annotation-${note.id}`} key={`${note.id}-${index}`} className="rounded bg-amber/30 px-0.5 text-left underline decoration-amber decoration-2 underline-offset-4 focus:outline-none focus:ring-2 focus:ring-amber" onClick={() => onOpen(note)} aria-label={`Highlight: ${note.anchor_quote || piece.text}`}>{piece.text}</button> : plain(piece.text, piece.start, `text-${index}`);
  })}</p></section>;
}

function AnnotationCard({ note, onClose, onDelete, onSave }: { note: Note; onClose: () => void; onDelete: () => Promise<void>; onSave: (content: string) => Promise<void> }) {
  const [value, setValue] = useState(note.content);
  useEffect(() => setValue(note.content), [note]);
  return <div className="absolute bottom-5 right-5 z-[70] w-[min(26rem,calc(100%-2.5rem))] rounded-3xl border border-line bg-white p-5 shadow-soft"><div className="mb-3 flex items-start justify-between gap-3"><div><p className="eyebrow mb-2">Annotation</p>{note.anchor_quote ? <blockquote className="rounded-2xl bg-amber/10 p-3 font-serif text-sm">“{note.anchor_quote}”</blockquote> : null}</div><button className="btn h-9 w-9 p-0" onClick={onClose} aria-label="Close annotation"><X className="h-4 w-4" /></button></div><textarea className="input min-h-28" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Highlight note (optional)" /><div className="mt-3 flex gap-2"><button className="btn btn-primary" onClick={() => void onSave(value)}><Check className="h-4 w-4" />Save</button><button className="btn text-rose" onClick={() => void onDelete()}><Trash2 className="h-4 w-4" />Delete</button></div></div>;
}
