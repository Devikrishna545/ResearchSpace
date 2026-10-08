import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import * as compareState from "../features/compare/compare-state.ts";
import * as reportHelpers from "../features/compare/grounded-report.ts";

const source = readFileSync(new URL("../features/compare/use-compare.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function job(id, state = "comparing", report_id = null) {
  return { id, state, report_id, space_id: "space", progress: 0.5, params: {}, phase_log: [], warnings: [], pending_sections: [], cancel_requested: false };
}

// A deterministic hook scheduler lets tests order server responses and timers without a DOM or real requests.
function harness(t, { saved = compareState.initialCompareState(["a", "b"]), api: overrides = {} } = {}) {
  let cursor = 0, dirty = true, current, effects = [], timerId = 0, mounted = true;
  const slots = [], timers = new Map(), notices = [], reports = [];
  const api = {
    comparisons: async () => [],
    compareJobs: async () => [],
    compareJob: async (id) => job(id),
    comparison: async (id) => { reports.push(id); return { id }; },
    startCompareJob: async () => job("new"),
    cancelCompareJob: async (id) => job(id, "cancelled"),
    ...overrides,
  };
  const sameDeps = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!slots[index]) {
        slots[index] = { value: typeof initial === "function" ? initial() : initial };
        slots[index].set = (action) => {
          assert.equal(mounted, true, "late requests must not update state after unmount");
          const value = typeof action === "function" ? action(slots[index].value) : action;
          if (!Object.is(value, slots[index].value)) { slots[index].value = value; dirty = true; }
        };
      }
      return [slots[index].value, slots[index].set];
    },
    useRef(value) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { current: value };
      return slots[index];
    },
    useCallback(callback, deps) {
      const index = cursor++;
      if (!slots[index] || !sameDeps(slots[index].deps, deps)) slots[index] = { value: callback, deps };
      return slots[index].value;
    },
    useEffect(callback, deps) {
      const index = cursor++;
      if (!slots[index] || !sameDeps(slots[index].deps, deps)) {
        const cleanup = slots[index]?.cleanup;
        slots[index] = { deps };
        effects.push(() => { cleanup?.(); slots[index].cleanup = callback(); });
      }
    },
  };
  const oldWindow = globalThis.window;
  globalThis.window = {
    setTimeout(callback) { const id = ++timerId; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  const compiledModule = { exports: {} };
  const imports = {
    react, "./compare-state": compareState, "./grounded-report": reportHelpers,
    "@/lib/task-events": { notifyTask: (notice) => notices.push(notice) },
    "@/lib/api/client": { api, asList: (value) => value, ApiError: class ApiError extends Error {} },
    "@/features/spaces/use-workspace-state": {
      useWorkspaceState(_space, _module, _initial, validate) {
        assert.equal(validate(saved), true);
        return [...react.useState(saved), true];
      },
    },
  };
  new Function("require", "module", "exports", compiled)((id) => {
    assert.ok(id in imports, `Unexpected import ${id}`);
    return imports[id];
  }, compiledModule, compiledModule.exports);
  function render() {
    if (!mounted) return;
    let loops = 0;
    while (dirty) {
      assert.ok(loops++ < 30, "Hook render loop");
      dirty = false;
      cursor = 0;
      current = compiledModule.exports.useCompare("space", [{ id: "a" }, { id: "b" }]);
      const pending = effects;
      effects = [];
      pending.forEach((effect) => effect());
    }
  }
  async function flush() {
    for (let i = 0; i < 8; i++) { render(); await Promise.resolve(); }
    render();
  }
  function unmount() {
    if (!mounted) return;
    mounted = false;
    slots.forEach((slot) => slot?.cleanup?.());
  }
  t.after(() => {
    unmount();
    if (oldWindow === undefined) delete globalThis.window;
    else globalThis.window = oldWindow;
  });
  render();
  return {
    get current() { return current; }, notices, reports, flush, unmount,
    async poll() {
      assert.ok(timers.size > 0, "A live job should keep polling even without visibility input");
      const [id, callback] = timers.entries().next().value;
      timers.delete(id);
      await callback();
      await flush();
    },
  };
}

test("reload keeps saved reports closed until explicitly opened, without duplicate notices", async (t) => {
  const h = harness(t, {
    saved: { ...compareState.initialCompareState(["a", "b"]), jobId: "old-job", reportId: "selected" },
    api: { compareJob: async () => job("old-job", "completed", "arbitrary-old-report") },
  });
  await h.flush();
  assert.equal(h.current.report, null);
  assert.equal(h.current.visibleReportId, null);
  assert.deepEqual(h.reports, []);
  h.current.openReport("selected");
  await h.flush();
  assert.equal(h.current.report.id, "selected");
  assert.equal(h.current.visibleReportId, "selected");
  assert.deepEqual(h.reports, ["selected"]);
  assert.deepEqual(h.notices, []);
});

test("an opened report can close and reopen, and job reconciliation respects its visibility", async (t) => {
  const h = harness(t);
  await h.flush();
  h.current.openReport("selected");
  await h.flush();
  h.current.retryJobs();
  await h.flush();
  assert.equal(h.current.report.id, "selected");
  h.current.closeReport();
  await h.flush();
  h.current.retryJobs();
  await h.flush();
  assert.equal(h.current.visibleReportId, null);
  assert.equal(h.current.report, null);
  assert.deepEqual(h.reports, ["selected", "selected"]);
  h.current.openReport("selected");
  await h.flush();
  assert.equal(h.current.visibleReportId, "selected");
  assert.equal(h.current.report.id, "selected");
});

for (const outcome of ["success", "failure"]) {
  test(`closing while loading ignores the report's late ${outcome}`, async (t) => {
    const response = deferred();
    const h = harness(t, { api: { comparison: () => response.promise } });
    await h.flush();
    h.current.openReport("selected");
    await h.flush();
    assert.equal(h.current.loadingReport, true);
    h.current.closeReport();
    await h.flush();
    assert.equal(h.current.loadingReport, false);
    if (outcome === "success") response.resolve({ id: "selected" });
    else response.reject(new Error("Report unavailable"));
    await h.flush();
    assert.equal(h.current.visibleReportId, null);
    assert.equal(h.current.report, null);
    assert.equal(h.current.reportError, null);
  });
}

test("closing during a run stays closed on completion, while a subsequent run can show its result", async (t) => {
  const h = harness(t, { api: { compareJob: async () => job("new", "completed", "new-result") } });
  await h.flush();
  h.current.openReport("selected");
  await h.flush();
  await h.current.run();
  await h.flush();
  h.current.closeReport();
  await h.flush();
  await h.poll();
  assert.equal(h.current.visibleReportId, null);
  assert.equal(h.current.report, null);
  assert.deepEqual(h.reports, ["selected"]);
  await h.current.run();
  await h.flush();
  await h.poll();
  assert.equal(h.current.visibleReportId, "new-result");
  assert.equal(h.current.report.id, "new-result");
});

test("closing while a start response is pending prevents that result from reopening the viewer", async (t) => {
  const start = deferred();
  const h = harness(t, { api: { startCompareJob: () => start.promise } });
  await h.flush();
  h.current.openReport("selected");
  await h.flush();
  const starting = h.current.run();
  h.current.closeReport();
  start.resolve(job("new", "completed", "new-result"));
  await starting;
  await h.flush();
  assert.equal(h.current.visibleReportId, null);
  assert.equal(h.current.report, null);
  assert.deepEqual(h.reports, ["selected"]);
});

test("a running saved job polls, opens its result and notifies exactly once", async (t) => {
  let calls = 0;
  const h = harness(t, {
    saved: { ...compareState.initialCompareState(["a", "b"]), jobId: "live", jobPending: true, pendingReportJobId: "live" },
    api: { compareJob: async () => job("live", ++calls > 1 ? "completed_with_warnings" : "comparing", calls > 1 ? "result" : null) },
  });
  await h.flush();
  assert.equal(h.current.running, true);
  await h.poll();
  assert.equal(h.current.report.id, "result");
  assert.equal(h.current.state.jobPending, false);
  assert.equal(h.notices.length, 1);
  assert.equal(h.notices[0].id, "compare-job:live:terminal");
  h.current.retryJobs();
  await h.flush();
  assert.equal(h.notices.length, 1);
});

test("a historical selection made during a live job survives completion", async (t) => {
  let calls = 0;
  const h = harness(t, { api: {
    compareJobs: async () => [job("live")],
    compareJob: async () => { calls++; return job("live", "completed", "new-result"); },
  } });
  await h.flush();
  h.current.openReport("historical");
  await h.flush();
  await h.poll();
  assert.equal(calls, 1);
  assert.equal(h.current.report.id, "historical");
  assert.deepEqual(h.reports, ["historical"]);
  assert.equal(h.notices.length, 1);
});

test("history stays closed until Open, then a new run replaces that report with its completed result", async (t) => {
  let completed = false;
  const previous = { id: "previous-report", paper_ids: ["a", "b"] };
  const newest = { id: "new-result", paper_ids: ["a", "b"] };
  const h = harness(t, { api: {
    comparisons: async () => completed ? [newest, previous] : [previous],
    compareJob: async () => { completed = true; return job("new", "completed", "new-result"); },
  } });
  await h.flush();
  assert.deepEqual(h.current.previous, [previous]);
  assert.equal(h.current.report, null);
  assert.deepEqual(h.reports, []);
  h.current.openReport(previous.id);
  await h.flush();
  assert.equal(h.current.report.id, previous.id);
  await h.current.run();
  await h.flush();
  await h.poll();
  assert.equal(h.current.state.reportId, newest.id);
  assert.equal(h.current.report.id, newest.id);
  assert.deepEqual(h.current.previous, [newest, previous]);
  assert.deepEqual(h.reports, [previous.id, newest.id]);
  h.current.openReport(previous.id);
  await h.flush();
  assert.equal(h.current.report.id, previous.id);
});

test("out-of-order report responses never overwrite the latest selection", async (t) => {
  const first = deferred(), second = deferred();
  const h = harness(t, { api: { comparison: (id) => id === "first" ? first.promise : second.promise } });
  await h.flush();
  h.current.openReport("first");
  h.current.openReport("second");
  second.resolve({ id: "second" });
  await h.flush();
  first.resolve({ id: "first" });
  await h.flush();
  assert.equal(h.current.report.id, "second");
  assert.equal(h.current.state.reportId, "second");
});

test("double clicks send one unchanged compare request and cancellation emits one terminal notice", async (t) => {
  const start = deferred(), requests = [];
  const h = harness(t, { api: { startCompareJob: (spaceId, body) => { requests.push({ spaceId, body }); return start.promise; } } });
  await h.flush();
  const first = h.current.run();
  const second = h.current.run();
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0], { spaceId: "space", body: { paper_ids: ["a", "b"], refresh: false, check_novelty: false } });
  start.resolve(job("new"));
  await Promise.all([first, second]);
  await h.flush();
  await h.current.cancel();
  await h.flush();
  assert.equal(h.current.job.state, "cancelled");
  assert.equal(h.notices.length, 1);
  assert.equal(h.notices[0].status, "info");
});

