"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { api } from "@/lib/api/client";
import { splitMentions } from "@/features/chat/chat-sessions";
import { mapCitationOccurrences } from "@/features/chat/citation-mapping";
import { withChatReadTimeout } from "@/features/chat/chat-requests";
import type { ChatResponse, Citation, ReaderTarget, Turn, VerificationTrail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ConfidenceBadge } from "./confidence-badge";

export function ChatTurn({ turn, meta, onCitation, onOpenSession }: { turn: Turn; meta?: ChatResponse; onCitation: (citation: Citation) => void; onOpenSession?: (sessionId: string) => void }) {
  const isUser = turn.role === "user";
  const verification = meta ?? turn.verification;
  const notAnswerable = !isUser && turn.content.toLowerCase().includes("not answerable from the attached papers");
  return <article className={cn("rounded-3xl p-5", isUser ? "ml-auto max-w-2xl bg-indigo text-white" : "mr-auto border border-line bg-paper")}>
    <div className="mb-3 flex flex-wrap items-center gap-2"><span className="text-xs font-semibold uppercase tracking-widest opacity-70">{isUser ? "You" : "Assistant"}</span>{!isUser && verification ? <ConfidenceBadge verified={verification.verified} confidence={verification.confidence} warning={verification.low_confidence_warning} iterations={verification.iterations} /> : null}</div>
    {notAnswerable ? <div className="mb-3 rounded-2xl border border-indigo/20 bg-white/70 p-3 text-sm text-muted">The assistant abstained because the attached evidence was insufficient.</div> : null}
    {isUser ? <UserText content={turn.content} turn={turn} onOpenSession={onOpenSession} /> : <CitationText content={turn.content} citations={turn.citations ?? []} onCitation={onCitation} />}
    {!isUser && turn.citations?.length ? <div className="mt-4 flex flex-wrap gap-2" aria-label="Answer evidence">{turn.citations.map((citation, index) => <button key={`${citation.chunk_id}-${index}`} className="btn text-xs" onClick={() => onCitation(citation)}>Evidence {index + 1}{citation.page != null ? ` · Page ${citation.page}` : ""}</button>)}</div> : null}
    {!isUser && !turn.id.startsWith("local-") ? <VerificationTrailDisclosure turnId={turn.id} /> : null}
  </article>;
}

function UserText({ content, turn, onOpenSession }: { content: string; turn: Turn; onOpenSession?: (sessionId: string) => void }) {
  return <p className="whitespace-pre-wrap">{splitMentions(content, turn.mentions ?? []).map((part, index) => part.mention
    ? <button key={index} type="button" className="mx-0.5 rounded-full bg-white/20 px-2 py-0.5 text-sm font-medium underline-offset-2 hover:underline" title="Open referenced chat" onClick={() => onOpenSession?.(part.mention!.id)}>{part.text}</button>
    : <span key={index}>{part.text}</span>)}</p>;
}

export function CitationText({ content, citations, onCitation }: { content: string; citations: Citation[]; onCitation: (citation: Citation) => void }) {
  const { parts, hits } = mapCitationOccurrences(content, citations);
  return <p className="whitespace-pre-wrap leading-7">{parts.map((part, index) => {
    const match = /^\[([^\]]+)\]$/.exec(part);
    if (!match) return <span key={`${part}-${index}`}>{part}</span>;
    const hit = hits.get(index);
    if (!hit) return <span key={`${part}-${index}`} className="text-indigo-deep">{part}</span>;
    return <button key={`${part}-${index}`} className="mx-0.5 inline-flex h-5 min-w-5 translate-y-[-0.35em] items-center justify-center rounded-full bg-indigo px-1.5 text-[11px] font-bold text-white shadow-sm" onClick={() => onCitation(hit.citation)} aria-label={`Open citation ${hit.index}`}>{hit.index}</button>;
  })}</p>;
}

