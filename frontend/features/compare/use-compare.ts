"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, asList } from "@/lib/api/client";
import type { CompareJob, ComparisonSummary, GroundedReport, Pin } from "@/lib/types";
import { notifyTask } from "@/lib/task-events";
import { useWorkspaceState } from "@/features/spaces/use-workspace-state";
import { completedReportId, comparisonTerminalNotice, initialCompareState, isCompareWorkspaceState, settledCompareState } from "./compare-state";
import { isTerminalJob } from "./grounded-report";

const POLL_MS = 1500;

export function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function useCompare(spaceId: string, pins: Pin[]) {
  const [state, setState, ready] = useWorkspaceState(spaceId, "compare", initialCompareState(pins.slice(0, 2).map((pin) => pin.id)), isCompareWorkspaceState);
  const stateRef = useRef(state);
  const [job, setJob] = useState<CompareJob | null>(null);
  const jobRef = useRef<CompareJob | null>(null);
  const [report, setReport] = useState<GroundedReport | null>(null);
  const [visibleReportId, setVisibleReportId] = useState<string | null>(null);
  const visibleReportRef = useRef<string | null>(null);
  const [previous, setPrevious] = useState<ComparisonSummary[]>([]);
  const [jobError, setJobError] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [loadingReport, setLoadingReport] = useState(false);
  const [retry, setRetry] = useState(0);
  const [pollTick, setPollTick] = useState(0);
  const startLock = useRef(false);
  const cancelLock = useRef(false);
  const requestEpoch = useRef(0);
  const reportRequest = useRef(0);
  const historyRequest = useRef(0);
  const noticedJobs = useRef(new Set<string>());

  // Refs are synchronized before async callbacks, including two clicks in one frame.
  useEffect(() => { stateRef.current = state; }, [state]);
  const updateState: typeof setState = useCallback((action) => {
    const next = typeof action === "function" ? action(stateRef.current) : action;
    stateRef.current = next;
    setState(next);
  }, [setState]);

  useEffect(() => {
    if (ready && !state.selectionInitialized && pins.length) {
      updateState((current) => ({ ...current, selected: pins.slice(0, 2).map((pin) => pin.id), selectionInitialized: true }));
    }
  }, [ready, pins, state.selectionInitialized, updateState]);

  const loadPrevious = useCallback(async () => {
    const request = ++historyRequest.current;
    const epoch = requestEpoch.current;
    try {
      const result = await api.comparisons(spaceId);
      if (request === historyRequest.current && epoch === requestEpoch.current) {
        setPrevious(asList(result));
        setHistoryError(null);
      }
    } catch (error) {
      if (request === historyRequest.current && epoch === requestEpoch.current) setHistoryError(errorText(error, "Unable to load previous reports."));
    }
  }, [spaceId]);

  const fetchReport = useCallback(async (reportId: string) => {
    const request = ++reportRequest.current;
    const epoch = requestEpoch.current;
    visibleReportRef.current = reportId;
    setVisibleReportId(reportId);
    setLoadingReport(true);
    setReportError(null);
    setReport(null);
    try {
      const result = await api.comparison(reportId);
      if (request === reportRequest.current && epoch === requestEpoch.current) setReport(result);
    } catch (error) {
      if (request === reportRequest.current && epoch === requestEpoch.current) setReportError(errorText(error, "Unable to open the report."));
    } finally {
      if (request === reportRequest.current && epoch === requestEpoch.current) setLoadingReport(false);
    }
  }, []);

  const openReport = useCallback((reportId: string) => {
    updateState((current) => ({
      ...current, reportId, pendingReportJobId: null,
      openPanels: current.reportId === reportId ? current.openPanels : [],
    }));
    void fetchReport(reportId);
  }, [fetchReport, updateState]);

  const closeReport = useCallback(() => {
    reportRequest.current += 1;
    visibleReportRef.current = null;
    setVisibleReportId(null);
    setReport(null);
    setReportError(null);
    setLoadingReport(false);
    updateState((current) => ({ ...current, pendingReportJobId: null }));
  }, [updateState]);

  const acceptJob = useCallback((next: CompareJob, observeTerminal = true) => {
    jobRef.current = next;
    setJob(next);
    const current = stateRef.current;
    const terminal = isTerminalJob(next);
    const reportId = terminal ? completedReportId(current, next) : null;
    const notice = terminal && observeTerminal && current.jobPending && current.jobId === next.id ? comparisonTerminalNotice(next) : null;
    updateState((value) => terminal ? settledCompareState(value, next) : { ...value, jobId: next.id, jobPending: true });
    if (notice && !noticedJobs.current.has(notice.id)) {
      noticedJobs.current.add(notice.id);
      notifyTask({ ...notice, spaceId, module: "compare" });
    }
    if (terminal) {
      void loadPrevious();
      if (reportId) void fetchReport(reportId);
    }
  }, [fetchReport, loadPrevious, spaceId, updateState]);

  useEffect(() => {
    if (!ready) return;
    const epoch = requestEpoch.current + 1;
    requestEpoch.current = epoch;
    let disposed = false;
    setRestoring(true);
    setRestoreFailed(false);
    setJobError(null);
    setJob(null);
    jobRef.current = null;
    void loadPrevious();
    const saved = stateRef.current;
    // Saved selections retain disclosure state, but only this visit's open view is restored on retry.
    if (visibleReportRef.current) void fetchReport(visibleReportRef.current);
    else setReport(null);

    async function restore() {
      try {
        if (saved.jobId) {
          let restored: CompareJob | null = null;
          try { restored = await api.compareJob(saved.jobId); }
          catch (error) {
            if (!(error instanceof ApiError && error.status === 404)) throw error;
            if (disposed) return;
            setJobError("The saved comparison job no longer exists. Your selected report is unchanged.");
            updateState((current) => ({ ...current, jobId: null, jobPending: false, pendingReportJobId: null }));
          }
          if (disposed) return;
          if (restored) {
            acceptJob(restored, saved.jobPending);
            if (!isTerminalJob(restored)) return;
          }
        }
        // Only discover active work. Never replace the selected report with an arbitrary historical report.
        const jobs = await api.compareJobs(spaceId);
        if (disposed) return;
        const active = jobs.find((item) => !isTerminalJob(item));
        if (active) {
          updateState((current) => ({
            ...current, jobId: active.id, jobPending: true,
            pendingReportJobId: current.reportId ? null : active.id,
          }));
          acceptJob(active, false);
        }
      } catch (error) {
        if (!disposed) {
          setRestoreFailed(true);
          setJobError(`${errorText(error, "Unable to resume comparison jobs.")} Retry checking jobs before starting another comparison.`);
        }
      } finally {
        if (!disposed) setRestoring(false);
      }
    }
    void restore();
    return () => {
      disposed = true;
      if (requestEpoch.current === epoch) requestEpoch.current = epoch + 1;
    };
  }, [ready, spaceId, retry, acceptJob, fetchReport, loadPrevious, updateState]);

  useEffect(() => {
    if (!job || isTerminalJob(job) || restoring) return;
    const epoch = requestEpoch.current;
    let disposed = false;
    const timer = window.setTimeout(async () => {
      try {
        const next = await api.compareJob(job.id);
        if (disposed || epoch !== requestEpoch.current || jobRef.current !== job || isTerminalJob(jobRef.current)) return;
        setJobError(null);
        acceptJob(next);
      } catch (error) {
        if (disposed || epoch !== requestEpoch.current || jobRef.current !== job) return;
        if (error instanceof ApiError && error.status === 404) {
          setJobError("The comparison job no longer exists (its space may have been deleted).");
          jobRef.current = null;
          setJob(null);
          updateState((current) => ({ ...current, jobId: null, jobPending: false, pendingReportJobId: null }));
          return;
        }
        setJobError(`${errorText(error, "Lost contact with the comparison job.")} Retrying automatically; the server job may still be running.`);
        setPollTick((tick) => tick + 1);
      }
    }, POLL_MS);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [job, restoring, pollTick, acceptJob, updateState]);

  async function run() {
    const current = stateRef.current;
    const chosen = current.selected.filter((id) => pins.some((pin) => pin.id === id));
    if (!ready || restoring || restoreFailed || startLock.current || (jobRef.current && !isTerminalJob(jobRef.current)) || chosen.length < 2) return;
    startLock.current = true;
    setStarting(true);
    setJobError(null);
    const epoch = requestEpoch.current;
    const selectionRequest = reportRequest.current;
    try {
      const next = await api.startCompareJob(spaceId, { paper_ids: chosen, refresh: current.refresh, check_novelty: current.checkNovelty });
      if (epoch !== requestEpoch.current) return;
      updateState((value) => ({ ...value, jobId: next.id, jobPending: true, pendingReportJobId: reportRequest.current === selectionRequest ? next.id : null }));
      acceptJob(next);
    } catch (error) {
      if (epoch !== requestEpoch.current) return;
      // A failed POST response can still have created a job. Reconcile before allowing another POST.
      setRestoreFailed(true);
      setJobError(`${errorText(error, "Unable to start the comparison.")} Check existing jobs before trying again.`);
    } finally {
      startLock.current = false;
      if (epoch === requestEpoch.current) setStarting(false);
    }
  }

  async function cancel() {
    const current = jobRef.current;
    if (!current || isTerminalJob(current) || current.cancel_requested || cancelLock.current) return;
    cancelLock.current = true;
    setCancelling(true);
    const epoch = requestEpoch.current;
    try {
      const next = await api.cancelCompareJob(current.id);
      if (epoch !== requestEpoch.current || jobRef.current?.id !== current.id || isTerminalJob(jobRef.current)) return;
      setJobError(null);
      acceptJob(next);
    } catch (error) {
      if (epoch === requestEpoch.current && jobRef.current?.id === current.id && !isTerminalJob(jobRef.current)) setJobError(errorText(error, "Unable to cancel. The job may still be running; please retry."));
    } finally {
      cancelLock.current = false;
      if (epoch === requestEpoch.current) setCancelling(false);
    }
  }

  return {
    state, setState: updateState, ready, job, report, previous, jobError, reportError, historyError,
    restoring, restoreFailed, starting, cancelling, loadingReport, visibleReportId,
    running: Boolean(job && !isTerminalJob(job)), run, cancel, openReport, closeReport, loadPrevious,
    retryJobs: () => setRetry((value) => value + 1),
  };
}
