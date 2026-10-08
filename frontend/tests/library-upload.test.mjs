import assert from "node:assert/strict";
import { test } from "node:test";
import { initialUploadState, isUploadState, recoverUploadState } from "../features/papers/pdf-upload.ts";

test("upload reload recovery preserves title and filename without inventing browser Files", () => {
  const recovered = recoverUploadState({ ...initialUploadState, title: "My paper", fileName: "paper.pdf", uploading: true, taskId: "upload-task" });
  assert.equal(recovered.title, "My paper");
  assert.equal(recovered.fileName, "paper.pdf");
  assert.equal(recovered.uploading, false);
  assert.equal(recovered.job, null);
  assert.match(recovered.info, /interrupted before confirmation/);
  assert.equal("file" in recovered, false);
  assert.equal("bytes" in recovered, false);
  assert.equal(isUploadState(JSON.parse(JSON.stringify(recovered))), true);
});

test("a selected but unsent PDF is accurately marked for reselection on reload", () => {
  const recovered = recoverUploadState({ ...initialUploadState, fileName: "draft.pdf" });
  assert.match(recovered.info, /Choose “draft.pdf” again/);
  assert.equal(recovered.uploading, false);
});

test("confirmed upload jobs survive reload and can resume status polling", () => {
  const state = { ...initialUploadState, title: "Research", fileName: "source.pdf", taskId: "task", job: { paper_id: "paper", status: "EMBEDDING" } };
  assert.deepEqual(recoverUploadState(state), state);
  assert.equal(isUploadState(state), true);
  assert.equal(isUploadState({ ...state, job: { status: "QUEUED" } }), false);
  assert.equal(isUploadState({ ...state, uploading: "true" }), false);
  assert.equal(isUploadState({ ...state, title: null }), false);
});
