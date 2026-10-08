"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, BookOpen, CircleCheck, FileSearch, History, Library, LoaderCircle, RefreshCw, Share2, Sparkles, Trash2, X } from "lucide-react";
import { api } from "@/lib/api/client";
import { BASIS_LABELS, findingSources, isTerminalJob, JOB_PHASES, KIND_LABELS, NOVELTY_LABELS, phaseIndex, REPORT_SECTIONS, sourceLocation, statusMeta } from "@/features/compare/grounded-report";
import { errorText, useCompare } from "@/features/compare/use-compare";
import { notifyTask } from "@/lib/task-events";
import { allSelected, toggleAll, toggleOne } from "@/lib/utils/selection";
import type { CompareJob, CorpusResponse, EvidenceFactDTO, GroundedFinding, GroundedReport, Pin, ReaderTarget, SourceArtifact } from "@/lib/types";
import { cn, dateLabel, shortId } from "@/lib/utils";
import { SharePreview, type ShareItem } from "@/features/notes/components/share-preview";
import { ModuleLayout, PanelHeader, RailCard, SelectAllToggle } from "@/components/ui/module-layout";

const TONES = {
  emerald: "[border-color:rgb(var(--color-success-line))] [background-color:rgb(var(--color-success-bg))] [color:rgb(var(--color-success-ink))]",
  indigo: "border-indigo/20 bg-indigo-soft text-indigo-deep",
  sky: "border-sky-200 bg-sky-50 text-sky-800",
  amber: "border-amber/30 bg-amber/10 text-ink",
  muted: "border-line bg-linen text-muted",
} as const;

interface ComparePanelProps {
  spaceId: string;
  pins: Pin[];
  memorySlot?: ReactNode;
  active?: boolean;
  focusReport?: { id: string; nonce: number } | null;
  onOpenReader: (target: ReaderTarget) => void;
}

export function ComparePanel(props: ComparePanelProps) {
  return <CompareWorkspace key={props.spaceId} {...props} />;
}