test("uncertain start failures require reconciliation before another POST", async (t) => {
  let starts = 0, checks = 0;
  const h = harness(t, { api: {
    compareJobs: async () => ++checks > 1 ? [job("accepted-despite-network-error")] : [],
    startCompareJob: async () => { starts++; throw new Error("Connection lost"); },
  } });
  await h.flush();
  await h.current.run();
  await h.flush();
  assert.equal(h.current.restoreFailed, true);
  assert.match(h.current.jobError, /Check existing jobs/);
  await h.current.run();
  assert.equal(starts, 1);
  h.current.retryJobs();
  await h.flush();
  assert.equal(h.current.job.id, "accepted-despite-network-error");
  assert.equal(h.current.running, true);
});

test("a report chosen while the start request is in flight is not replaced by its result", async (t) => {
  const start = deferred();
  const h = harness(t, { api: { startCompareJob: () => start.promise, compareJob: async () => job("new", "completed", "new-result") } });
  await h.flush();
  const running = h.current.run();
  h.current.openReport("selected");
  await h.flush();
  start.resolve(job("new"));
  await running;
  await h.flush();
  await h.poll();
  assert.equal(h.current.report.id, "selected");
  assert.deepEqual(h.reports, ["selected"]);
});

test("an older in-flight poll cannot resurrect a cancelled job", async (t) => {
  const response = deferred();
  const h = harness(t, { api: { compareJobs: async () => [job("live")], compareJob: () => response.promise } });
  await h.flush();
  const polling = h.poll();
  await h.current.cancel();
  await h.flush();
  response.resolve(job("live"));
  await polling;
  assert.equal(h.current.job.state, "cancelled");
  assert.equal(h.current.running, false);
  assert.equal(h.notices.length, 1);
});

