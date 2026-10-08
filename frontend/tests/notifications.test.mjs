import assert from "node:assert/strict";
import { test } from "node:test";
import { legacyNoticeKey } from "../features/auth/notifications.ts";

test("the same legacy warning stays dismissed on page navigation", () => {
  const warning = { foreign_key_violations: 17, comparison_orphans: 3, message: "Review missing evidence." };
  assert.equal(legacyNoticeKey(warning), legacyNoticeKey({ ...warning }));
});

test("a changed warning can notify the user again", () => {
  const warning = { foreign_key_violations: 17, comparison_orphans: 3, message: "Review missing evidence." };
  assert.notEqual(legacyNoticeKey(warning), legacyNoticeKey({ ...warning, foreign_key_violations: 18 }));
  assert.notEqual(legacyNoticeKey(warning), legacyNoticeKey({ ...warning, message: "New finding." }));
});
