import assert from "node:assert/strict";
import { test } from "node:test";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import config from "../tailwind.config.ts";

test("Tailwind scans feature sources and keeps shared source directories", () => {
  for (const directory of ["app", "features", "components", "lib"]) {
    assert.ok(config.content.includes(`./${directory}/**/*.{ts,tsx}`), `${directory} must be scanned for utility classes`);
  }
  assert.equal(config.content.some((pattern) => pattern.includes("deleted_files")), false);
});

test("feature-only utility classes survive production Tailwind generation", async () => {
  const result = await postcss([tailwindcss(config)]).process("@tailwind utilities;", { from: undefined });
  const selectors = new Set();
  result.root.walkRules((rule) => selectors.add(rule.selector));
  assert.ok(selectors.has(".z-\\[95\\]"), "legacy notification overlay keeps its feature-only stacking class");
  assert.ok(selectors.has(".text-\\[11px\\]"), "chat citations and space memory keep their small labels");
  assert.ok(selectors.has(".font-serif"), "shared typography remains available");
});