function CompareWorkspace({ spaceId, pins, memorySlot, active = true, focusReport, onOpenReader }: ComparePanelProps) {
  const { state, setState, ready, job, report, previous, jobError, reportError, historyError, restoring, restoreFailed, starting, cancelling, loadingReport, visibleReportId, running, run, cancel, openReport, closeReport, loadPrevious, retryJobs } = useCompare(spaceId, pins);
  const focusedNonce = useRef<number | null>(null);
  useEffect(() => {
    if (!ready || !focusReport || focusedNonce.current === focusReport.nonce) return;
    focusedNonce.current = focusReport.nonce;
    openReport(focusReport.id);
  }, [ready, focusReport, openReport]);
  const { selected, refresh, checkNovelty } = state;
  const pinIds = pins.map((pin) => pin.id);
  const chosen = selected.filter((id) => pinIds.includes(id));
  const locked = !ready || restoring || running || starting;
  const setSelected = (value: string[]) => setState((current) => ({ ...current, selected: value, selectionInitialized: true }));
  const setPanelOpen = (id: string, open: boolean) => setState((current) => ({
    ...current, openPanels: toggleOne(current.openPanels, id, open),
  }));

  return <ModuleLayout
    header={<PanelHeader eyebrow="Synthesis" title="Compare pinned papers" text="Evidence-grounded comparison: typed facts are extracted per paper with exact page provenance, validated, compared in code where possible, and withheld when the evidence is inadequate. Runs in the background; you can leave this tab." />}
    main={<>
    <div className="panel min-w-0 max-w-full p-4 [overflow-wrap:anywhere] sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <SelectAllToggle checked={allSelected(chosen, pinIds)} indeterminate={chosen.length > 0} disabled={!pins.length || locked} onToggle={() => setSelected(toggleAll(chosen, pinIds))} />
        <span className="text-sm text-muted">{chosen.length} of {pins.length} selected{chosen.length < 2 ? " · pick at least 2" : ""}</span>
      </div>
      {pins.length === 0 ? <p className="text-sm text-muted">Pin papers in the Library to compare them.</p> : null}
      <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">{pins.map((paper) => <label key={paper.id} className={cn("flex min-w-0 items-start gap-3 rounded-2xl border border-line bg-paper p-3 transition", chosen.includes(paper.id) && "border-indigo/40 bg-indigo-soft/40")}><input type="checkbox" className="mt-1 shrink-0" disabled={locked} checked={chosen.includes(paper.id)} onChange={(e) => setSelected(toggleOne(chosen, paper.id, e.target.checked))} /><span className="min-w-0"><strong className="block">{paper.title}</strong><small className="text-muted">{paper.year ?? paper.venue ?? shortId(paper.id)}</small></span></label>)}</div>
      <div className="mt-4 flex flex-col gap-2 text-sm text-muted">
        <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 shrink-0" disabled={locked} checked={refresh} onChange={(e) => setState((current) => ({ ...current, refresh: e.target.checked }))} />Rebuild evidence from the PDFs (slower; use after re-uploading a paper)</label>
        <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 shrink-0" disabled={locked} checked={checkNovelty} onChange={(e) => setState((current) => ({ ...current, checkNovelty: e.target.checked }))} />Check candidate gaps against the literature corpus (novelty candidates)</label>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button className="btn btn-primary h-auto min-h-10 max-w-full whitespace-normal" disabled={chosen.length < 2 || locked || restoreFailed} onClick={() => void run()}><Sparkles className="h-4 w-4 shrink-0" />{starting ? "Starting comparison…" : restoring ? "Checking comparison jobs…" : "Run grounded comparison"}</button>
        {running ? <button className="btn" disabled={job?.cancel_requested || cancelling} onClick={() => void cancel()}><X className="h-4 w-4" />{job?.cancel_requested || cancelling ? "Cancelling…" : "Cancel"}</button> : null}
      </div>
      {jobError ? <div role="alert" className="mt-3 rounded-2xl border border-rose/20 bg-rose/5 p-3 text-sm text-rose">{jobError}{restoreFailed ? <button type="button" className="btn mt-2" disabled={restoring || starting} onClick={retryJobs}>Check existing jobs</button> : null}</div> : null}
    </div>
      <RailCard title="Previous reports" icon={<History className="h-5 w-5 text-indigo-deep" />}>
        {historyError ? <div role="alert" className="mb-2 text-sm text-rose [overflow-wrap:anywhere]">{historyError}<button type="button" className="btn mt-2" onClick={() => void loadPrevious()}>Retry reports</button></div> : null}
        <p className="mb-3 text-sm text-muted">Open a saved report to view it below; Close hides it again. New comparison results appear in the same place.</p>
        {previous.length === 0 ? <p className="text-sm text-muted">Reports you run appear here.</p> : <ul className="min-w-0 max-h-80 space-y-2 overflow-y-auto overscroll-contain pr-1 [overflow-wrap:anywhere]">{previous.map((item) => {
          const isOpen = visibleReportId === item.id;
          return <li key={item.id} className={cn("flex min-w-0 items-center justify-between gap-3 rounded-2xl border border-line bg-paper p-3 text-sm", isOpen && "border-indigo/40 bg-indigo-soft/40")}>
            <span className="min-w-0">{dateLabel(item.generated_at)} · {item.paper_ids.length} papers{report?.id === item.id ? <span className="mt-1 block text-xs text-indigo-deep">Viewing</span> : null}</span>
            <button type="button" className="btn" disabled={!ready} aria-expanded={isOpen} aria-label={`${isOpen ? "Close" : "Open"} report from ${dateLabel(item.generated_at)}`} onClick={() => isOpen ? closeReport() : openReport(item.id)}>{isOpen ? "Close" : "Open"}</button>
          </li>;
        })}</ul>}
      </RailCard>
      {job && (running || job.state === "failed" || job.state === "cancelled" || job.warnings.length) ? <JobProgress job={job} /> : null}
      {loadingReport ? <p role="status" className="panel flex items-center gap-2 p-5 text-sm"><LoaderCircle className="h-4 w-4 animate-spin" />Loading selected report…</p> : null}
      {reportError ? <div role="alert" className="panel p-5 text-sm text-rose [overflow-wrap:anywhere]">{reportError}{state.reportId ? <button type="button" className="btn ml-2" onClick={() => openReport(state.reportId!)}>Retry report</button> : null}</div> : null}
      {report ? <GroundedReportView key={report.id} report={report} active={active} openPanels={state.openPanels} onPanelOpen={setPanelOpen} onOpenReader={onOpenReader} /> : null}
    </>}
    aside={<>
      <CorpusCard spaceId={spaceId} pins={pins} ready={ready} permission={state.corpusPermission} onPermissionChange={(corpusPermission) => setState((current) => ({ ...current, corpusPermission }))} />
      {memorySlot}
    </>} />;
}

