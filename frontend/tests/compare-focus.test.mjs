import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import { initialCompareState } from "../features/compare/compare-state.ts";

test("context report requests wait for restore readiness and run once per focus nonce", () => {
  const source = readFileSync(new URL("../features/compare/components/grounded-compare.tsx", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const opened = [], effects = [], focusRef = { current: null };
  let ready = false;
  const openReport = (id) => opened.push(id);
  const jsx = (type, props) => ({ type, props });
  const imports = {
    react: { useRef: () => focusRef, useEffect: (effect) => effects.push(effect) },
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    "lucide-react": {},
    "@/lib/api/client": {},
    "@/features/compare/grounded-report": {},
    "@/features/compare/use-compare": {
      useCompare: () => ({
        ready, state: initialCompareState(), setState() {}, previous: [], openReport,
      }),
    },
    "@/lib/task-events": {},
    "@/lib/utils/selection": { allSelected: () => false },
    "@/lib/types": {},
    "@/lib/utils": {},
    "@/features/notes/components/share-preview": {},
    "@/components/ui/module-layout": {},
  };
  const compiledModule = { exports: {} };
  new Function("require", "module", "exports", compiled)((id) => {
    assert.ok(id in imports, `Unexpected import ${id}`);
    return imports[id];
  }, compiledModule, compiledModule.exports);
  function render(focusReport) {
    const workspace = compiledModule.exports.ComparePanel({ spaceId: "space", pins: [], focusReport, onOpenReader() {} });
    workspace.type(workspace.props);
    effects.splice(0).forEach((effect) => effect());
  }
  render({ id: "latest", nonce: 0 });
  assert.deepEqual(opened, [], "hydration must not discard saved selection before state is ready");
  ready = true;
  render({ id: "latest", nonce: 0 });
  render({ id: "latest", nonce: 0 });
  assert.deepEqual(opened, ["latest"], "ordinary rerenders must not reload the report");
  render({ id: "latest", nonce: 1 });
  assert.deepEqual(opened, ["latest", "latest"], "a fresh click on the same report opens it again");
  render({ id: "another-report", nonce: 2 });
  render(null);
  render(undefined);
  assert.deepEqual(opened, ["latest", "latest", "another-report"]);
});
