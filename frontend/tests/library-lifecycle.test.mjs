import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import ts from "typescript";
import * as library from "../features/papers/library-state.ts";
import * as upload from "../features/papers/pdf-upload.ts";
import * as selection from "../lib/utils/selection.ts";

const require = createRequire(import.meta.url);
const event = { preventDefault() {} };
const flush = () => new Promise((resolve) => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// Render the actual component event handlers with controlled hooks and deferred APIs.
// This needs no DOM or additional renderer dependency to exercise unmount races.
async function mount(file, name, { api = {}, saved = {}, fileSelection, confirm = async () => true } = {}) {
  const effects = [];
  const notices = [];
  const updates = [];
  const polling = [];
  let refreshes = 0;
  let stateIndex = 0;
  const react = {
    useRef: (value) => ({ current: value }),
    useCallback: (callback) => callback,
    useEffect: (effect) => effects.push(effect),
    useState: (initial) => {
      const index = stateIndex++;
      let value = index === 0 && fileSelection ? fileSelection : typeof initial === "function" ? initial() : initial;
      return [value, (next) => {
        updates.push("local");
        value = typeof next === "function" ? next(value) : next;
      }];
    },
  };
  const jsx = (type, props) => ({ type, props });
  const mocks = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    "lucide-react": new Proxy({}, { get: (_target, key) => key }),
    "@/components/ui/module-layout": { EmptyInset: "EmptyInset", ModuleLayout: "ModuleLayout", PanelHeader: "PanelHeader", SelectAllToggle: "SelectAllToggle" },
    "@/features/papers/components/pdf-upload": { PdfUpload: "PdfUpload" },
    "@/features/spaces/use-workspace-state": {
      useWorkspaceState: (_space, module, initial) => {
        let state = { ...initial, ...saved };
        return [state, (next) => {
          updates.push(module);
          state = typeof next === "function" ? next(state) : next;
        }, true];
      },
    },
    "@/lib/api/client": { api: { domainTags: async () => [], ...api }, ApiError: Error },
    "@/lib/task-events": { notifyTask: (notice) => notices.push(notice) },
    "@/lib/utils": { cn: (...values) => values.filter(Boolean).join(" ") },
    "@/lib/utils/selection": selection,
    "../library-state": library,
    "@/features/papers/library-state": library,
    "@/features/papers/pdf-upload": upload,
    "../use-ingestion-polling": { useIngestionPolling: (...args) => polling.push(args) },
    "@/features/papers/use-ingestion-polling": { useIngestionPolling: (...args) => polling.push(args) },
  };
  const source = readFileSync(new URL(`../features/papers/components/${file}.tsx`, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const compiledModule = { exports: {} };
  new Function("require", "module", "exports", compiled)((key) => mocks[key] ?? require(key), compiledModule, compiledModule.exports);
  const wrapper = compiledModule.exports[name]({
    spaceId: "old-account-space", pins: [{ id: "p1", title: "Private paper" }], confirm,
    refreshSpace: async () => { refreshes++; }, openReader() {},
  });
  const tree = wrapper.type(wrapper.props);
  const cleanups = effects.map((effect) => effect());
  await flush();
  return {
    tree, notices, updates, polling, refreshes: () => refreshes,
    unmount: () => cleanups.forEach((cleanup) => { if (typeof cleanup === "function") cleanup(); }),
  };
}

function findNode(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (node.type && predicate(node)) return node;
  for (const child of Array.isArray(node) ? node : Object.values(node.props ?? {})) {
    const found = findNode(child, predicate);
    if (found) return found;
  }
  return null;
}

for (const fails of [false, true]) {
  test(`search ${fails ? "failure" : "completion"} after logout cannot update state or notify next account`, async () => {
    const request = deferred();
    const mounted = await mount("library-panel", "LibraryPanel", { saved: { query: "private query" }, api: { search: () => request.promise } });
    findNode(mounted.tree, (node) => node.type === "form").props.onSubmit(event);
    mounted.unmount();
    const writes = mounted.updates.length;
    if (fails) request.reject(new Error("private error"));
    else request.resolve({ results: [], web_results: [] });
    await flush();
    assert.equal(mounted.updates.length, writes);
    assert.deepEqual(mounted.notices, []);
    assert.equal(mounted.refreshes(), 0);
  });

  test(`pin ${fails ? "failure" : "completion"} after logout cannot leak a task`, async () => {
    const request = deferred();
    const result = { paper: { title: "Unpinned private result", source: "arxiv" } };
    const mounted = await mount("library-panel", "LibraryPanel", {
      saved: { results: [result], recent: { query: "private", includeWeb: false, count: 1, at: new Date().toISOString() } },
      api: { pinPaper: () => request.promise },
    });
    findNode(mounted.tree, (node) => node.type?.name === "SearchResultCard").props.onPin();
    mounted.unmount();
    const writes = mounted.updates.length;
    if (fails) request.reject(new Error("private error"));
    else request.resolve({ paper_id: "private-id", status: "READY" });
    await flush();
    assert.equal(mounted.updates.length, writes);
    assert.deepEqual(mounted.notices, []);
    assert.equal(mounted.refreshes(), 0);
  });

  test(`upload ${fails ? "failure" : "completion"} and progress after logout cannot mutate state or notify`, async () => {
    const request = deferred();
    let onProgress;
    const mounted = await mount("pdf-upload", "PdfUpload", {
      fileSelection: { name: "private.pdf", size: 10 },
      api: { uploadPaper: (_space, _file, _title, progress) => { onProgress = progress; return request.promise; } },
    });
    findNode(mounted.tree, (node) => node.type === "form").props.onSubmit(event);
    mounted.unmount();
    const writes = mounted.updates.length;
    onProgress(100);
    if (fails) request.reject(new Error("private error"));
    else request.resolve({ paper_id: "private-id", status: "READY" });
    await flush();
    assert.equal(mounted.updates.length, writes);
    assert.deepEqual(mounted.notices, []);
    assert.equal(mounted.refreshes(), 0);
  });

  test(`unpin ${fails ? "failure" : "completion"} after logout cannot change state or notify`, async () => {
    const request = deferred();
    const mounted = await mount("pinned-papers", "PinnedPapers", { api: { unpinPapers: () => request.promise } });
    findNode(mounted.tree, (node) => node.props["aria-label"] === "Unpin Private paper").props.onClick();
    await flush();
    mounted.unmount();
    const writes = mounted.updates.length;
    if (fails) request.reject(new Error("private error"));
    else request.resolve({});
    await flush();
    assert.equal(mounted.updates.length, writes);
    assert.deepEqual(mounted.notices, []);
    assert.equal(mounted.refreshes(), 0);
  });
}

test("confirmation resolving after logout cannot start a removal request", async () => {
  const confirmation = deferred();
  let calls = 0;
  const mounted = await mount("pinned-papers", "PinnedPapers", {
    confirm: () => confirmation.promise,
    api: { unpinPapers: async () => { calls++; } },
  });
  findNode(mounted.tree, (node) => node.props["aria-label"] === "Unpin Private paper").props.onClick();
  mounted.unmount();
  const writes = mounted.updates.length;
  confirmation.resolve(true);
  await flush();
  assert.equal(calls, 0);
  assert.equal(mounted.updates.length, writes);
  assert.deepEqual(mounted.notices, []);
});

test("bulk pin workers stop submitting queued requests after logout", async () => {
  const request = deferred();
  let calls = 0;
  const results = Array.from({ length: 6 }, (_, index) => ({ paper: { title: `private result ${index}`, source: "arxiv" } }));
  const mounted = await mount("library-panel", "LibraryPanel", {
    saved: { results, selected: results.map(({ paper }) => library.paperIdentity(paper)), recent: { query: "private", includeWeb: false, count: 6, at: new Date().toISOString() } },
    api: { pinPaper: () => { calls++; return request.promise; } },
  });
  findNode(mounted.tree, (node) => node.type === "button" && node.props.children?.includes?.("Pin selected")).props.onClick();
  assert.equal(calls, 3);
  mounted.unmount();
  const writes = mounted.updates.length;
  request.resolve({ status: "READY", paper_id: "private-id" });
  await flush();
  assert.equal(calls, 3);
  assert.equal(mounted.updates.length, writes);
  assert.deepEqual(mounted.notices, []);
  assert.equal(mounted.refreshes(), 0);
});

test("mounted successful search still updates state and emits a completion", async () => {
  const request = deferred();
  const mounted = await mount("library-panel", "LibraryPanel", { saved: { query: "research" }, api: { search: () => request.promise } });
  findNode(mounted.tree, (node) => node.type === "form").props.onSubmit(event);
  request.resolve({ results: [] });
  await flush();
  assert.equal(mounted.notices.length, 1);
  assert.equal(mounted.notices[0].status, "success");
  mounted.unmount();
});

for (const component of [
  { file: "library-panel", name: "LibraryPanel", saved: { jobs: { paper: { status: "EMBEDDING", paper_id: "p1", taskId: "private-task", title: "Private paper" } } } },
  { file: "pdf-upload", name: "PdfUpload", saved: { job: { status: "EMBEDDING", paper_id: "p1" }, taskId: "private-task" } },
]) {
  test(`${component.name} rejects late status callbacks after logout`, async () => {
    const mounted = await mount(component.file, component.name, { saved: component.saved });
    const [, onStatus, onError] = mounted.polling[0];
    mounted.unmount();
    const writes = mounted.updates.length;
    onStatus("p1", { status: "READY" });
    onError("p1", "Private error");
    await flush();
    assert.equal(mounted.updates.length, writes);
    assert.deepEqual(mounted.notices, []);
    assert.equal(mounted.refreshes(), 0);
  });
}
