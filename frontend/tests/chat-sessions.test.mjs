import assert from "node:assert/strict";
import { test } from "node:test";
import { activeMentionQuery, canCompress, insertMention, neighborSession, presentMentions, sortSessions, splitMentions, summarizedCount } from "../features/chat/chat-sessions.ts";

const session = (id, extra = {}) => ({ id, space_id: "s", title: id, pinned: false, archived: false, summary: null, summary_turn_count: 0, turn_count: 0, ...extra });

test("sessions sort pinned first then by recent activity and arrows stop at the ends", () => {
  const sorted = sortSessions([
    session("old", { updated_at: "2026-01-01T00:00:00Z" }),
    session("new", { updated_at: "2026-03-01T00:00:00Z" }),
    session("pinned", { pinned: true, updated_at: "2025-01-01T00:00:00Z" }),
  ]);
  assert.deepEqual(sorted.map((s) => s.id), ["pinned", "new", "old"]);
  assert.equal(neighborSession(sorted, "new", -1), "pinned");
  assert.equal(neighborSession(sorted, "new", 1), "old");
  assert.equal(neighborSession(sorted, "old", 1), null);
  assert.equal(neighborSession(sorted, "pinned", -1), null);
  assert.equal(neighborSession(sorted, null, 1), "pinned");
  assert.equal(neighborSession([], "x", 1), null);
});

test("mention queries open only after a word boundary and insert a full title", () => {
  assert.deepEqual(activeMentionQuery("Compare @Spa", 12), { start: 8, query: "Spa" });
  assert.deepEqual(activeMentionQuery("@", 1), { start: 0, query: "" });
  assert.equal(activeMentionQuery("mail me@example", 15), null);
  assert.equal(activeMentionQuery("@first\nline", 11), null);
  assert.equal(activeMentionQuery("no mention", 10), null);
  const inserted = insertMention("Compare @Spa with dense", 8, 12, "Sparse retrieval");
  assert.equal(inserted.text, "Compare @Sparse retrieval with dense");
  assert.equal(inserted.caret, "Compare @Sparse retrieval ".length);
});

test("only mentions still present in the draft are sent, and rendering links them", () => {
  const mentions = [{ id: "a", title: "Sparse" }, { id: "b", title: "Sparse retrieval" }, { id: "a", title: "Sparse" }, { id: "c", title: "Gone" }];
  assert.deepEqual(presentMentions("See @Sparse retrieval", mentions).map((m) => m.id), ["a", "b"]);
  const parts = splitMentions("See @Sparse retrieval and @Sparse.", mentions);
  assert.deepEqual(parts.map((p) => [p.text, p.mention?.id ?? null]), [["See ", null], ["@Sparse retrieval", "b"], [" and ", null], ["@Sparse", "a"], [".", null]]);
  assert.deepEqual(splitMentions("plain"), [{ text: "plain" }]);
});

test("compression hides summarised turns relative to the loaded window", () => {
  const turns = Array.from({ length: 10 }, (_, i) => ({ id: String(i), role: "user", content: "" }));
  assert.equal(summarizedCount(session("s", { summary: "x", summary_turn_count: 8, turn_count: 10 }), turns), 8);
  assert.equal(summarizedCount(session("s", { summary: "x", summary_turn_count: 8, turn_count: 14 }), turns), 4);
  assert.equal(summarizedCount(session("s", { summary: null, summary_turn_count: 8, turn_count: 10 }), turns), 0);
  assert.equal(canCompress(session("s", { turn_count: 7 })), false);
  assert.equal(canCompress(session("s", { turn_count: 8 })), true);
  assert.equal(canCompress(session("s", { turn_count: 12, summary: "x", summary_turn_count: 8 })), false);
  assert.equal(canCompress(session("s", { turn_count: 13, summary: "x", summary_turn_count: 8 })), true);
});
