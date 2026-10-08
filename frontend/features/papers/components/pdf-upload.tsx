"use client";

import { DragEvent, FormEvent, useEffect, useRef, useState } from "react";
import { FileUp, LoaderCircle } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { initialUploadState, isUploadState, pdfUploadError, recoverUploadState, type UploadState } from "@/features/papers/pdf-upload";
import { isIngestionTerminal, terminalNotice } from "@/features/papers/library-state";
import { useIngestionPolling } from "@/features/papers/use-ingestion-polling";
import { useWorkspaceState } from "@/features/spaces/use-workspace-state";
import { notifyTask } from "@/lib/task-events";
import type { IngestJob } from "@/lib/types";
import { cn } from "@/lib/utils";

type PdfUploadProps = {
  spaceId: string;
  refreshSpace: () => Promise<void>;
  openReader: (paperId: string) => void;
};

export function PdfUpload(props: PdfUploadProps) {
  return <PdfUploadForm key={props.spaceId} {...props} />;
}

function PdfUploadForm({ spaceId, refreshSpace, openReader }: PdfUploadProps) {
  const [state, setState, ready] = useWorkspaceState<UploadState>(spaceId, "library-upload", initialUploadState, isUploadState);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const recovered = useRef(false);
  const submitting = useRef(false);
  const notified = useRef(new Set<string>());
  const alive = useRef(false);
  const { title, job, error } = state;
  const indexing = Boolean(job && !isIngestionTerminal(job.status));
  const busy = state.uploading || indexing;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    if (!ready || recovered.current) return;
    recovered.current = true;
    queueMicrotask(() => { if (alive.current) setState(recoverUploadState); });
  }, [ready, setState]);

  function announce(result: IngestJob, taskId: string) {
    if (!alive.current || !isIngestionTerminal(result.status) || notified.current.has(taskId)) return;
    notified.current.add(taskId);
    const label = result.status === "READY" ? "PDF ready to read and cite" : result.status === "DEGRADED" ? "PDF uploaded with limited text" : "PDF indexing failed";
    notifyTask({ id: taskId, spaceId, module: "library", title: label, message: result.message ?? undefined, status: terminalNotice(result.status) });
  }

  async function refresh() {
    if (!alive.current) return;
    try { await refreshSpace(); } catch {
      if (alive.current) setState((previous) => ({ ...previous, info: "The upload was received, but pinned papers could not be refreshed. Refresh the page to sync the sidebar." }));
    }
  }

  useIngestionPolling(ready && indexing && job ? [job.paper_id] : [], (_paperId, response) => {
    if (!alive.current || !job) return;
    const updated = { ...job, status: response.status, message: response.message ?? job.message };
    setState((previous) => ({ ...previous, job: updated }));
    setPollError(null);
    if (isIngestionTerminal(updated.status)) {
      if (state.taskId) announce(updated, state.taskId);
      void refresh();
    }
  }, (_paperId, message) => { if (alive.current) setPollError(message); });

  function selectFile(value: File | null) {
    if (!ready || busy) return;
    setState((previous) => ({ ...previous, error: value ? pdfUploadError(value) : null, job: null, fileName: value?.name ?? "", info: null, taskId: null }));
    setFile(value);
    setPollError(null);
    setProgress(0);
  }

  function drop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files[0] ?? null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!alive.current || !ready || !file || busy || submitting.current) return;
    const invalid = pdfUploadError(file);
    if (invalid) { setState((previous) => ({ ...previous, error: invalid })); return; }
    submitting.current = true;
    const taskId = `upload:${spaceId}:${crypto.randomUUID()}`;
    setState((previous) => ({ ...previous, uploading: true, error: null, info: null, job: null, taskId }));
    setProgress(0);
    setPollError(null);
    try {
      const response = await api.uploadPaper(spaceId, file, title, (percent) => { if (alive.current) setProgress(percent); });
      if (!alive.current) return;
      const result = { ...response, status: response.status.toUpperCase() };
      setState((previous) => ({ ...previous, uploading: false, job: { paper_id: result.paper_id, status: result.status, message: result.message } }));
      announce(result, taskId);
      await refresh();
    } catch (err) {
      if (!alive.current) return;
      const message = err instanceof ApiError ? err.message : "Unable to upload this PDF.";
      setState((previous) => ({ ...previous, uploading: false, error: message, info: "Upload was not confirmed. Check pinned papers before retrying." }));
      notifyTask({ id: taskId, spaceId, module: "library", title: "PDF upload failed", message, status: "error" });
    } finally {
      submitting.current = false;
    }
  }

  return <form className="panel space-y-4 p-5" onSubmit={(event) => void submit(event)}>
    <div className="flex items-start gap-3">
      <div className="rounded-2xl bg-indigo-soft p-3 text-indigo-deep"><FileUp className="h-5 w-5" /></div>
      <div><h3 className="font-serif text-xl">Upload your PDF</h3><p className="mt-1 text-sm text-muted">Add a PDF you already have to this space. Text pages become searchable and citable; scans need OCR.</p></div>
    </div>
    <label className={cn("block rounded-2xl border-2 border-dashed p-5 text-sm transition", dragging ? "border-indigo bg-indigo-soft" : "border-line bg-paper/60") }
      onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)} onDrop={drop}>
      <span className="font-medium">Choose a PDF or drop it here</span><span className="ml-2 text-muted">Up to 30 MB</span>
      <input className="mt-3 block w-full text-sm file:mr-3 file:rounded-full file:border-0 file:bg-indigo-soft file:px-3 file:py-2 file:text-indigo-deep" type="file" accept=".pdf,application/pdf" disabled={!ready || busy} onChange={(event) => selectFile(event.target.files?.[0] ?? null)} />
      {file ? <span className="mt-2 block break-all text-muted">{file.name}</span> : null}
    </label>
    <label className="block text-sm font-medium">Paper title <span className="font-normal text-muted">(optional)</span>
      <input className="input mt-2" value={title} maxLength={300} disabled={!ready || busy} onChange={(event) => setState((previous) => ({ ...previous, title: event.target.value }))} placeholder="Use PDF metadata or filename" />
    </label>
    <div className="flex flex-wrap items-center gap-3">
      <button className="btn btn-primary" disabled={!ready || !file || busy || Boolean(file && pdfUploadError(file))}>{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}{state.uploading ? "Uploading…" : indexing ? "Indexing…" : "Upload and index"}</button>
      {state.uploading ? <span role="status" className="text-sm text-muted">{progress < 100 ? `Uploading ${progress}%` : "Upload sent; waiting for indexing confirmation…"} </span> : null}
      {job?.status === "READY" ? <button type="button" className="btn" onClick={() => openReader(job.paper_id)}>Open in reader</button> : null}
    </div>
    {state.uploading ? <div role="progressbar" aria-label="PDF upload progress" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} className="h-2 overflow-hidden rounded-full bg-linen"><div className="h-full rounded-full bg-indigo transition-all" style={{ width: `${progress}%` }} /></div> : null}
    {error ? <p role="alert" className="text-sm text-rose">{error}</p> : null}
    {state.info ? <p role="status" className="text-sm text-muted">{state.info}</p> : null}
    {pollError ? <p role="alert" className="text-sm text-amber">{pollError}</p> : null}
    {job ? <p role={job.status === "FAILED" ? "alert" : "status"} className={cn("text-sm", job.status === "FAILED" ? "text-rose" : job.status === "DEGRADED" ? "text-amber" : "text-ink")}>{job.status === "READY" ? "Ready to read and cite. " : job.status === "DEGRADED" ? "Uploaded with limited searchable text. " : job.status === "FAILED" ? "Indexing failed. " : `Indexing in progress (${job.status.toLowerCase()}). `}{job.message}</p> : null}
  </form>;
}
