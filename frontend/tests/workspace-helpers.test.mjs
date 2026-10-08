import assert from "node:assert/strict";
import { test } from "node:test";
import { findQuoteRange } from "../features/papers/quote-highlight.ts";
import { allSelected, mapWithConcurrency, toggleAll, toggleOne } from "../lib/utils/selection.ts";
import { hasMoreDetail, memoryHeadline, memoryKey } from "../features/spaces/memory-items.ts";

test("cited quotes are found despite whitespace, case and truncation", () => {
  const text = "Intro.  The   model Reduces\nhallucination by 30% on long inputs. End.";
  const range = findQuoteRange(text, "“the model reduces hallucination by 30%…”");
  assert.ok(range);
  assert.equal(text.slice(range.start, range.end), "The   model Reduces\nhallucination by 30%");
  assert.equal(findQuoteRange(text, "absent passage"), null);
  assert.equal(findQuoteRange(text, ""), null);
  assert.equal(findQuoteRange(text, null), null);
});

test("select-all toggles every visible id without dropping unrelated selections", () => {
  assert.deepEqual(toggleAll(["x"], ["a", "b"]), ["x", "a", "b"]);
  assert.deepEqual(toggleAll(["x", "a", "b"], ["a", "b"]), ["x"]);
  assert.equal(allSelected([], []), false);
  assert.equal(allSelected(["a", "b"], ["a", "b"]), true);
  assert.deepEqual(toggleOne(["a"], "b"), ["a", "b"]);
  assert.deepEqual(toggleOne(["a", "b"], "a"), ["b"]);
  assert.deepEqual(toggleOne(["a"], "a", true), ["a"]);
});

test("bounded concurrency preserves order and captures failures", async () => {
  let running = 0;
  let peak = 0;
  const results = await mapWithConcurrency([1, 2, 3, 4, 5], 2, async (n) => {
    running += 1;
    peak = Math.max(peak, running);
    await new Promise((resolve) => setTimeout(resolve, 5));
    running -= 1;
    if (n === 3) throw new Error("boom");
    return n * 10;
  });
  assert.equal(peak, 2);
  assert.deepEqual(results.map((r) => r.status === "fulfilled" ? r.value : r.reason.message), [10, 20, "boom", 40, 50]);
});

test("memory headlines show the first sentence and keys are stable", () => {
  assert.equal(memoryHeadline("Dense retrieval wins. It also scales."), "Dense retrieval wins.");
  assert.equal(hasMoreDetail("Dense retrieval wins. It also scales."), true);
  assert.equal(hasMoreDetail("Short finding"), false);
  assert.ok(memoryHeadline("x".repeat(200)).endsWith("…"));
  assert.equal(memoryKey(" Same Text "), memoryKey("same text"));
});
