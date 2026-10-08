import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createNotificationState,
  hasLegacyIssues,
  isWorkspaceTask,
  legacyWarningSummary,
  notificationReducer,
  notificationStorageKey,
  NOTIFICATION_LIMIT,
  readNotificationHistory,
  serializeNotificationHistory,
  unreadNotificationCount,
} from "../features/auth/notifications.ts";

const userId = "member-1";
const warning = { foreign_key_violations: 17, comparison_orphans: 3, message: "Review missing evidence." };
const task = { id: "task-1", spaceId: "space-1", module: "library", title: "Paper uploaded", status: "success", createdAt: 100 };
const reduce = (state, action) => notificationReducer(state, { userId, ...action });
const initial = () => reduce(createNotificationState(userId), { type: "restore", serialized: null });

test("current warning summary omits resolved categories and handles singular counts", () => {
  assert.equal(legacyWarningSummary({ ...warning, foreign_key_violations: 1, comparison_orphans: 0 }), "1 broken reference.");
  assert.equal(legacyWarningSummary({ ...warning, foreign_key_violations: 0, comparison_orphans: 1 }), "1 comparison with missing papers.");
  assert.equal(legacyWarningSummary(warning), "17 broken references and 3 comparisons with missing papers.");
});

test("live warning replaces stale restored counts instead of keeping both", () => {
  const saved = serializeNotificationHistory(reduce(initial(), { type: "warning", warning }));
  let state = reduce(createNotificationState(userId), { type: "restore", serialized: saved });
  const current = { ...warning, foreign_key_violations: 1, comparison_orphans: 0 };
  state = reduce(state, { type: "warning", warning: current });
  assert.equal(state.items.length, 1);
  assert.deepEqual(state.items[0].warning, current);
});

test("zero-count and absent warnings do not create issues or unread badges", () => {
  for (const value of [null, undefined, { ...warning, foreign_key_violations: 0, comparison_orphans: 0 }]) {
    assert.equal(hasLegacyIssues(value), false);
    const state = reduce(initial(), { type: "warning", warning: value });
    assert.equal(state.items.length, 0);
    assert.equal(unreadNotificationCount(state), 0);
    assert.equal(state.toastId, null);
  }
  assert.equal(hasLegacyIssues({ ...warning, comparison_orphans: 0 }), true);
  assert.equal(hasLegacyIssues({ ...warning, foreign_key_violations: 0 }), true);
});

test("maintenance retains the actual warning without producing a legacy toast", () => {
  const state = reduce(initial(), { type: "warning", warning });
  assert.equal(unreadNotificationCount(state), 1);
  assert.deepEqual(state.items[0].warning, warning);
  assert.equal(state.toastId, null);
});

test("opening marks warning read and does not revive unread state on rerender or restore", () => {
  let state = reduce(initial(), { type: "warning", warning });
  state = reduce(state, { type: "open" });
  assert.equal(unreadNotificationCount(state), 0);
  state = reduce(state, { type: "close" });
  assert.equal(reduce(state, { type: "warning", warning: { ...warning } }), state);
  const saved = serializeNotificationHistory(state);
  const restored = reduce(createNotificationState(userId), { type: "restore", serialized: saved });
  assert.equal(unreadNotificationCount(reduce(restored, { type: "warning", warning })), 0);
  assert.equal(restored.open, false);
  assert.equal(restored.toastId, null);
});

test("dismissed maintenance stays hidden on navigation without claiming the data was repaired", () => {
  let state = reduce(initial(), { type: "warning", warning });
  state = reduce(state, { type: "dismiss", id: state.items[0].id });
  const saved = serializeNotificationHistory(state);
  state = reduce(createNotificationState(userId), { type: "restore", serialized: saved });
  state = reduce(state, { type: "warning", warning });
  assert.equal(state.items[0].dismissed, true);
  assert.equal(state.items[0].read, true);
  assert.deepEqual(state.items[0].warning, warning);
  assert.equal(unreadNotificationCount(state), 0);
  state = reduce(state, { type: "warning", warning: { ...warning, comparison_orphans: 4 } });
  assert.equal(state.items.length, 1);
  assert.equal(state.items[0].dismissed, false);
  assert.equal(unreadNotificationCount(state), 1);
});

test("a cleared warning is removed while task history remains", () => {
  let state = reduce(initial(), { type: "warning", warning });
  state = reduce(state, { type: "task", task });
  state = reduce(state, { type: "warning", warning: { ...warning, foreign_key_violations: 0, comparison_orphans: 0 } });
  assert.equal(state.items.length, 1);
  assert.equal(state.items[0].kind, "task");
});