export function CitationPopover({ citation, onClose, paperTitles, onOpenPaper }: { citation: Citation; onClose: () => void; paperTitles?: Map<string, string>; onOpenPaper?: (target: ReaderTarget) => void }) {
  const paperTitle = citation.paper_id ? paperTitles?.get(citation.paper_id) : undefined;
  const ordinal = /-(\d+)$/.exec(citation.chunk_id || "")?.[1];
  const facts: Array<[string, string]> = [];
  if (paperTitle || citation.paper_id) facts.push(["Paper", paperTitle ?? "Not pinned in this space"]);
  if (citation.page != null) facts.push(["Page", String(citation.page)]);
  facts.push(["Section", citation.section || "Unknown"]);
  if (ordinal) facts.push(["Passage", `#${Number(ordinal) + 1}`]);
  return <div className="fixed inset-0 z-40 bg-ink/20 p-4 backdrop-blur-sm" onClick={onClose}><aside className="ml-auto flex h-full max-w-md flex-col overflow-y-auto rounded-3xl border border-line bg-paper p-6 shadow-soft" onClick={(e) => e.stopPropagation()}>
    <button className="btn mb-5 h-10 w-10 shrink-0 p-0" onClick={onClose} aria-label="Close citation"><X className="h-4 w-4" /></button>
    <p className="eyebrow mb-2">Source passage</p>
    {paperTitle ? <h3 className="mb-3 font-serif text-xl leading-snug">{paperTitle}</h3> : null}
    <blockquote className="rounded-2xl bg-white p-4 font-serif text-lg leading-7 text-ink">
      {citation.quote ? `\u201C${citation.quote}\u201D` : <span className="text-muted">The stored passage for this citation is unavailable. It was recorded before passage capture was added.</span>}
    </blockquote>
    {citation.claim_text ? <p className="mt-3 text-sm text-muted">Cited claim: {citation.claim_text}</p> : null}
    <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">{facts.map(([label, value]) => <div key={label}><dt className="text-muted">{label}</dt><dd className="break-words">{value}</dd></div>)}</dl>
    {citation.paper_id && paperTitle && onOpenPaper ? <button className="btn btn-primary mt-5 self-start" onClick={() => { onOpenPaper({ paperId: citation.paper_id as string, chunkId: citation.chunk_id, quote: citation.quote }); onClose(); }}>Open highlighted passage in paper</button> : null}
  </aside></div>;
}

function VerificationTrailDisclosure({ turnId }: { turnId: string }) {
  const [open, setOpen] = useState(false);
  const [trail, setTrail] = useState<VerificationTrail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (!open || trail) return;
    let cancelled = false;
    setError(null);
    withChatReadTimeout(api.verification(turnId))
      .then((loaded) => { if (!cancelled && mounted.current) setTrail(loaded); })
      .catch((err: unknown) => { if (!cancelled && mounted.current) setError(err instanceof Error ? err.message : "Verification trail unavailable."); });
    return () => { cancelled = true; };
  }, [open, trail, turnId, attempt]);
  return <div className="mt-5">
    <button className="btn" aria-expanded={open} onClick={() => setOpen((v) => !v)}><ChevronDown className={cn("h-4 w-4 transition", open && "rotate-180")} />Peer review &amp; evidence</button>
    {open ? <div className="mt-4 space-y-4">
      {error ? <div><p className="text-sm text-rose">{error}</p><button className="btn mt-2" onClick={() => setAttempt((value) => value + 1)}>Retry review details</button></div> : null}
      {!trail && !error ? <div className="skeleton h-28" /> : null}
      {trail?.iterations.length === 0 ? <p className="text-sm text-muted">No peer-review records were saved for this answer.</p> : null}
      {trail?.iterations.map((iteration) => <div key={iteration.iteration} className="rounded-2xl border border-line bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2"><span className="rounded-full bg-indigo-soft px-3 py-1 text-xs font-semibold text-indigo-deep">Iteration {iteration.iteration}</span><span className="text-sm text-muted">{iteration.verdict?.verdict ?? "Reviewed"}</span><span className="text-sm text-muted">Score {iteration.verdict?.overall_score ?? "?"}</span><span className="text-sm text-muted">{iteration.latency_ms ? `${Math.round(iteration.latency_ms)}ms` : ""}</span></div>
        <p className="mb-3 text-sm text-muted">Action: {iteration.action_taken ?? "?"}</p>
        {iteration.verdict?.global_feedback ? <p className="mb-3 rounded-xl bg-linen p-3 text-sm">{iteration.verdict.global_feedback}</p> : null}
        {!iteration.verdict?.claims?.length ? <p className="text-sm text-muted">No claim-level review was completed in this iteration.</p> : null}
        <div className="space-y-2">{iteration.verdict?.claims?.map((claim) => <div key={claim.claim_id ?? claim.claim_text} className="rounded-xl border border-line p-3">
          <span className={cn("mb-2 inline-flex rounded-full px-2 py-1 text-[11px] font-bold", claim.status === "SUPPORTED" ? "bg-emerald-50 text-emerald-700" : claim.status === "PARTIAL" ? "bg-amber/10 text-amber" : "bg-rose/10 text-rose")}>{claim.status ?? "CLAIM"}</span>
          <p className="text-sm">{claim.claim_text}</p>
          {claim.evidence_quote ? <p className="mt-2 text-sm text-muted">Evidence: {claim.evidence_quote}</p> : null}
          {claim.issue ? <p className="mt-2 text-sm text-rose">{claim.issue}</p> : null}
          {claim.suggested_correction ? <p className="mt-2 text-sm text-muted">Suggested correction: {claim.suggested_correction}</p> : null}
        </div>)}</div>
        {iteration.draft_text ? <details className="mt-3 text-sm"><summary className="cursor-pointer text-muted">Reviewed draft (not the final answer)</summary><p className="mt-2 whitespace-pre-wrap">{iteration.draft_text}</p></details> : null}
      </div>)}
    </div> : null}
  </div>;
}
