import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { isCurrentSpaceSnapshot } from "../features/spaces/dashboard-state.ts";

test("dashboard no longer requests or displays backend readiness", () => {
  const source = readFileSync(new URL("../features/spaces/components/dashboard.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /api\.health\(|healthLabel|Backend ready/);
  assert.match(source, /api\.spaces\(\)/);
  assert.match(source, /<BackendDown message=\{error\}/);
});

function deferred() {
  let resolve;
  const promise = new Promise((complete) => { resolve = complete; });
  return { promise, resolve };
}

test("a new space remains visible when an earlier list request returns empty", async () => {
  let latestRequest = 1;
  let mutation = 0;
  let spaces = [];
  const pendingList = deferred();
  const pendingHealth = deferred();
  const load = async () => {
    void pendingHealth.promise;
    const results = await pendingList.promise;
    if (isCurrentSpaceSnapshot(1, latestRequest, 0, mutation)) spaces = results;
  };
  const loading = load();
  mutation += 1;
  spaces = [{ id: "created", name: "New space" }];
  pendingList.resolve([]);
  await loading;
  assert.deepEqual(spaces.map((space) => space.id), ["created"]);
  assert.equal(isCurrentSpaceSnapshot(1, latestRequest, 0, mutation), false);
  latestRequest += 1;
  assert.equal(isCurrentSpaceSnapshot(1, latestRequest, mutation, mutation), false);
  pendingHealth.resolve();
});

test("the current list can complete without waiting for backend health", async () => {
  const pendingHealth = deferred();
  const pendingList = deferred();
  let spaces = [];
  const load = async () => {
    void pendingHealth.promise;
    const results = await pendingList.promise;
    if (isCurrentSpaceSnapshot(1, 1, 0, 0)) spaces = results;
  };
  const loading = load();
  pendingList.resolve([{ id: "existing", name: "Existing" }]);
  await loading;
  assert.deepEqual(spaces.map((space) => space.id), ["existing"]);
  pendingHealth.resolve();
});