test("task completions notify without maintenance and deduplicate by terminal event id", () => {
  const state = reduce(initial(), { type: "task", task });
  assert.equal(state.items.length, 1);
  assert.equal(unreadNotificationCount(state), 1);
  assert.equal(state.toastId, state.items[0].id);
  assert.equal(reduce(state, { type: "task", task: { ...task, status: "error", title: "Duplicate terminal callback" } }), state);
});

test("read and dismissed terminal tasks remain deduplicated after reload", () => {
  for (const type of ["read", "dismiss"]) {
    let state = reduce(initial(), { type: "task", task });
    state = reduce(state, { type, id: state.items[0].id });
    assert.equal(unreadNotificationCount(state), 0);
    assert.equal(state.toastId, null);
    state = reduce(createNotificationState(userId), { type: "restore", serialized: serializeNotificationHistory(state) });
    assert.equal(reduce(state, { type: "task", task }), state);
    assert.equal(state.items[0].dismissed, type === "dismiss");
  }
});

test("events received while the center is open are read without an overlapping toast", () => {
  let state = reduce(initial(), { type: "open" });
  state = reduce(state, { type: "task", task });
  assert.equal(unreadNotificationCount(state), 0);
  assert.equal(state.toastId, null);
  assert.equal(state.items.length, 1);
});

test("toast expiration hides only its own toast and does not mark unseen notifications read", () => {
  let state = reduce(initial(), { type: "task", task });
  const firstId = state.toastId;
  state = reduce(state, { type: "task", task: { ...task, id: "task-2" } });
  assert.equal(reduce(state, { type: "expire-toast", id: firstId }), state);
  state = reduce(state, { type: "expire-toast", id: state.toastId });
  assert.equal(state.toastId, null);
  assert.equal(unreadNotificationCount(state), 2);
});

test("history is bounded, keeps newest tasks, and preserves maintenance dismissal", () => {
  let state = reduce(initial(), { type: "warning", warning });
  state = reduce(state, { type: "dismiss", id: state.items[0].id });
  for (let index = 0; index < NOTIFICATION_LIMIT + 20; index++) {
    state = reduce(state, { type: "task", task: { ...task, id: `task-${index}`, createdAt: index } });
  }
  assert.equal(state.items.length, NOTIFICATION_LIMIT);
  assert.equal(state.items[0].task.id, `task-${NOTIFICATION_LIMIT + 19}`);
  assert.equal(state.items.find((item) => item.kind === "maintenance").dismissed, true);
  assert.equal(readNotificationHistory(serializeNotificationHistory(state), userId).length, NOTIFICATION_LIMIT);
  assert.equal(reduce(state, { type: "warning", warning }), state);
});

test("per-user keys, hydration and actions cannot leak another account's notifications", () => {
  const state = reduce(initial(), { type: "task", task });
  const saved = serializeNotificationHistory(state);
  const otherUser = "member-2";
  assert.notEqual(notificationStorageKey(userId), notificationStorageKey(otherUser));
  assert.notEqual(notificationStorageKey("a:b"), notificationStorageKey("a%3Ab"));
  assert.deepEqual(readNotificationHistory(saved, otherUser), []);
  assert.equal(notificationReducer(state, { userId: otherUser, type: "task", task: { ...task, id: "other-task" } }), state);
  assert.equal(notificationReducer(state, { userId: otherUser, type: "dismiss", id: state.items[0].id }), state);
  const otherState = notificationReducer(createNotificationState(otherUser), { userId: otherUser, type: "restore", serialized: saved });
  assert.equal(otherState.items.length, 0);
  assert.equal(otherState.toastId, null);
  assert.equal(unreadNotificationCount(otherState), 0);
});

test("corrupt or incompatible history is safe, and invalid task events are ignored", () => {
  for (const saved of ["bad-json", "null", "[]", JSON.stringify({ version: 99, userId, items: [] })]) {
    assert.deepEqual(readNotificationHistory(saved, userId), []);
  }
  for (const value of [null, {}, { ...task, id: "" }, { ...task, module: "unknown" }, { ...task, status: "pending" }, { ...task, createdAt: Infinity }]) {
    assert.equal(isWorkspaceTask(value), false);
    const state = initial();
    assert.equal(reduce(state, { type: "task", task: value }), state);
  }
});

test("restored history validates entries and deduplicates untrusted stored ids", () => {
  const state = reduce(initial(), { type: "task", task });
  const item = state.items[0];
  const items = readNotificationHistory(JSON.stringify({
    version: 1,
    userId,
    items: [
      null,
      { ...item, read: "yes" },
      { ...item, id: "forged-id" },
      item,
      { kind: "maintenance", read: false, dismissed: false, warning: { ...warning, foreign_key_violations: 0, comparison_orphans: 0 } },
    ],
  }), userId);
  assert.deepEqual(items, [item]);
});
