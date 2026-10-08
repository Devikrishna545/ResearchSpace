import assert from "node:assert/strict";
import { test } from "node:test";
import { draftKey, getDraft, initialChatState, isChatWorkspaceState, optimisticQuestion, reconcileQuestion, updateDraft } from "../features/chat/chat-state.ts";
import { withChatReadTimeout } from "../features/chat/chat-requests.ts";

const request = (extra = {}) => ({
  id: "request-1", sessionId: "chat-a", text: "Compare @Earlier", mentions: [{ id: "ref", title: "Earlier" }],
  since: 1_000, baselineCount: 2, baselineLastId: "old-answer", status: "unknown", ...extra,
});
const user = (id, extra = {}) => ({ id, role: "user", content: "Compare @Earlier", mentions: [{ id: "ref", title: "Earlier" }], ...extra });
const answer = (id) => ({ id, role: "assistant", content: "Supported answer", citations: [] });
const previous = [user("old-question"), answer("old-answer")];

test("drafts and mentions stay independent for each session and the new-chat draft", () => {
  let state = updateDraft(initialChatState, "chat-a", { text: "Compare @Earlier", mentions: [{ id: "ref", title: "Earlier" }] });
  state = updateDraft(state, "chat-b", { text: "Different question" });
  state = updateDraft(state, null, { text: "New topic" });
  state = updateDraft(state, "new", { text: "A server id named new" });
  assert.equal(getDraft(state, "chat-a").text, "Compare @Earlier");
  assert.deepEqual(getDraft(state, "chat-b").mentions, []);
  assert.equal(getDraft(state, null).text, "New topic");
  assert.equal(getDraft(state, "new").text, "A server id named new");
  assert.notEqual(draftKey(null), draftKey("new"));
  assert.deepEqual(initialChatState.drafts, {});
});

test("reload validation keeps selection, filters, expansion and request metadata without saved history", () => {
  const state = {
    ...updateDraft(initialChatState, "chat-a", { text: "Follow-up draft" }),
    selected: true, activeId: "chat-a", view: "archived", query: "retrieval", showFull: { "chat-a": true }, pending: request(),
  };
  const restored = JSON.parse(JSON.stringify(state));
  assert.equal(isChatWorkspaceState(restored), true);
  assert.deepEqual(restored, state);
  assert.equal("turns" in restored, false);
  assert.equal("turnsBySession" in restored, false);
  assert.equal(getDraft(restored, "chat-b").text, "");
});

test("invalid restored state and incomplete request records are rejected", () => {
  for (const bad of [
    null, [], {}, { ...initialChatState, version: 2 }, { ...initialChatState, drafts: { "chat-a": { text: "" } } },
    { ...initialChatState, showFull: { a: "true" } }, { ...initialChatState, pending: { id: "missing-fields" } },
    { ...initialChatState, pending: request({ since: NaN }) }, { ...initialChatState, pending: request({ baselineCount: -1 }) },
    { ...initialChatState, pending: request({ mentions: [{ title: "missing-id" }] }) },
    { ...initialChatState, view: ["active"] }, { ...initialChatState, pending: request({ status: ["pending"] }) },
  ]) assert.equal(isChatWorkspaceState(bad), false);
});

test("a question is visible before session creation, and its timestamp and mentions survive reload", () => {
  const pending = request({ sessionId: null, status: "creating", baselineCount: 0, baselineLastId: null });
  const restored = JSON.parse(JSON.stringify({ ...initialChatState, pending }));
  assert.equal(isChatWorkspaceState(restored), true);
  assert.deepEqual(optimisticQuestion(restored.pending), {
    id: "local-request-1", role: "user", content: "Compare @Earlier", mentions: pending.mentions,
    citations: [], session_id: null, created_at: "1970-01-01T00:00:01.000Z",
  });
});

test("reconciliation never treats an old identical question and answer as this request", () => {
  assert.deepEqual(reconcileQuestion(request(), previous, 2), { status: "missing" });
  assert.deepEqual(reconcileQuestion(request(), [...previous, user("new-question")], 3), { status: "saved", userTurnId: "new-question" });
  assert.deepEqual(reconcileQuestion(request(), [...previous, user("new-question"), answer("new-answer")], 4), {
    status: "answered", userTurnId: "new-question", assistantTurnId: "new-answer",
  });
});

test("saved ids and window offsets reconcile a limited history without duplicate optimistic bubbles", () => {
  assert.equal(reconcileQuestion(request({ baselineLastId: "not-loaded", baselineCount: 10 }), [user("new-question"), answer("new-answer")], 12).status, "answered");
  assert.equal(reconcileQuestion(request({ baselineLastId: null, baselineCount: 0 }), previous, 1002).status, "missing");
  assert.deepEqual(reconcileQuestion(request({ userTurnId: "known", baselineCount: 99 }), [user("known"), answer("next")], 100), {
    status: "answered", userTurnId: "known", assistantTurnId: "next",
  });
  assert.equal(reconcileQuestion(request({ responseTurnId: "known-answer" }), [answer("known-answer")], 5000).status, "answered");
});

test("reconciliation matches mention identities and will not take another question's answer", () => {
  assert.equal(reconcileQuestion(request(), [...previous, user("wrong-ref", { mentions: [] }), answer("wrong-answer")], 4).status, "missing");
  assert.deepEqual(reconcileQuestion(request(), [...previous, user("ours"), user("different", { content: "Another question" }), answer("theirs")], 5), {
    status: "saved", userTurnId: "ours",
  });
});

test("unsaved optimistic bubbles cannot resolve their own request", () => {
  const pending = request();
  assert.equal(reconcileQuestion(pending, [...previous, optimisticQuestion(pending)], 2).status, "missing");
  assert.equal(reconcileQuestion(pending, previous, 2).status, "missing");
});

test("read-only recovery checks have a deadline and preserve failures instead of claiming success", async () => {
  assert.equal(await withChatReadTimeout(Promise.resolve("saved"), 100), "saved");
  await assert.rejects(withChatReadTimeout(Promise.reject(new Error("Backend offline")), 100), /Backend offline/);
  await assert.rejects(withChatReadTimeout(new Promise(() => {}), 5), /timed out/);
});