function JobProgress({ job }: { job: CompareJob }) {
  const current = phaseIndex(job.state);
  const novelty = Boolean(job.params?.check_novelty);
  const phases = JOB_PHASES.filter((phase) => novelty || phase.id !== "checking_novelty_optional");
  const recent = job.phase_log.slice(-6).reverse();
  const done = isTerminalJob(job);
  return <section className="panel min-w-0 max-w-full p-4 [overflow-wrap:anywhere] sm:p-5" aria-live="polite">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <h3 className="flex min-w-0 items-center gap-2 font-serif text-2xl">{done ? null : <LoaderCircle className="h-5 w-5 shrink-0 animate-spin text-indigo-deep" />}Comparison job · {job.state.replace(/_/g, " ")}</h3>
      <span className="text-sm text-muted">{Math.round(job.progress * 100)}%</span>
    </div>
    <div className="mb-4 h-2 overflow-hidden rounded-full bg-linen"><div className="h-full rounded-full bg-indigo transition-all" style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
    <ol className="mb-4 flex flex-wrap gap-2 text-xs">{phases.map((phase) => { const index = JOB_PHASES.findIndex((p) => p.id === phase.id); return <li key={phase.id} className={cn("rounded-full border px-3 py-1", index < current ? TONES.emerald : index === current && !done ? "border-indigo/30 bg-indigo-soft text-indigo-deep" : "border-line text-muted")}>{phase.label}</li>; })}</ol>
    {job.pending_sections.length ? <p className="mb-3 text-sm text-muted">Still pending: {job.pending_sections.join(", ")}.</p> : null}
    {job.error ? <p role="alert" className="mb-3 rounded-2xl border border-rose/20 bg-rose/5 p-3 text-sm text-rose">{job.error}</p> : null}
    {job.warnings.length ? <ul className="mb-3 space-y-1 rounded-2xl border border-amber/20 bg-amber/10 p-3 text-sm">{job.warnings.map((w) => <li key={w} className="flex gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber" />{w}</li>)}</ul> : null}
    <ul className="space-y-1 text-xs text-muted">{recent.map((entry, index) => <li key={`${entry.at}-${index}`}>{new Date(entry.at).toLocaleTimeString()} · {entry.message}</li>)}</ul>
  </section>;
}

function StatusBadge({ status }: { status: string }) {
  const meta = statusMeta(status);
  return <span title={meta.basis} className={cn("inline-flex max-w-full items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium [overflow-wrap:anywhere]", TONES[meta.tone])}>{meta.tone === "emerald" || meta.tone === "indigo" ? <CircleCheck className="h-3.5 w-3.5 shrink-0" /> : null}{meta.label}</span>;
}

interface ReportDisclosureState {
  openPanels: string[];
  onPanelOpen: (id: string, open: boolean) => void;
}

function ReportDetails({ id, title, children, openPanels, onPanelOpen }: ReportDisclosureState & { id: string; title: ReactNode; children: ReactNode }) {
  const open = openPanels.includes(id);
  return <details className="mb-2 min-w-0 max-w-full rounded-2xl border border-line bg-paper p-3" open={open} onToggle={(event) => {
    if (event.target === event.currentTarget && event.currentTarget.open !== open) onPanelOpen(id, event.currentTarget.open);
  }}>
    <summary className="cursor-pointer text-sm font-medium">{title}</summary>
    <div className="mt-3 max-h-[28rem] min-w-0 space-y-3 overflow-y-auto overscroll-contain pr-2 text-sm [overflow-wrap:anywhere]">{children}</div>
  </details>;
}

