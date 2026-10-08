"use client";

import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Trash2 } from "lucide-react";
import type { ConfirmOptions } from "@/components/ui/confirm-dialog";
import { SelectAllToggle } from "@/components/ui/module-layout";
import { useWorkspaceState } from "@/features/spaces/use-workspace-state";
import { api, ApiError } from "@/lib/api/client";
import { notifyTask } from "@/lib/task-events";
import type { Pin, ReaderTarget } from "@/lib/types";
import { cn } from "@/lib/utils";
import { allSelected, toggleAll, toggleOne } from "@/lib/utils/selection";
import { isRecord, isStringArray } from "../library-state";

export interface PinnedPapersProps {
  spaceId: string;
  pins: Pin[];
  refreshSpace: () => Promise<void>;
  openReader: (target: ReaderTarget) => void;
  confirm: (options: ConfirmOptions) => Promise<boolean>;
}
type SidebarState = { selected: string[]; removing: string[] };
const initial: SidebarState = { selected: [], removing: [] };
function isSidebarState(value: unknown): value is SidebarState {
  return isRecord(value) && isStringArray(value.selected) && isStringArray(value.removing);
}

export function PinnedPapers(props: PinnedPapersProps) {
  return <PinnedPapersContent key={props.spaceId} {...props} />;
}