test("job recovery errors block duplicate work until checking succeeds", async (t) => {
  let starts = 0;
  const h = harness(t, { api: {
    compareJobs: async () => { throw new Error("Offline"); },
    startCompareJob: async () => { starts++; return job("new"); },
  } });
  await h.flush();
  assert.equal(h.current.restoreFailed, true);
  await h.current.run();
  assert.equal(starts, 0);
  assert.match(h.current.jobError, /Retry checking jobs/);
});

test("transient polling failures remain explicit and recover without restarting work", async (t) => {
  let calls = 0;
  const h = harness(t, { api: {
    compareJobs: async () => [job("live")],
    compareJob: async () => { if (++calls === 1) throw new Error("Offline"); return job("live", "failed"); },
  } });
  await h.flush();
  await h.poll();
  assert.match(h.current.jobError, /Retrying automatically/);
  assert.equal(h.current.running, true);
  await h.poll();
  assert.equal(h.current.job.state, "failed");
  assert.equal(h.notices[0].status, "error");
});

test("late comparison start responses cannot publish or save state after account unmount", async (t) => {
  const response = deferred();
  const h = harness(t, { api: { startCompareJob: () => response.promise } });
  await h.flush();
  const starting = h.current.run();
  h.unmount();
  response.resolve(job("new", "completed", "private-result"));
  await starting;
  assert.deepEqual(h.notices, []);
  assert.deepEqual(h.reports, []);
});

test("late polling responses cannot publish or restore reports after account unmount", async (t) => {
  const response = deferred();
  const h = harness(t, { api: { compareJobs: async () => [job("live")], compareJob: () => response.promise } });
  await h.flush();
  const polling = h.poll();
  h.unmount();
  response.resolve(job("live", "completed", "private-result"));
  await polling;
  assert.deepEqual(h.notices, []);
  assert.deepEqual(h.reports, []);
});

test("late cancellation responses cannot publish after account unmount", async (t) => {
  const response = deferred();
  const h = harness(t, { api: { compareJobs: async () => [job("live")], cancelCompareJob: () => response.promise } });
  await h.flush();
  const cancelling = h.current.cancel();
  h.unmount();
  response.resolve(job("live", "cancelled"));
  await cancelling;
  assert.deepEqual(h.notices, []);
});

test("late report and history responses cannot update state after account unmount", async (t) => {
  const history = deferred(), report = deferred();
  const h = harness(t, { api: { comparisons: () => history.promise, comparison: () => report.promise } });
  await h.flush();
  h.current.openReport("private-report");
  h.unmount();
  history.resolve([{ id: "private-report" }]);
  report.resolve({ id: "private-report" });
  await h.flush();
  assert.deepEqual(h.notices, []);
});