function GroundedReportView({ report, active, openPanels, onPanelOpen, onOpenReader }: ReportDisclosureState & { report: GroundedReport; active: boolean; onOpenReader: (target: ReaderTarget) => void }) {
  const disclosure = { openPanels, onPanelOpen };
  const [source, setSource] = useState<{ artifact: SourceArtifact; quote?: string } | null>(null);
  const [sharing, setSharing] = useState<ShareItem | null>(null);
  const openSource = useCallback((sourceId: string | null | undefined, quote?: string) => {
    const artifact = sourceId ? report.evidence_appendix[sourceId] : undefined;
    if (artifact) setSource({ artifact, quote });
  }, [report.evidence_appendix]);
  const factsById = useMemo(() => {
    const map = new Map<string, EvidenceFactDTO>();
    Object.values(report.evidence_ledger).flat().forEach((fact) => map.set(fact.fact_id, fact));
    return map;
  }, [report.evidence_ledger]);
  const labels = report.papers.map((paper) => paper.label);

  function share(finding: GroundedFinding, kind: (typeof REPORT_SECTIONS)[number]["shareKind"], index: number) {
    const titles = finding.paper_ids.map((id) => report.papers.find((p) => p.paper_id === id)?.title).filter((t): t is string => Boolean(t));
    const caveat = finding.evidence_status === "PARTIALLY_SUPPORTED" || finding.basis === "interpretation" || finding.kind === "candidate_gap"
      ? "This is a candidate or interpretive finding, not a verified conclusion. Keep its evidence label when sharing." : undefined;
    setSharing({ id: `${report.id}-${finding.finding_id}`, source: { type: "finding", id: report.id, kind, index }, kind: KIND_LABELS[finding.kind] ?? finding.kind,
      text: `${finding.statement} [${statusMeta(finding.evidence_status).label}]`, citation: titles.join("; ") || undefined, warning: caveat });
  }

  return <article className="panel min-w-0 max-w-full space-y-8 p-4 [overflow-wrap:anywhere] sm:p-5">
    <header className="space-y-3">
      <div className="flex min-w-0 flex-wrap items-center gap-3"><h3 className="font-serif text-3xl">Grounded comparison report</h3><span className="text-sm text-muted">{dateLabel(report.generated_at)}</span></div>
      <p className="rounded-2xl border border-line bg-linen p-3 text-sm text-muted">{report.release_gate}</p>
      {report.stale_warning ? <p role="status" className="rounded-2xl border border-amber/30 bg-amber/10 p-3 text-sm">{report.stale_warning}</p> : null}
      {report.warnings.length ? <ul className="space-y-1 rounded-2xl border border-amber/20 bg-amber/10 p-3 text-sm">{report.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : null}
      <div className="flex flex-wrap gap-2">{Object.keys(report.status_legend ?? {}).map((status) => <StatusBadge key={status} status={status} />)}</div>
    </header>

    <ReportSection title="Paper summaries" subtitle="Built only from validated, page-linked facts; nothing here comes from a generated profile.">
      <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">{report.papers.map((paper) => <div key={paper.paper_id} className="min-w-0 rounded-2xl border border-line bg-paper p-4 text-sm">
        <p className="font-medium">{paper.label} · {paper.title}</p>
        <p className="mt-1 text-xs text-muted">Evidence build v{paper.build.version} · {paper.build.text_source.replace(/_/g, " ")} · {paper.build.page_count || "?"} pages{paper.build.scanned ? " · scanned (OCR)" : ""} · {paper.fact_counts.validated} validated facts</p>
        {(["research_question", "method", "dataset", "metric"] as const).map((type) => <div key={type} className="mt-2"><span className="text-xs uppercase tracking-wide text-muted">{type.replace("_", " ")}</span>
          {paper.summary[type]?.length ? <ul>{paper.summary[type].map((item) => { const fact = factsById.get(item.fact_id); return <li key={item.fact_id}><FactLink label={item.value} page={item.page} onClick={() => openSource(fact?.source_ids[0], fact?.quote)} /></li>; })}</ul> : <p className="italic text-muted">Insufficient evidence</p>}
        </div>)}
      </div>)}</div>
    </ReportSection>

    <ReportSection title="Evidence ledger" subtitle="Every validated fact with its verbatim quote and page. Rejected or uncertain extractions stay in the audit record and are never compared.">
      {report.papers.map((paper) => <EvidenceLedgerBlock key={paper.paper_id} id={paper.paper_id} {...disclosure} title={`${paper.label} · ${paper.title}`} facts={report.evidence_ledger[paper.paper_id] ?? []} audit={report.audit_record[paper.paper_id] ?? []} onOpen={(fact) => openSource(fact.source_ids[0], fact.quote)} />)}
    </ReportSection>

    <ReportSection title="Deterministic comparison table" subtitle="Validated values per paper. Empty cells say why rather than being filled in.">
      <p className="mb-2 text-xs text-muted">Scroll within the table to compare all papers.</p>
      <div role="region" aria-label="Comparison matrix, scroll horizontally for more papers" tabIndex={0} className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain rounded-2xl border border-line focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo"><table style={{ width: `${12 + labels.length * 18}rem` }} className="min-w-full table-fixed divide-y divide-line text-sm"><thead className="bg-linen"><tr><th scope="col" className="w-48 px-4 py-3 text-left">Dimension</th>{labels.map((label) => <th scope="col" key={label} className="px-4 py-3 text-left">{label} · {report.paper_labels[label]}</th>)}</tr></thead>
        <tbody className="divide-y divide-line bg-white/70">{report.deterministic_table.map((row) => <tr key={row.dimension}><th scope="row" className="px-4 py-3 text-left align-top font-medium">{row.label}</th>{labels.map((label) => { const cell = row.cells[label]; return <td key={label} className="px-4 py-3 align-top">
          {cell?.status === "evidenced" ? <ul className="space-y-1">{cell.values.map((v) => <li key={v.fact_id}><FactLink label={v.value} page={v.page} onClick={() => openSource(v.source_id, factsById.get(v.fact_id)?.quote)} /></li>)}</ul>
            : cell?.status === "extraction_failed" ? <span className="text-amber" title={cell.note}>Extraction failed (not evidence of absence)</span>
            : <span className="italic text-muted">Insufficient evidence</span>}
        </td>; })}</tr>)}</tbody></table></div>
    </ReportSection>

    {REPORT_SECTIONS.map((section) => { const items = report.sections[section.key] ?? []; return <ReportSection key={section.key} title={section.title}>
      {items.length ? <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-2">{items.map((finding, index) => <FindingCard key={finding.finding_id} finding={finding} report={report} factsById={factsById} onOpenSource={openSource} onShare={() => share(finding, section.shareKind, index)} />)}</div>
        : <p className="rounded-2xl border border-dashed border-line p-4 text-sm text-muted">{section.key === "candidate_gaps" ? report.candidate_gaps_empty_reason ?? "No candidate gaps." : "Insufficient evidence: no finding in this section survived validation and verification."}</p>}
    </ReportSection>; })}

    <ReportSection title="Novelty assessment" subtitle="Two papers cannot establish novelty. Labels are relative to the searched corpus only.">
      {report.novelty?.ran && report.novelty.coverage ? <div className="space-y-2 text-sm">
        <p>Corpus searched: {report.novelty.coverage.size} items{report.novelty.coverage.year_range ? `, ${report.novelty.coverage.year_range[0]}–${report.novelty.coverage.year_range[1]}` : ""}{Object.keys(report.novelty.coverage.fields).length ? `, fields: ${Object.keys(report.novelty.coverage.fields).join(", ")}` : ""}. Permissions: {Object.entries(report.novelty.coverage.permissions).map(([k, v]) => `${k.replace(/_/g, " ")} (${v})`).join(", ") || "none"}.</p>
        {report.novelty.status === "insufficient_literature_coverage" ? <p className="text-amber">The corpus is too small for a meaningful check; every gap is labelled “Insufficient literature coverage”.</p> : null}
        <ul className="list-disc pl-5 text-muted">{report.novelty.coverage.search_limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      </div> : <p className="text-sm text-muted">{NOVELTY_LABELS.novelty_not_assessed}. {report.novelty?.reason}</p>}
    </ReportSection>

    <ReportSection title="Limitations and coverage" subtitle="What the evidence could not cover, and what was withheld.">
      <div className="space-y-3 text-sm">
        {report.papers.map((paper) => { const flags = report.coverage.papers[paper.paper_id]?.quality_flags ?? []; return flags.length ? <p key={paper.paper_id}><strong>{paper.label}</strong> extraction flags: {flags.join(", ")}</p> : null; })}
        {report.coverage.insufficient.length ? <ul className="list-disc pl-5 text-muted">{report.coverage.insufficient.map((f) => <li key={f.finding_id}>{f.statement}</li>)}</ul> : null}
        <ReportDetails id="withheld" {...disclosure} title={`${report.withheld_count} finding${report.withheld_count === 1 ? "" : "s"} withheld (unsupported or insufficient)`}>
          <ul className="mt-2 space-y-2">{report.withheld.map((f) => <li key={f.finding_id} className="text-muted"><StatusBadge status={f.evidence_status} /> {f.statement}{f.reason ? ` — ${f.reason}` : ""}</li>)}</ul>
        </ReportDetails>
      </div>
    </ReportSection>

    <ReportSection title="Evidence appendix" subtitle="Every source span cited above.">
      <ReportDetails id="appendix" {...disclosure} title={`${Object.keys(report.evidence_appendix).length} source spans`}>
        <ul className="mt-2 space-y-2 text-sm">{Object.values(report.evidence_appendix).map((a) => <li key={a.source_id}><button type="button" className="text-left text-indigo-deep hover:underline" onClick={() => setSource({ artifact: a })}>{report.papers.find((p) => p.paper_id === a.paper_id)?.label} · {sourceLocation(a)}</button><span className="text-muted"> — {a.text.slice(0, 140)}{a.text.length > 140 ? "…" : ""}</span></li>)}</ul>
      </ReportDetails>
    </ReportSection>

    <ReportDetails id="provenance" {...disclosure} title="Technical provenance (audit)">
      <p className="text-muted">Models used for extraction and verification are recorded for reproducibility, not as a guarantee of correctness. The evidence labels and source spans above remain authoritative.</p>
      {report.tier ? <dl className="space-y-1"><div><dt className="inline font-medium">Text: </dt><dd className="inline">{report.tier.text_model}</dd></div><div><dt className="inline font-medium">Vision: </dt><dd className="inline">{report.tier.vision_model}</dd></div><div><dt className="inline font-medium">Retrieval: </dt><dd className="inline">{report.tier.embed_model}</dd></div></dl> : null}
      {report.tier?.limitation_note ? <p className="text-muted">{report.tier.limitation_note}</p> : null}
      <pre className="min-w-0 max-w-full whitespace-pre-wrap rounded-xl bg-linen p-3 text-xs [overflow-wrap:anywhere]">{JSON.stringify(report.model_metadata, null, 2)}</pre>
    </ReportDetails>

    {active && source ? <EvidenceDrawer report={report} artifact={source.artifact} quote={source.quote} onClose={() => setSource(null)} onOpenReader={(target) => { setSource(null); onOpenReader(target); }} /> : null}
    {active && sharing ? <SharePreview key={sharing.id} item={sharing} onClose={() => setSharing(null)} /> : null}
  </article>;
}

