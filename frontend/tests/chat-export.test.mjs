import assert from "node:assert/strict";
import { test } from "node:test";
import { CHAT_TURNS_LIMIT, createChatExport } from "../features/chat/chat-export.ts";

const session = {
  id: "chat", space_id: "space", title: "Research: answers", pinned: true, archived: false,
  summary: "Compressed summary", summary_turn_count: 1, turn_count: 2, updated_at: "2026-01-01T00:00:00Z",
};
const turns = [
  { id: "question", role: "user", content: "Original compressed question", session_id: "chat", mentions: [{ id: "ref", title: "Earlier" }] },
  { id: "answer", role: "assistant", content: "Original answer [1]", session_id: "chat", citations: [{ chunk_id: "paper-2", paper_id: "paper", quote: "Evidence", page: 3, match_score: 0.9 }], verification: { verified: true, confidence: 0.95, iterations: 2, verification_url: "/v1/turns/answer/verification" } },
];

test("JSON exports preserve the full original conversation, summary, citations and available metadata", () => {
  const file = createChatExport(session, turns, "json", "2026-10-01T00:00:00Z");
  const data = JSON.parse(file.content);
  assert.deepEqual(data.session, session);
  assert.deepEqual(data.turns, turns);
  assert.equal(data.exported_at, "2026-10-01T00:00:00Z");
  assert.equal(file.filename, "Research- answers.json");
  assert.match(file.mime, /application\/json/);
});

test("Markdown exports include original compressed turns as well as summary and citation details", () => {
  const file = createChatExport(session, turns, "markdown", "2026-10-01T00:00:00Z");
  for (const content of ["# Research: answers", "## Summary", "Compressed summary", "Original compressed question", "Original answer [1]", '"quote": "Evidence"', '"verified": true']) {
    assert.ok(file.content.includes(content), content);
  }
  assert.ok(file.filename.endsWith(".md"));
  assert.match(file.mime, /text\/markdown/);
});

test("exports exclude failed optimistic bubbles and deduplicate saved ids", () => {
  const file = createChatExport(session, [...turns, turns[0], { id: "local-failed", role: "user", content: "Unconfirmed question" }], "json");
  assert.deepEqual(JSON.parse(file.content).turns, turns);
  assert.ok(!file.content.includes("Unconfirmed question"));
});

test("exports fail explicitly rather than silently truncating to the endpoint's maximum window", () => {
  assert.equal(CHAT_TURNS_LIMIT, 1000);
  assert.throws(() => createChatExport({ ...session, turn_count: 1001 }, turns, "markdown"), /complete export is unavailable/);
  assert.throws(() => createChatExport(session, [turns[1]], "json"), /No partial file was downloaded/);
  assert.throws(() => createChatExport(session, [{ ...turns[0], session_id: "another-chat" }, turns[1]], "json"), /do not belong/);
});

test("empty chats export and unsafe filenames and markdown metadata fences are handled", () => {
  const file = createChatExport({ ...session, turn_count: 0, title: '... /\\:*?"<>|', summary: "A ``` fenced summary" }, [], "markdown");
  assert.doesNotMatch(file.filename, /[<>:"/\\|?*]/);
  assert.ok(file.content.includes("````json"));
  assert.deepEqual(JSON.parse(createChatExport({ ...session, turn_count: 0 }, [], "json").content).turns, []);
});
