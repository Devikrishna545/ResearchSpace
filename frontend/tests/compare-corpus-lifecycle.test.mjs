import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../features/compare/components/grounded-compare.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(`${source}\nexport { CorpusCard };`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

function corpusHarness(t) {
  let cursor = 0, mounted = true, lateWrites = 0, corpusLoads = 0, tree;
  let resolve, reject;
  const response = new Promise((yes, no) => { resolve = yes; reject = no; });
  const slots = [], effects = [], notices = [];
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: initial };
      return [slots[index].value, (value) => {
        if (!mounted) { lateWrites++; return; }
        slots[index].value = typeof value === "function" ? value(slots[index].value) : value;
      }];
    },
    useRef(value) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { current: value };
      return slots[index];
    },
    useCallback(callback) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { callback };
      return slots[index].callback;
    },
    useEffect(callback) {
      const index = cursor++;
      if (!slots[index]) { slots[index] = {}; effects.push(() => { slots[index].cleanup = callback(); }); }
    },
  };
  const jsx = (type, props) => ({ type, props });
  const imports = {
    react, "react/jsx-runtime": { jsx, jsxs: jsx },
    "lucide-react": {}, "@/features/compare/grounded-report": {}, "@/lib/utils/selection": {},
    "@/lib/utils": {}, "@/features/notes/components/share-preview": {},
    "@/components/ui/module-layout": { RailCard: "RailCard" },
    "@/features/compare/use-compare": { errorText: (error) => error.message },
    "@/lib/task-events": { notifyTask: (notice) => notices.push(notice) },
    "@/lib/api/client": { api: {
      corpus: async () => { corpusLoads++; return { coverage: { size: 1 }, items: [{ id: "item", title: "Private paper" }] }; },
      addCorpusPapers: () => response, removeCorpusItem: () => response,
    } },
  };
  const compiledModule = { exports: {} };
  new Function("require", "module", "exports", compiled)((id) => {
    assert.ok(id in imports, `Unexpected import ${id}`);
    return imports[id];
  }, compiledModule, compiledModule.exports);
  function render() {
    if (!mounted) return;
    cursor = 0;
    tree = compiledModule.exports.CorpusCard({ spaceId: "old-user-space", pins: [{ id: "paper" }], ready: true, permission: "user_library", onPermissionChange() {} });
    effects.splice(0).forEach((effect) => effect());
  }
  async function flush() {
    for (let i = 0; i < 8; i++) { await Promise.resolve(); render(); }
  }
  function unmount() {
    if (!mounted) return;
    mounted = false;
    slots.forEach((slot) => slot.cleanup?.());
  }
  function findButton(node, removal) {
    if (Array.isArray(node)) return node.map((child) => findButton(child, removal)).find(Boolean);
    if (!node?.props) return undefined;
    if (node.type === "button" && Boolean(node.props["aria-label"]) === removal) return node;
    return findButton(node.props.children, removal);
  }
  render();
  t.after(unmount);
  return {
    flush, unmount, resolve, reject, notices,
    click(removal) { const button = findButton(tree, removal); assert.ok(button); button.props.onClick(); },
    get lateWrites() { return lateWrites; }, get corpusLoads() { return corpusLoads; },
  };
}

for (const action of ["add", "remove"]) {
  for (const outcome of ["success", "failure"]) {
    test(`corpus ${action} ${outcome} after logout cannot notify, refresh context or update view state`, async (t) => {
      const h = corpusHarness(t);
      await h.flush();
      h.click(action === "remove");
      h.unmount();
      if (outcome === "success") h.resolve({ added: 1, skipped_duplicates: 0 });
      else h.reject(new Error("Private request failure"));
      await h.flush();
      assert.deepEqual(h.notices, []);
      assert.equal(h.lateWrites, 0);
      assert.equal(h.corpusLoads, 1, "must not make a follow-up request under the next account");
    });
  }
}

test("mounted corpus mutations still notify and refresh normally", async (t) => {
  const h = corpusHarness(t);
  await h.flush();
  h.click(false);
  h.resolve({ added: 1, skipped_duplicates: 0 });
  await h.flush();
  assert.equal(h.notices.length, 1);
  assert.equal(h.notices[0].spaceId, "old-user-space");
  assert.equal(h.notices[0].status, "success");
  assert.equal(h.corpusLoads, 2);
});