function ReportSection({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return <section className="min-w-0 max-w-full"><h4 className="font-serif text-2xl">{title}</h4>{subtitle ? <p className="mb-3 mt-1 text-sm text-muted">{subtitle}</p> : <div className="mb-3" />}{children}</section>;
}

function FactLink({ label, page, onClick }: { label: string; page?: number | null; onClick: () => void }) {
  return <button type="button" className="max-w-full whitespace-normal text-left text-indigo-deep [overflow-wrap:anywhere] hover:underline" onClick={onClick}>{label}<span className="ml-1 text-xs text-muted">{page ? `p. ${page}` : "page ?"}</span></button>;
}

function FindingCard({ finding, report, factsById, onOpenSource, onShare }: { finding: GroundedFinding; report: GroundedReport; factsById: Map<string, EvidenceFactDTO>; onOpenSource: (sourceId: string, quote?: string) => void; onShare: () => void }) {
  const sources = findingSources(report, finding);
  const quoteFor = (sourceId: string) => finding.fact_ids.map((id) => factsById.get(id)).find((fact) => fact?.source_ids.includes(sourceId))?.quote;
  return <div className={cn("min-w-0 max-w-full rounded-2xl border p-4 text-sm", finding.display_status === "shown_with_caveat" ? "border-amber/30 bg-amber/5" : "border-line bg-paper")}>
    <div className="mb-2 flex flex-wrap items-center gap-2"><span className="text-xs font-semibold uppercase tracking-wide text-muted">{KIND_LABELS[finding.kind] ?? finding.kind}</span><StatusBadge status={finding.evidence_status} /><span className="text-xs text-muted">{BASIS_LABELS[finding.basis] ?? finding.basis}</span>{finding.category ? <span className="text-xs text-muted">· {finding.category.replace(/_/g, " ")}</span> : null}</div>
    <p className="whitespace-pre-wrap">{finding.statement}</p>
    {finding.reason ? <p className="mt-2 text-xs text-amber">{finding.reason}</p> : null}
    {finding.coverage_note ? <p className="mt-2 text-xs text-muted">{finding.coverage_note}</p> : null}
    {finding.novelty?.label ? <p className="mt-2 text-xs"><span className="rounded-full bg-linen px-2 py-0.5">{NOVELTY_LABELS[finding.novelty.label] ?? finding.novelty.label}</span>{finding.novelty.reason ? <span className="text-muted"> {finding.novelty.reason}</span> : null}</p> : null}
    <div className="mt-3 flex flex-wrap gap-2">{sources.map((s) => <button key={s.source_id} type="button" className="min-w-0 max-w-full whitespace-normal rounded-2xl border border-line bg-white px-2.5 py-1 text-left text-xs text-indigo-deep [overflow-wrap:anywhere] hover:border-indigo/40" onClick={() => onOpenSource(s.source_id, quoteFor(s.source_id))}><FileSearch className="mr-1 inline h-3.5 w-3.5" />{report.papers.find((p) => p.paper_id === s.paper_id)?.label} · {sourceLocation(s)}</button>)}</div>
    <button type="button" className="btn mt-3 h-auto min-h-9 max-w-full whitespace-normal px-3" onClick={onShare}><Share2 className="h-4 w-4 shrink-0" />Share this finding</button>
  </div>;
}

function EvidenceLedgerBlock({ id, title, facts, audit, openPanels, onPanelOpen, onOpen }: ReportDisclosureState & { id: string; title: string; facts: EvidenceFactDTO[]; audit: EvidenceFactDTO[]; onOpen: (fact: EvidenceFactDTO) => void }) {
  const disclosure = { openPanels, onPanelOpen };
  const grouped = facts.reduce<Record<string, EvidenceFactDTO[]>>((acc, fact) => { (acc[fact.label] ??= []).push(fact); return acc; }, {});
  return <ReportDetails id={`ledger:${id}`} {...disclosure} title={`${title} · ${facts.length} validated facts`}>
    <div className="mt-3 space-y-3 text-sm">{Object.entries(grouped).map(([label, items]) => <div key={label}><p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <ul className="space-y-1">{items.map((fact) => <li key={fact.fact_id}><button type="button" className="text-left hover:underline" onClick={() => onOpen(fact)}><strong>{fact.value}</strong> <span className="text-muted">— “{fact.quote}” ({fact.page ? `p. ${fact.page}` : "page ?"}{fact.section ? `, ${fact.section}` : ""})</span></button></li>)}</ul></div>)}
      {facts.length === 0 ? <p className="italic text-muted">Insufficient evidence: no facts passed validation.</p> : null}
      {audit.length ? <ReportDetails id={`audit:${id}`} {...disclosure} title={`Audit record: ${audit.length} rejected or uncertain extractions`}>
        <ul className="mt-2 space-y-1 text-xs text-muted">{audit.map((fact) => <li key={fact.fact_id}>{fact.label}: “{fact.value}” — {fact.extraction_status} (provenance {fact.provenance_validation}, type {fact.type_validation}, ownership {fact.ownership_validation}, dimension {fact.dimension_validation})</li>)}</ul></ReportDetails> : null}
    </div>
  </ReportDetails>;
}

function EvidenceDrawer({ report, artifact, quote, onClose, onOpenReader }: { report: GroundedReport; artifact: SourceArtifact; quote?: string; onClose: () => void; onOpenReader: (target: ReaderTarget) => void }) {
  const paper = report.papers.find((p) => p.paper_id === artifact.paper_id);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    const previous = document.activeElement;
    const panel = panelRef.current;
    panel?.querySelector<HTMLButtonElement>("button")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], [tabindex="0"]'));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
        event.preventDefault(); first?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (previous instanceof HTMLElement && previous.isConnected && previous.getClientRects().length) previous.focus();
    };
  }, []);
  const visual = artifact.quality_flags.includes("visual_extraction") || artifact.extraction_status === "candidate" || artifact.extraction_status === "ocr_candidate";
  return <div className="fixed inset-0 z-50 flex justify-end bg-ink/20 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="evidence-heading" onClick={onClose}>
    <div ref={panelRef} className="h-full min-w-0 w-full max-w-2xl overflow-y-auto overscroll-contain bg-paper p-4 shadow-card [overflow-wrap:anywhere] sm:p-6" onClick={(e) => e.stopPropagation()}>
      <div className="mb-4 flex items-start justify-between gap-3"><div className="min-w-0"><p className="eyebrow">Source evidence</p><h2 id="evidence-heading" className="font-serif text-2xl">{paper ? `${paper.label} · ${paper.title}` : artifact.paper_id}</h2><p className="mt-1 text-sm text-muted">{sourceLocation(artifact)} · {artifact.kind}</p></div><button type="button" className="btn h-10 w-10 shrink-0 p-0" onClick={onClose} aria-label="Close evidence"><X className="h-4 w-4" /></button></div>
      {visual ? <p className="mb-3 rounded-2xl border border-amber/30 bg-amber/10 p-3 text-sm">Extracted by the vision model ({artifact.extraction_status.replace(/_/g, " ")}); check it against the rendered page before relying on it.</p> : null}
      {quote ? <blockquote className="mb-4 rounded-2xl border-l-4 border-amber bg-amber/10 p-3 font-serif">“{quote}”</blockquote> : null}
      {artifact.caption ? <p className="mb-2 text-sm font-medium">{artifact.caption}</p> : null}
      {artifact.cells?.length ? <div role="region" aria-label="Source table, scroll horizontally" tabIndex={0} className="mb-4 min-w-0 max-w-full overflow-x-auto overscroll-x-contain rounded-2xl border border-line"><table style={{ width: `${Math.max(24, artifact.cells.reduce((max, row) => Math.max(max, row.length), 0) * 12)}rem` }} className="min-w-full table-fixed divide-y divide-line text-sm"><tbody>{artifact.cells.map((row, r) => <tr key={r} className={r === 0 ? "bg-linen font-medium" : ""}>{row.map((cell, c) => <td key={c} className="px-3 py-2">{cell}</td>)}</tr>)}</tbody></table></div> : null}
      {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image, not a static asset */}
      {artifact.has_image ? <img className="mb-4 w-full rounded-2xl border border-line" src={api.artifactImageUrl(artifact.source_id)} alt={`Rendered ${artifact.label ?? "page"} ${artifact.page ?? ""}`} /> : null}
      {!artifact.cells?.length ? <p className="whitespace-pre-wrap font-serif leading-7">{artifact.text}{artifact.truncated ? "…" : ""}</p> : null}
      {artifact.quality_flags.length ? <p className="mt-3 text-xs text-muted">Quality flags: {artifact.quality_flags.join(", ")}</p> : null}
      <button type="button" className="btn btn-primary mt-5 h-auto min-h-10 max-w-full whitespace-normal" onClick={() => onOpenReader({ paperId: artifact.paper_id, quote: quote ?? artifact.text.slice(0, 160), page: artifact.page ?? null })}><BookOpen className="h-4 w-4 shrink-0" />Open in paper reader</button>
    </div>
  </div>;
}

