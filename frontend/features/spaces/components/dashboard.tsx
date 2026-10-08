"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Archive, Copy, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react";
import { api, asList, ApiError } from "@/lib/api/client";
import type { SpaceSummary } from "@/lib/types";
import { isCurrentSpaceSnapshot } from "@/features/spaces/dashboard-state";
import { dateLabel } from "@/lib/utils";

export function Dashboard() {
  const [spaces, setSpaces] = useState<SpaceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const listRequest = useRef(0);
  const mutationVersion = useRef(0);

  async function load() {
    const request = ++listRequest.current;
    const version = mutationVersion.current;
    setLoading(true);
    setError(null);
    try {
      const response = await api.spaces();
      if (isCurrentSpaceSnapshot(request, listRequest.current, version, mutationVersion.current)) {
        setSpaces(asList(response));
      }
    } catch (err) {
      if (isCurrentSpaceSnapshot(request, listRequest.current, version, mutationVersion.current)) {
        setError(err instanceof ApiError ? err.message : "Unable to load research spaces.");
      }
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    return () => {
      listRequest.current += 1;
    };
  }, []);

  async function createSpace() {
    const trimmed = name.trim();
    if (!trimmed || loading || creating) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createSpace(trimmed);
      mutationVersion.current += 1;
      setName("");
      setSpaces((prev) => prev.some((space) => space.id === created.id) ? prev : [created, ...prev]);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Unable to create research space.");
    } finally {
      setCreating(false);
    }
  }

  async function action(space: SpaceSummary, kind: "archive" | "duplicate" | "delete" | "rename") {
    if (kind === "delete") {
      await api.deleteSpace(space.id);
      mutationVersion.current += 1;
      setSpaces((prev) => prev.filter((item) => item.id !== space.id));
      return;
    }
    if (kind === "archive") await api.archiveSpace(space.id);
    if (kind === "duplicate") await api.duplicateSpace(space.id, true, `Copy of ${space.name}`);
    if (kind === "rename") {
      const newName = window.prompt("Rename research space", space.name)?.trim();
      if (!newName) return;
      await api.renameSpace(space.id, newName);
    }
    await load();
  }

  return (
    <main className="mx-auto max-w-7xl px-5 py-8 md:px-10 md:py-12">
      <header className="mb-10 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="eyebrow mb-3">Local-first research</p>
          <h1 className="font-serif text-4xl tracking-tight text-ink md:text-6xl">Research Spaces</h1>
          <p className="mt-4 max-w-2xl text-muted">A calm desk for grounded literature search, verified answers, comparison matrices and durable notes.</p>
        </div>
      </header>

      <section className="panel mb-8 p-4 md:p-5">
        <div className="flex flex-col gap-3 md:flex-row">
          <label className="sr-only" htmlFor="space-name">New space name</label>
          <input id="space-name" className="input" value={name} disabled={loading || creating} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void createSpace(); }} placeholder="Name a new research space…" />
          <button className="btn btn-primary shrink-0" onClick={() => void createSpace()} disabled={loading || creating || !name.trim()}><Plus className="h-4 w-4" />Create space</button>
        </div>
        {createError ? <p role="alert" className="mt-3 text-sm text-rose">{createError}</p> : null}
      </section>

      {error ? <BackendDown message={error} onRetry={() => void load()} /> : null}
      {loading ? <SpaceSkeleton /> : null}
      {!loading && !error && spaces.length === 0 ? <EmptyState /> : null}
      {!loading && !error && spaces.length > 0 ? (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {spaces.map((space) => (
            <article key={space.id} className="paper-card p-6">
              <div className="flex items-start justify-between gap-4">
                <Link href={`/spaces/${space.id}`} className="group min-w-0">
                  <p className="mb-3 inline-flex rounded-full bg-indigo-soft px-3 py-1 text-xs font-medium text-indigo-deep">{space.status ?? "active"}</p>
                  <h2 className="line-clamp-2 font-serif text-2xl text-ink group-hover:text-indigo-deep">{space.name}</h2>
                </Link>
                <details className="relative">
                  <summary className="btn h-9 w-9 list-none p-0" aria-label={`Actions for ${space.name}`}><MoreHorizontal className="h-4 w-4" /></summary>
                  <div className="absolute right-0 z-10 mt-2 w-48 rounded-2xl border border-line bg-white p-2 shadow-soft">
                    <button className="w-full rounded-xl px-3 py-2 text-left text-sm hover:bg-linen" onClick={() => void action(space, "rename")}>Rename</button>
                    <button className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-linen" onClick={() => void action(space, "duplicate")}><Copy className="h-4 w-4" />Duplicate</button>
                    <button className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-linen" onClick={() => void action(space, "archive")}><Archive className="h-4 w-4" />Archive</button>
                    <button className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-rose hover:bg-rose/5" onClick={() => void action(space, "delete")}><Trash2 className="h-4 w-4" />Delete</button>
                  </div>
                </details>
              </div>
              <div className="mt-8 flex items-center justify-between text-sm text-muted">
                <span>{space.pin_count ?? space.pins?.length ?? 0} pinned papers</span>
                <span>{dateLabel(space.updated_at ?? space.created_at)}</span>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </main>
  );
}

function BackendDown({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="panel p-8 text-center"><Search className="mx-auto mb-4 h-8 w-8 text-indigo" /><h2 className="font-serif text-2xl">Backend unreachable</h2><p className="mx-auto mt-2 max-w-xl text-muted">{message}</p><button className="btn btn-primary mt-5" onClick={onRetry}>Try again</button></div>;
}
function EmptyState() {
  return <div className="panel p-10 text-center"><h2 className="font-serif text-3xl">Start your first research space</h2><p className="mx-auto mt-3 max-w-xl text-muted">Create a space to pin papers, ask grounded questions, compare findings and keep notes.</p></div>;
}
function SpaceSkeleton() {
  return <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="panel p-6"><div className="skeleton mb-5 h-7 w-24" /><div className="skeleton h-8 w-3/4" /><div className="skeleton mt-8 h-5 w-full" /></div>)}</div>;
}
