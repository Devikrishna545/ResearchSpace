import assert from "node:assert/strict";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { accountInitials, parseThemePreference, resolveTheme, themeBootstrapScript } from "../lib/utils/theme.ts";

function boot(saved, systemDark, storageThrows = false) {
  const document = { documentElement: { dataset: {} } };
  runInNewContext(themeBootstrapScript, {
    document,
    localStorage: { getItem: () => {
      if (storageThrows) throw new Error("Storage disabled");
      return saved;
    } },
    window: { matchMedia: () => ({ matches: systemDark }) }
  });
  return document.documentElement.dataset.theme;
}

test("theme bootstrap applies stored preference before hydration", () => {
  assert.equal(boot("dark", false), "dark");
  assert.equal(boot("light", true), "light");
  assert.equal(boot(null, true), "dark");
  assert.equal(boot(null, false), "light");
  assert.equal(boot("invalid", true), "dark");
  assert.equal(boot(null, true, true), "dark");
});

test("system theme follows OS changes while explicit choices do not", () => {
  assert.equal(parseThemePreference("unexpected"), "system");
  assert.equal(resolveTheme("system", false), "light");
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
});

test("account avatar initials derive from email without image uploads", () => {
  assert.equal(accountInitials("devikrishna.u@example.com"), "DU");
  assert.equal(accountInitials("alice@example.com"), "AL");
  assert.equal(accountInitials(""), "?");
});
