import assert from "node:assert/strict";
import { test } from "node:test";
import {
  SEARCH_HISTORY_LIMIT, TERMINAL_JOB_LIMIT, appendSearchHistory, clearRecentSearch, compactResults,
  defaultFilters, filterResults, initialLibraryState, isIngestionTerminal, isLibraryState, isPollingJob,
  paperIdentity, paperIsPinned, pruneJobs, queryTags, readIngestionStatus, recoverLibraryState, scholarUrl,
  terminalNotice, toggleQueryTag,
} from "../features/papers/library-state.ts";

const result = (title, year, authors, source = "openalex", score = 0) => ({ paper: { title, year, authors, source }, score });
const results = [
  result("API first", 2021, ["Zoe Zed"], "openalex", 0.1),
  result("API second", 2024, ["amy Able", "Co Author"], "arxiv", 0.9),
  result("Unknown metadata", null, [], "web", 1),
  result("API fourth", 2018, ["Ben Brown"], "openalex", 0.5),
  result("API fifth", 2024, ["amy Able"], "arxiv", 0.2),
];
const titles = (rows) => rows.map(({ paper }) => paper.title);
const job = (status, extra = {}) => ({ status, taskId: "task", title: "Paper", ...extra });

test("relevance preserves provider order rather than sorting by score", () => {
  const before = JSON.stringify(results);
  assert.deepEqual(titles(filterResults(results, defaultFilters)), titles(results));
  filterResults(results, { ...defaultFilters, sort: "oldest" });
  assert.equal(JSON.stringify(results), before);
});

test("year sorts place missing years last and retain API ordering for ties", () => {
  assert.deepEqual(titles(filterResults(results, { ...defaultFilters, sort: "newest" })), ["API second", "API fifth", "API first", "API fourth", "Unknown metadata"]);
  assert.deepEqual(titles(filterResults(results, { ...defaultFilters, sort: "oldest" })), ["API fourth", "API first", "API second", "API fifth", "Unknown metadata"]);
});

test("author sorting is case insensitive and missing authors sort last", () => {
  assert.deepEqual(titles(filterResults(results, { ...defaultFilters, sort: "authors" })), ["API fifth", "API second", "API fourth", "API first", "Unknown metadata"]);
});

test("author, year, and source filters intersect without changing fetched data", () => {
  const filters = { ...defaultFilters, author: "  CO AUTHOR ", year: "2024", source: "arxiv" };
  assert.deepEqual(titles(filterResults(results, filters)), ["API second"]);
  assert.deepEqual(titles(filterResults(results, { ...defaultFilters, year: "unknown" })), ["Unknown metadata"]);
  assert.equal(filterResults(results, { ...filters, source: "web" }).length, 0);
  assert.equal(results.length, 5);
});

test("compact persistence strips provider payloads without limiting API results", () => {
  const input = Array.from({ length: 150 }, (_, index) => ({
    paper: { source: "arxiv", title: `Paper ${index}`, authors: ["Author"], abstract: "Abstract", doi: `doi-${index}`, raw_payload: { huge: "x".repeat(10000) } },
    score: index, rank_explanation: "Provider rank",
  }));
  const compacted = compactResults(input);
  assert.equal(compacted.length, 150);
  assert.equal("raw_payload" in compacted[0].paper, false);
  assert.equal(compacted[0].paper.abstract, "Abstract");
  assert.equal(compacted[0].rank_explanation, "Provider rank");
  assert.ok(JSON.stringify(compacted).length < JSON.stringify(input).length / 10);
});

test("search history stores only bounded query metadata and refreshes duplicates", () => {
  let history = [];
  for (let index = 0; index < 12; index++) history = appendSearchHistory(history, { query: `query ${index}`, includeWeb: false, at: new Date().toISOString(), count: index });
  assert.equal(history.length, SEARCH_HISTORY_LIMIT);
  const repeated = { ...history[2], at: new Date().toISOString() };
  history = appendSearchHistory(history, repeated);
  assert.deepEqual(history[0], repeated);
  assert.equal(history.filter((entry) => entry.query === repeated.query).length, 1);
  assert.equal("results" in history[0], false);
});

test("clearing recent search does not remove ingestion jobs or mutate input", () => {
  const original = { ...initialLibraryState, results, webResults: [results[2]], jobs: { a: job("EMBEDDING", { paper_id: "paper" }) }, selected: ["a"], history: [{ query: "q", includeWeb: true, at: new Date().toISOString(), count: 5 }], recent: { query: "q", includeWeb: false, at: new Date().toISOString(), count: 5 } };
  const cleared = clearRecentSearch(original);
  assert.deepEqual(cleared.results, []);
  assert.deepEqual(cleared.webResults, []);
  assert.deepEqual(cleared.history, []);
  assert.deepEqual(cleared.selected, []);
  assert.equal(cleared.recent, null);
  assert.equal(cleared.jobs, original.jobs);
  assert.equal(original.results.length, 5);
  assert.match(cleared.info, /Pinned papers.*unchanged/);
});

