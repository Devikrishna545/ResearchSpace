import assert from "node:assert/strict";
import { test } from "node:test";
import { findingSources, isTerminalJob, phaseIndex, sourceLocation, statusMeta } from "../features/compare/grounded-report.ts";

test("job terminal states and phase ordering", () => {
  assert.equal(isTerminalJob({ state: "completed_with_warnings" }), true);
  assert.equal(isTerminalJob({ state: "verifying_findings" }), false);
  assert.ok(phaseIndex("comparing") > phaseIndex("validating_facts"));
  assert.equal(phaseIndex("failed"), 11);
});

test("finding sources resolve only through the evidence appendix", () => {
  const source = { source_id: "s1", paper_id: "p", kind: "table", page: 7, section: "Results", label: "Table 2", text: "", extraction_status: "parsed", quality_flags: [] };
  const report = { evidence_appendix: { s1: source } };
  assert.deepEqual(findingSources(report, { source_ids: ["s1", "missing"] }), [source]);
  assert.equal(sourceLocation(source), "Table 2 · p. 7 · Results");
  assert.equal(sourceLocation({ kind: "text", page: null, section: null, label: null }), "page unknown");
});

test("unknown statuses never render as verified", () => {
  assert.equal(statusMeta("DIRECTLY_EVIDENCED").label, "Directly evidenced");
  assert.equal(statusMeta("SOMETHING_NEW").tone, "muted");
});
