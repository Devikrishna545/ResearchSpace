import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import ts from "typescript";
import config from "../tailwind.config.ts";

const component = readFileSync(new URL("../features/compare/components/grounded-compare.tsx", import.meta.url), "utf8");

test("previous reports and the single report viewer follow controls in the main column, not the tools rail", () => {
  const ast = ts.createSourceFile("grounded-compare.tsx", component, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let layout;
  function visit(node) {
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(ast) === "ModuleLayout") layout = node;
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(layout);
  const slots = Object.fromEntries(layout.attributes.properties.filter(ts.isJsxAttribute).map((attr) => [attr.name.getText(ast), attr.initializer.getText(ast)]));
  assert.ok(slots.main.indexOf("Run grounded comparison") < slots.main.indexOf('title="Previous reports"'));
  assert.ok(slots.main.indexOf('title="Previous reports"') < slots.main.indexOf("<GroundedReportView"));
  assert.match(slots.main, /const isOpen = visibleReportId === item\.id/);
  assert.match(slots.main, /aria-expanded=\{isOpen\}/);
  assert.match(slots.main, /onClick=\{\(\) => isOpen \? closeReport\(\) : openReport\(item\.id\)\}>\{isOpen \? "Close" : "Open"\}<\/button>/);
  assert.match(slots.main, /max-h-80[^"]*overflow-y-auto/);
  assert.equal(component.match(/<GroundedReportView\b/g).length, 1);
  assert.doesNotMatch(slots.aside, /Previous reports|GroundedReportView/);
  assert.match(slots.aside, /<CorpusCard/);
  assert.equal(slots.footer, undefined);
});

test("corpus permission control sizes to its text rather than clipping within a fixed height", async () => {
  const classes = component.match(/<select className="([^"]+)"/)?.[1];
  assert.ok(classes);
  assert.doesNotMatch(classes, /(?:^|\s)h-\d/);
  const result = await postcss([tailwindcss({ ...config, content: [{ raw: classes }] })]).process("@tailwind utilities;", { from: undefined });
  const declarations = {};
  result.root.walkDecls((declaration) => { declarations[declaration.prop] = declaration.value; });
  assert.equal(declarations["padding-top"], "0.5rem");
  assert.equal(declarations["padding-bottom"], "0.5rem");
  assert.equal(declarations["line-height"], "1.25rem");
  assert.equal(declarations.height, undefined);
});

test("compare has no tier control/card but retains technical provenance and evidence interactions", () => {
  assert.doesNotMatch(component, /title="Model tier"|api\.groundedTiers|report\.tier\??\.tier/);
  for (const label of ["Technical provenance (audit)", "Source evidence", "Share this finding", "Open in paper reader", "Literature corpus"]) {
    assert.ok(component.includes(label), `${label} remains accessible`);
  }
  assert.match(component, /active && source \? <EvidenceDrawer/);
  assert.match(component, /active && sharing \? <SharePreview/);
});

test("the comparison matrix owns horizontal scrolling instead of expanding the report", () => {
  const matrixClasses = component.match(/aria-label="Comparison matrix[^"]*"[^>]*className="([^"]*)"/)?.[1];
  assert.ok(matrixClasses);
  for (const utility of ["min-w-0", "max-w-full", "overflow-x-auto", "overscroll-x-contain"]) assert.ok(matrixClasses.includes(utility));
  assert.match(component, /table-fixed divide-y/);
  assert.match(component, /<article className="panel min-w-0 max-w-full/);
  assert.match(component, /<pre className="[^"]*whitespace-pre-wrap[^"]*\[overflow-wrap:anywhere\]/);
});

test("bounded evidence and long-token wrapping utilities compile with the installed Tailwind", async () => {
  const result = await postcss([tailwindcss({ ...config, content: [{ raw: component, extension: "tsx" }] })]).process("@tailwind utilities;", { from: undefined });
  const declarations = new Set();
  result.root.walkDecls((declaration) => declarations.add(`${declaration.prop}:${declaration.value}`));
  for (const declaration of [
    "min-width:0px", "max-width:100%", "overflow-x:auto", "overflow-y:auto",
    "overflow-wrap:anywhere", "table-layout:fixed", "max-height:28rem", "white-space:pre-wrap",
    "border-color:rgb(var(--color-success-line))",
    "background-color:rgb(var(--color-success-bg))",
    "color:rgb(var(--color-success-ink))",
  ]) assert.ok(declarations.has(declaration), `${declaration} must be generated for compare`);
});

test("evidenced badges and completed phases use semantic success colors with readable light/dark contrast", () => {
  assert.match(component, /emerald: "\[border-color:rgb\(var\(--color-success-line\)\)\] \[background-color:rgb\(var\(--color-success-bg\)\)\] \[color:rgb\(var\(--color-success-ink\)\)\]"/);
  assert.match(component, /index < current \? TONES\.emerald/);
  assert.doesNotMatch(component, /text-emerald-800/);
  const stylesheet = postcss.parse(readFileSync(new URL("../app/globals.css", import.meta.url), "utf8"));
  const luminance = (value) => value.trim().split(/\s+/).map(Number).map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  }).reduce((total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index], 0);
  for (const selector of [":root", 'html[data-theme="dark"]']) {
    const variables = {};
    stylesheet.walkRules(selector, (rule) => rule.walkDecls((declaration) => { variables[declaration.prop] = declaration.value; }));
    const background = luminance(variables["--color-success-bg"]);
    const foreground = luminance(variables["--color-success-ink"]);
    const contrast = (Math.max(background, foreground) + 0.05) / (Math.min(background, foreground) + 0.05);
    assert.ok(contrast >= 4.5, `${selector} success badge contrast must meet WCAG AA for small text`);
  }
});