test("reload recovery stops unresumable requests but keeps known server jobs polling", () => {
  const recovered = recoverLibraryState({ ...initialLibraryState, searching: true, jobs: { unsent: job("PINNING"), known: job("PINNING", { paper_id: "known" }), queued: job("EMBEDDING", { paper_id: "queued" }) } });
  assert.equal(recovered.searching, false);
  assert.equal(recovered.jobs.unsent.status, "INTERRUPTED");
  assert.equal(isPollingJob(recovered.jobs.unsent), false);
  assert.equal(isPollingJob(recovered.jobs.known), true);
  assert.equal(isPollingJob(recovered.jobs.queued), true);
  assert.match(recovered.info, /before a request was confirmed/);
});

test("status request network errors never turn into FAILED ingestion outcomes", async () => {
  const failedPoll = await readIngestionStatus("p1", async () => { throw new Error("offline"); });
  assert.equal(failedPoll.response, undefined);
  assert.match(failedPoll.error, /retrying.*offline/);
  const pending = job("EMBEDDING", { paper_id: "p1", pollError: failedPoll.error });
  assert.equal(isPollingJob(pending), true);
  const recoveredPoll = await readIngestionStatus("p1", async () => ({ status: "ready" }));
  assert.equal(recoveredPoll.response.status, "READY");
  assert.equal(recoveredPoll.error, undefined);
  const actualFailure = await readIngestionStatus("p1", async () => ({ status: "FAILED" }));
  assert.equal(actualFailure.response.status, "FAILED");
});

test("only actual ingestion terminal states end polling with appropriate outcomes", () => {
  for (const status of ["QUEUED", "FETCHING", "PARSING", "CHUNKING", "EMBEDDING", "PROFILING"]) {
    assert.equal(isIngestionTerminal(status), false);
    assert.equal(isPollingJob(job(status, { paper_id: "p" })), true);
  }
  for (const status of ["READY", "DEGRADED", "FAILED"]) assert.equal(isPollingJob(job(status, { paper_id: "p" })), false);
  assert.equal(terminalNotice("READY"), "success");
  assert.equal(terminalNotice("DEGRADED"), "info");
  assert.equal(terminalNotice("FAILED"), "error");
  assert.equal(terminalNotice("failed"), "error");
  assert.equal(isIngestionTerminal("ready"), true);
});

test("finished pin history is bounded without dropping active work", () => {
  const jobs = Object.fromEntries(Array.from({ length: TERMINAL_JOB_LIMIT + 20 }, (_, index) => [String(index), job("READY")]));
  jobs.active = job("EMBEDDING", { paper_id: "active" });
  jobs.saving = job("PINNING");
  const pruned = pruneJobs(jobs);
  assert.equal(Object.keys(pruned).length, TERMINAL_JOB_LIMIT + 2);
  assert.equal(pruned.active.status, "EMBEDDING");
  assert.equal(pruned.saving.status, "PINNING");
});

test("persisted state validates nested discovery metadata before rendering", () => {
  const valid = JSON.parse(JSON.stringify({ ...initialLibraryState, results: compactResults(results), jobs: { p: job("QUEUED", { paper_id: "id" }) } }));
  assert.equal(isLibraryState(valid), true);
  assert.equal(isLibraryState({ ...valid, results: [{ paper: { title: 5 } }] }), false);
  assert.equal(isLibraryState({ ...valid, results: [{ paper: { title: "t", source: "s", authors: [5] } }] }), false);
  assert.equal(isLibraryState({ ...valid, results: [{ paper: { title: "t", source: "s", raw_payload: {} } }] }), false);
  assert.equal(isLibraryState({ ...valid, filters: { ...defaultFilters, sort: "random" } }), false);
  assert.equal(isLibraryState({ ...valid, jobs: { p: { status: "QUEUED" } } }), false);
  assert.equal(isLibraryState({ ...valid, history: [null] }), false);
});

test("pin identity and server tracking support scholarly identifiers and saved web titles", () => {
  assert.equal(paperIdentity({ source: "arxiv", title: "A", doi: "ABC" }), paperIdentity({ source: "openalex", title: "B", doi: "abc" }));
  assert.equal(paperIsPinned({ source: "arxiv", title: "New title", doi: "ABC" }, [{ id: "p", title: "Original", doi: "abc" }]), true);
  assert.equal(paperIsPinned({ source: "web", title: " Web title " }, [{ id: "p", title: "web title" }]), true);
  assert.equal(paperIsPinned({ source: "web", title: "Changed title" }, [{ id: "p", title: "original" }], job("READY", { paper_id: "p" })), true);
});

test("domain tags toggle safely and Scholar links exclude domain syntax", () => {
  assert.deepEqual(queryTags("#ML #ml retrieval #ai"), ["#ml", "#ai"]);
  assert.equal(toggleQueryTag("#ml retrieval", "#ml"), "retrieval");
  assert.equal(toggleQueryTag("retrieval", "#ml"), "#ml retrieval");
  assert.equal(toggleQueryTag("retrieval", "#[bad"), "retrieval");
  assert.equal(new URL(scholarUrl("#ml retrieval augmentation")).searchParams.get("q"), "retrieval augmentation");
});