function PinnedPapersContent({ spaceId, pins, refreshSpace, openReader, confirm }: PinnedPapersProps) {
  const [state, setState, ready] = useWorkspaceState(spaceId, "library-pins", initial, isSidebarState);
  const [removed, setRemoved] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [known, setKnown] = useState(() => new Set(pins.map((pin) => pin.id)));
  const recovered = useRef(false);
  const removingNow = useRef(false);
  const alive = useRef(false);
  const idsKey = JSON.stringify(pins.map((pin) => pin.id));
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => setKnown(new Set(JSON.parse(idsKey) as string[])), 700);
    return () => clearTimeout(timer);
  }, [idsKey]);
  useEffect(() => {
    if (!ready || recovered.current) return;
    recovered.current = true;
    if (state.removing.length) queueMicrotask(() => {
      if (!alive.current) return;
      setInfo("The page reloaded before removal was confirmed. The sidebar now shows the server's pinned papers.");
      setState((previous) => ({ ...previous, removing: [] }));
    });
  }, [ready, setState, state.removing.length]);
  useEffect(() => {
    const ids = new Set(JSON.parse(idsKey) as string[]);
    queueMicrotask(() => {
      if (!alive.current) return;
      setRemoved((previous) => previous.filter((id) => ids.has(id)));
      if (ready) setState((previous) => ({ ...previous, selected: previous.selected.filter((id) => ids.has(id)) }));
    });
  }, [idsKey, ready, setState]);
  const visible = pins.filter((pin) => !state.removing.includes(pin.id) && !removed.includes(pin.id));
  const ids = visible.map((pin) => pin.id);
  const chosen = state.selected.filter((id) => ids.includes(id));

  async function remove(paperIds: string[]) {
    if (!alive.current || !ready || removingNow.current) return;
    const targets = pins.filter((pin) => paperIds.includes(pin.id));
    if (!targets.length) return;
    removingNow.current = true;
    setBusy(true);
    const taskId = `unpin:${spaceId}:${crypto.randomUUID()}`;
    try {
      const ok = await confirm(targets.length === 1
        ? { title: "Remove this paper?", message: `“${targets[0].title}” will be unpinned from this space. Its notes stay in the Notes tab and you can pin it again later.`, confirmLabel: "Remove paper" }
        : { title: `Remove ${targets.length} papers?`, message: `${targets.length} papers will be unpinned from this space. Their notes stay in the Notes tab and you can pin them again later.`, confirmLabel: `Remove ${targets.length} papers` });
      if (!alive.current || !ok) return;
      setError(null);
      setInfo(null);
      setState((previous) => ({ selected: previous.selected.filter((id) => !paperIds.includes(id)), removing: paperIds }));
      await api.unpinPapers(spaceId, paperIds);
      if (!alive.current) return;
      setRemoved((previous) => [...new Set([...previous, ...paperIds])]);
      notifyTask({ id: taskId, spaceId, module: "library", title: `${targets.length} ${targets.length === 1 ? "paper" : "papers"} removed`, message: "Notes were kept.", status: "success" });
      if (alive.current) {
        try { await refreshSpace(); } catch {
          if (alive.current) setInfo("Removal succeeded, but the sidebar could not refresh. Refresh the page to sync pinned papers.");
        }
      }
    } catch (err) {
      if (!alive.current) return;
      const message = err instanceof ApiError ? err.message : "Could not remove the selected papers.";
      setError(message);
      setState((previous) => ({ ...previous, selected: [...new Set([...previous.selected, ...paperIds])] }));
      notifyTask({ id: taskId, spaceId, module: "library", title: "Paper removal failed", message, status: "error" });
    } finally {
      removingNow.current = false;
      if (alive.current) {
        setState((previous) => ({ ...previous, removing: [] }));
        setBusy(false);
      }
    }
  }

  return <section className="flex min-h-0 flex-1 flex-col" aria-label="Pinned papers">
    <h2 className="eyebrow mb-3 flex items-center justify-between">Pinned papers<span className="rounded-full bg-linen px-2 py-0.5 text-[11px] tracking-normal text-muted">{visible.length}</span></h2>
    {visible.length ? <div className="mb-3 flex flex-wrap items-center gap-2">
      <SelectAllToggle checked={allSelected(chosen, ids)} indeterminate={chosen.length > 0} disabled={!ready || busy} onToggle={() => setState((previous) => ({ ...previous, selected: toggleAll(previous.selected, ids) }))} />
      <button type="button" className="btn h-8 px-2 text-xs text-rose" disabled={!chosen.length || busy || !ready} onClick={() => void remove(chosen)}>{busy ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}Remove{chosen.length ? ` (${chosen.length})` : " selected"}</button>
    </div> : null}
    {error ? <p role="alert" className="mb-3 rounded-xl bg-rose/10 p-2 text-xs text-rose">{error}</p> : null}
    {info ? <p role="status" className="mb-3 rounded-xl bg-indigo-soft p-2 text-xs">{info}</p> : null}
    {busy ? <p role="status" className="mb-2 text-xs text-muted">{state.removing.length ? "Removing papers…" : "Awaiting confirmation…"}</p> : null}
    <div className="max-h-[29rem] min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
      {visible.length === 0 ? <p className="text-sm text-muted">Search the library or upload a PDF to pin papers into this space.</p> : visible.map((paper) => <div key={paper.id} className={cn("flex gap-2 rounded-2xl border border-line bg-white/70 p-3", !known.has(paper.id) && "animate-pin-in", chosen.includes(paper.id) && "border-indigo/40 bg-indigo-soft/40")}>
        <input type="checkbox" className="mt-1 h-4 w-4 shrink-0" checked={chosen.includes(paper.id)} disabled={!ready || busy} aria-label={`Select pinned paper ${paper.title}`} onChange={(event) => setState((previous) => ({ ...previous, selected: toggleOne(previous.selected, paper.id, event.target.checked) }))} />
        <div className="min-w-0 flex-1"><button type="button" className="line-clamp-2 text-left text-sm font-medium hover:text-indigo-deep" onClick={() => openReader({ paperId: paper.id })}>{paper.title}</button>
          <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted"><span>{paper.year ?? paper.venue ?? "Paper"}</span><button type="button" className="p-1 hover:text-rose" disabled={!ready || busy} onClick={() => void remove([paper.id])} aria-label={`Unpin ${paper.title}`}><Trash2 className="h-4 w-4" /></button></div>
        </div>
      </div>)}
    </div>
  </section>;
}
