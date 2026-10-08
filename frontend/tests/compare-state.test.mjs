import assert from "node:assert/strict";
import { test } from "node:test";
import { completedReportId, comparisonTerminalNotice, initialCompareState, isCompareWorkspaceState, settledCompareState } from "../features/compare/compare-state.ts";

test("compare state round-trips only bounded controls, report/job identifiers and disclosures", () => {
  const state = {
    ...initialCompareState(["paper-a", "paper-b"]),
    refresh: true, checkNovelty: true, reportId: "chosen-report", jobId: "running-job",
    jobPending: true, pendingReportJobId: "running-job", openPanels: ["ledger:paper-a", "appendix"],
    corpusPermission: "open_access",
  };
  assert.equal(isCompareWorkspaceState(JSON.parse(JSON.stringify(state))), true);
  assert.equal(isCompareWorkspaceState(initialCompareState()), true);
  assert.ok(JSON.stringify(state).length < 1024);
});

test("compare state rejects corrupt values, unknown versions, oversized lists and full artifacts", () => {
  const initial = initialCompareState();
  for (const value of [
    null, [], true, {}, { ...initial, version: 2 }, { ...initial, selected: ["duplicate", "duplicate"] },
    { ...initial, selected: [4] }, { ...initial, selected: [""] }, { ...initial, reportId: {} },
    { ...initial, refresh: "false" }, { ...initial, jobPending: true }, { ...initial, openPanels: [null] },
    { ...initial, reportId: "x".repeat(513) }, { ...initial, corpusPermission: "unapproved" },
    { ...initial, selected: Array.from({ length: 1001 }, (_, i) => `paper-${i}`) },
    { ...initial, report: { evidence_appendix: { huge: "artifact content" } } },
    { ...initial, pendingReportJobId: "unknown-job" },
    { ...initial, jobId: "one", jobPending: true, pendingReportJobId: "two" },
  ]) assert.equal(isCompareWorkspaceState(value), false, JSON.stringify(value).slice(0, 100));
});

test("completion follows the pending job, not an arbitrary historical report", () => {
  const initial = initialCompareState(["p1", "p2"]);
  const pending = { ...initial, reportId: "old", jobId: "j1", jobPending: true, pendingReportJobId: "j1", openPanels: ["appendix"] };
  const completed = { id: "j1", state: "completed", report_id: "new" };
  assert.equal(completedReportId(pending, completed), "new");
  assert.equal(completedReportId(pending, { ...completed, id: "other" }), null);
  assert.equal(completedReportId(pending, { ...completed, state: "failed" }), null);
  assert.equal(completedReportId(pending, { ...completed, state: "cancelled" }), null);
  assert.equal(completedReportId(pending, { ...completed, state: "completed_with_warnings" }), "new");
  assert.equal(completedReportId({ ...pending, pendingReportJobId: null }, completed), null);
  assert.equal(completedReportId(initial, completed), null);
  assert.deepEqual(settledCompareState(pending, completed), {
    ...pending, reportId: "new", jobPending: false, pendingReportJobId: null, openPanels: [],
  });
});

test("historical selections and their disclosure state survive background completion and reload", () => {
  const selected = { ...initialCompareState(), reportId: "selected-history", jobId: "j1", jobPending: true, openPanels: ["withheld"] };
  const terminal = { id: "j1", state: "completed", report_id: "new" };
  const settled = settledCompareState(selected, terminal);
  assert.equal(settled.reportId, "selected-history");
  assert.deepEqual(settled.openPanels, ["withheld"]);
  assert.equal(settled.jobPending, false, "historical terminal reloads must not emit completion again");
  assert.equal(completedReportId(settled, terminal), null);
  assert.equal(isCompareWorkspaceState(settled), true);
});

test("failed and cancelled work retains the selected report but releases pending work", () => {
  for (const state of ["failed", "cancelled"]) {
    const current = { ...initialCompareState(), reportId: "selected", jobId: "j1", jobPending: true, pendingReportJobId: "j1" };
    const next = settledCompareState(current, { id: "j1", state });
    assert.equal(next.reportId, "selected");
    assert.equal(next.jobPending, false);
    assert.equal(next.pendingReportJobId, null);
    assert.equal(isCompareWorkspaceState(next), true);
  }
});

test("terminal notifications have stable per-job identity and honest success/error/cancellation states", () => {
  const base = { id: "j1", warnings: [] };
  assert.equal(comparisonTerminalNotice({ ...base, state: "comparing" }), null);
  const success = comparisonTerminalNotice({ ...base, state: "completed" });
  const warning = comparisonTerminalNotice({ ...base, state: "completed_with_warnings", warnings: ["limited corpus"] });
  const failure = comparisonTerminalNotice({ ...base, state: "failed", error: "PDF unavailable" });
  const cancelled = comparisonTerminalNotice({ ...base, state: "cancelled" });
  assert.equal(success.status, "success");
  assert.equal(warning.message, "limited corpus");
  assert.equal(failure.status, "error");
  assert.equal(failure.message, "PDF unavailable");
  assert.equal(cancelled.status, "info");
  assert.equal(new Set([success.id, warning.id, failure.id, cancelled.id]).size, 1);
  assert.notEqual(comparisonTerminalNotice({ ...base, id: "j2", state: "completed" }).id, success.id);
});
