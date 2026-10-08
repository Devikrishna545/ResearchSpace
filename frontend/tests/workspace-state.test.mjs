import assert from "node:assert/strict";
import { test } from "node:test";
import { isRecord, isStringArray, readWorkspaceState, workspaceStorageKey } from "../features/spaces/workspace-state.ts";

test("workspace state keys isolate user, space, module, and ambiguous delimiters", () => {
  const key = workspaceStorageKey("user", "space", "chat");
  assert.notEqual(key, workspaceStorageKey("other", "space", "chat"));
  assert.notEqual(key, workspaceStorageKey("user", "other", "chat"));
  assert.notEqual(key, workspaceStorageKey("user", "space", "notes"));
  assert.notEqual(workspaceStorageKey("a:b", "c", "chat"), workspaceStorageKey("a", "b:c", "chat"));
});

test("restoration validates data rather than trusting malformed saved views", () => {
  const valid = (v) => isRecord(v) && typeof v.query === "string" && isStringArray(v.selected);
  const initial = { query: "", selected: [] };
  assert.equal(readWorkspaceState(null, initial, valid), initial);
  assert.deepEqual(readWorkspaceState('{"query":"retrieval","selected":["p1"]}', initial, valid), { query: "retrieval", selected: ["p1"] });
  assert.throws(() => readWorkspaceState("{", initial, valid));
  assert.throws(() => readWorkspaceState('{"query":5,"selected":[]}', initial, valid));
  assert.throws(() => readWorkspaceState('{"query":"","selected":[5]}', initial, valid));
});
