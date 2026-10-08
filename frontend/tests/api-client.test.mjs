import assert from "node:assert/strict";
import { test } from "node:test";
import { api, API_BASE, ApiError, asList, setCsrfToken } from "../lib/api/client.ts";

function mockRequests(t, respond = () => new Response("{}", { status: 200 })) {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, ...init });
    return respond(url, init);
  });
  t.after(() => setCsrfToken(null));
  return calls;
}

test("API authentication preserves credentials, caching and CSRF handling", async (t) => {
  const calls = mockRequests(t, () => new Response(JSON.stringify({ csrf_token: "csrf-example" })));
  const status = await api.authStatus();
  assert.equal(status.csrf_token, "csrf-example");
  await api.spaces();
  await api.logout();
  assert.equal(calls[0].url, `${API_BASE}/v1/auth/status`);
  assert.equal(calls[1].headers.has("X-CSRF-Token"), false);
  assert.equal(calls[2].headers.get("X-CSRF-Token"), "csrf-example");
  assert.equal(calls[2].method, "POST");
  for (const call of calls) {
    assert.equal(call.credentials, "include");
    assert.equal(call.cache, "no-store");
  }
});

test("feature requests preserve URL encoding and serialized defaults", async (t) => {
  const calls = mockRequests(t);
  await api.chat("space /", "Question?");
  await api.chat("space /", "Follow-up", { sessionId: "chat-1", mentionedSessionIds: ["chat-2"] });
  await api.search("space /", "query");
  await api.pinPaper("space /", { title: "Paper", raw_payload: "invalid" }, true);
  await api.createNote("space /", "Note", null, { chunk_id: "chunk-1", quote: "Evidence" });
  await api.updateOpenAlexConsent({ choice: "decline", consent: false });
  await api.duplicateSpace("space /", true);
  const expected = [
    ["/v1/spaces/space%20%2F/chat", { question: "Question?", session_id: null, mentioned_session_ids: [] }],
    ["/v1/spaces/space%20%2F/chat", { question: "Follow-up", session_id: "chat-1", mentioned_session_ids: ["chat-2"] }],
    ["/v1/spaces/space%20%2F/search", { query: "query", include_web: false }],
    ["/v1/spaces/space%20%2F/papers?background=true", { title: "Paper", raw_payload: {} }],
    ["/v1/spaces/space%20%2F/notes", { content: "Note", paper_id: null, chunk_id: "chunk-1", quote: "Evidence" }],
    ["/v1/auth/openalex-consent", { choice: "decline", consent: false }],
    ["/v1/spaces/space%20%2F/duplicate", { copy_notes: true }],
  ];
  expected.forEach(([path, body], index) => {
    assert.equal(calls[index].url, `${API_BASE}${path}`);
    assert.equal(calls[index].body, JSON.stringify(body));
    assert.equal(calls[index].headers.get("Content-Type"), "application/json");
  });
  assert.equal(calls[5].method, "PUT");
});

test("active grounded comparison, evidence and corpus APIs keep their contracts", async (t) => {
  const calls = mockRequests(t);
  const body = { paper_ids: ["paper-1", "paper-2"], refresh: true, check_novelty: true, tier: "balanced", corpus_id: "corpus /" };
  await api.startCompareJob("space /", body);
  await api.compareJobs("space /");
  await api.compareJob("job /");
  await api.cancelCompareJob("job /");
  await api.evidenceLedger("paper /");
  await api.rebuildEvidence("paper /");
  await api.groundedTiers();
  await api.corpus("corpus /");
  await api.addCorpusPapers(["paper-1"], "permission", "", "corpus /");
  await api.comparison("report /");
  const paths = [
    "/v1/spaces/space%20%2F/compare-jobs",
    "/v1/spaces/space%20%2F/compare-jobs",
    "/v1/compare-jobs/job%20%2F",
    "/v1/compare-jobs/job%20%2F/cancel",
    "/v1/papers/paper%20%2F/evidence",
    "/v1/papers/paper%20%2F/evidence/rebuild",
    "/v1/grounded/tiers",
    "/v1/corpus?corpus_id=corpus%20%2F",
    "/v1/corpus/papers",
    "/v1/comparisons/report%20%2F",
  ];
  assert.deepEqual(calls.map(({ url }) => url), paths.map((path) => `${API_BASE}${path}`));
  assert.equal(calls[0].body, JSON.stringify(body));
  assert.equal(calls[3].method, "POST");
  assert.equal(calls[5].method, "POST");
  assert.equal(calls[8].body, JSON.stringify({ corpus_id: "corpus /", paper_ids: ["paper-1"], permission: "permission", permission_note: null }));
  assert.equal(api.artifactImageUrl("artifact /"), `${API_BASE}/v1/evidence/artifacts/artifact%20%2F/image`);
});

test("expired sessions retain auth events, error details and CSRF clearing", async (t) => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const events = [];
  Object.defineProperty(globalThis, "window", { configurable: true, value: { dispatchEvent: (event) => events.push(event.type) } });
  t.after(() => {
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
  });
  const calls = mockRequests(t, () => new Response(JSON.stringify({ detail: "Session expired" }), { status: 401 }));
  setCsrfToken("expired-token");
  await assert.rejects(api.createSpace("Research"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 401);
    assert.equal(error.message, '"Session expired"');
    assert.deepEqual(error.details, { detail: "Session expired" });
    return true;
  });
  await assert.rejects(api.login("reader@example.com", "password"), ApiError);
  assert.deepEqual(events, ["research-auth-expired"]);
  assert.equal(calls[0].headers.get("X-CSRF-Token"), "expired-token");
  assert.equal(calls[1].headers.has("X-CSRF-Token"), false);
});

test("network and non-JSON errors preserve their public error shape", async (t) => {
  const failure = new TypeError("offline");
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw failure; });
  await assert.rejects(api.spaces(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 0);
    assert.equal(error.details, failure);
    assert.equal(error.message, "Backend unreachable. Confirm FastAPI is running on port 8321.");
    return true;
  });
  fetch.mock.mockImplementation(async () => new Response("Unavailable", { status: 503, statusText: "Service unavailable" }));
  await assert.rejects(api.spaces(), (error) => {
    assert.equal(error.status, 503);
    assert.equal(error.message, "Service unavailable");
    assert.equal(error.details, "Unavailable");
    return true;
  });
});

test("list envelopes and reader query parameters stay compatible", async (t) => {
  const values = [{ id: "one" }];
  assert.equal(asList(values), values);
  assert.equal(asList({ value: values }), values);
  assert.deepEqual(asList({}), []);
  const calls = mockRequests(t);
  await api.paperContent("paper /", "space /", 25);
  await api.chatSessions("space /", "archived", "  session /  ");
  assert.equal(calls[0].url, `${API_BASE}/v1/papers/paper%20%2F/content?space_id=space+%2F&limit=25`);
  assert.equal(calls[1].url, `${API_BASE}/v1/spaces/space%20%2F/chat-sessions?status=archived&q=session%20%2F`);
});