function CorpusCard({ spaceId, pins, ready, permission, onPermissionChange }: { spaceId: string; pins: Pin[]; ready: boolean; permission: string; onPermissionChange: (value: string) => void }) {
  const [corpus, setCorpus] = useState<CorpusResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const mutationLock = useRef(false);
  const request = useRef(0);
  const mounted = useRef(true);
  const load = useCallback(async () => {
    const token = ++request.current;
    setLoading(true);
    try {
      const result = await api.corpus();
      if (mounted.current && token === request.current) { setCorpus(result); setLoadError(null); }
    } catch (err) {
      if (mounted.current && token === request.current) setLoadError(`${errorText(err, "Unable to load the literature corpus.")} The displayed corpus may be out of date.`);
    } finally {
      if (mounted.current && token === request.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => { mounted.current = false; };
  }, [load]);

  async function addPins() {
    if (!mounted.current || !ready || mutationLock.current || !pins.length) return;
    mutationLock.current = true;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.addCorpusPapers(pins.map((p) => p.id), permission);
      if (!mounted.current) return;
      const message = `Added ${result.added}; ${result.skipped_duplicates} already present.`;
      notifyTask({ id: `compare-corpus:add:${crypto.randomUUID()}`, spaceId, module: "compare", title: "Literature corpus updated", message, status: "success" });
      setMessage(message);
      await load();
    } catch (err) {
      if (!mounted.current) return;
      const message = errorText(err, "Unable to add papers.");
      setError(message);
      notifyTask({ id: `compare-corpus:add:${crypto.randomUUID()}`, spaceId, module: "compare", title: "Corpus update failed", message, status: "error" });
    } finally {
      mutationLock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function removeItem(itemId: string) {
    if (!mounted.current || !ready || mutationLock.current) return;
    mutationLock.current = true;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await api.removeCorpusItem(itemId);
      if (!mounted.current) return;
      notifyTask({ id: `compare-corpus:remove:${crypto.randomUUID()}`, spaceId, module: "compare", title: "Paper removed from literature corpus", status: "success" });
      setMessage("Paper removed from the literature corpus.");
      await load();
    } catch (err) {
      if (!mounted.current) return;
      const message = errorText(err, "Unable to remove the paper. Please retry.");
      setError(message);
      notifyTask({ id: `compare-corpus:remove:${crypto.randomUUID()}`, spaceId, module: "compare", title: "Corpus removal failed", message, status: "error" });
    } finally {
      mutationLock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return <RailCard title="Literature corpus" icon={<Library className="h-5 w-5 text-indigo-deep" />}>
    <p className="text-sm text-muted">Novelty checks search only this authorized corpus. {corpus ? `${corpus.coverage.size} items${corpus.coverage.year_range ? `, ${corpus.coverage.year_range[0]}–${corpus.coverage.year_range[1]}` : ""}.` : ""}</p>
    <label className="mt-2 block text-xs text-muted">Permission for added papers
      <select className="input mt-1 min-w-0 max-w-full px-3 py-2 text-sm leading-5" disabled={!ready || busy} value={permission} onChange={(e) => onPermissionChange(e.target.value)}>
        <option value="user_library">My library (my own copies)</option><option value="user_upload">My uploads</option><option value="university_licensed">University-licensed</option><option value="open_access">Open access</option><option value="metadata_only">Metadata only</option>
      </select></label>
    <button type="button" className="btn mt-2 h-auto min-h-10 w-full min-w-0 whitespace-normal" disabled={!ready || busy || !pins.length} onClick={() => void addPins()}>{busy ? <RefreshCw className="h-4 w-4 shrink-0 animate-spin" /> : null}Add this space&apos;s pinned papers</button>
    {message ? <p role="status" className="mt-2 text-xs text-muted [overflow-wrap:anywhere]">{message}</p> : null}
    {error ? <div role="alert" className="mt-2 text-xs text-rose [overflow-wrap:anywhere]">{error}<button type="button" className="btn mt-2" disabled={busy || loading} onClick={() => void load()}>Refresh corpus</button></div> : null}
    {loadError ? <div role="alert" className="mt-2 text-xs text-rose [overflow-wrap:anywhere]">{loadError}<button type="button" className="btn mt-2" disabled={busy || loading} onClick={() => void load()}>Retry corpus</button></div> : null}
    {corpus?.items.length ? <ul className="mt-2 max-h-48 min-w-0 space-y-1 overflow-y-auto overscroll-contain pr-1 text-xs">{corpus.items.map((item) => <li key={item.id} className="flex min-w-0 items-center justify-between gap-2"><span className="min-w-0 [overflow-wrap:anywhere]">{item.title}</span><button type="button" className="shrink-0 p-2 text-rose" disabled={!ready || busy} aria-label={`Remove ${item.title} from corpus`} onClick={() => void removeItem(item.id)}><Trash2 className="h-3.5 w-3.5" /></button></li>)}</ul> : null}
  </RailCard>;
}
