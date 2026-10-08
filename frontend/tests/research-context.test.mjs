import assert from "node:assert/strict";
import { test } from "node:test";
import { comparisonContextFindings, recentNotes } from "../features/spaces/research-context.ts";

test("shared comparison context excludes withheld findings and deduplicates by id", () => {
  const a = { finding_id: "a", display_status: "shown", statement: "Supported" };
  const b = { finding_id: "b", display_status: "shown_with_caveat", statement: "Candidate" };
  const hidden = { finding_id: "h", display_status: "withheld", statement: "Unsupported" };
  assert.deepEqual(comparisonContextFindings({ sections: { commonalities: [a, hidden], differences: [a], candidate_gaps: [b] } }), [a, b]);
  assert.deepEqual(comparisonContextFindings(null), []);
});

test("recent notes follow saved update time without mutating input", () => {
  const notes = [{ id: "older", created_at: "2025-01-01" }, { id: "newer", updated_at: "2026-10-01" }];
  assert.deepEqual(recentNotes(notes).map((n) => n.id), ["newer", "older"]);
  assert.equal(notes[0].id, "older");
});
