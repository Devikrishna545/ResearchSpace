import assert from "node:assert/strict";
import { test } from "node:test";
import { File } from "node:buffer";
import { api, ApiError, setCsrfToken } from "../lib/api/client.ts";
import { MAX_PDF_BYTES, pdfUploadError } from "../features/papers/pdf-upload.ts";

test("PDF upload selection handles empty, oversized, and wrong extensions", () => {
  assert.equal(pdfUploadError({ name: "book.pdf", size: 1234 }), null);
  assert.equal(pdfUploadError({ name: "book.PDF", size: MAX_PDF_BYTES }), null);
  assert.match(pdfUploadError({ name: "book.html", size: 100 }), /Choose a PDF/);
  assert.match(pdfUploadError({ name: "book.pdf", size: MAX_PDF_BYTES + 1 }), /30 MB/);
  assert.match(pdfUploadError({ name: "book.pdf", size: 0 }), /empty/);
});

test("multipart upload carries credentials, CSRF and progress without setting Content-Type", async () => {
  const original = globalThis.XMLHttpRequest;
  let sent;
  class FakeRequest {
    headers = {};
    upload = {};
    status = 200;
    responseText = JSON.stringify({ paper_id: "paper-1", status: "READY", message: "Indexed" });
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader(key, value) { this.headers[key] = value; }
    send(body) {
      sent = { method: this.method, url: this.url, headers: this.headers, withCredentials: this.withCredentials, body };
      this.upload.onprogress({ lengthComputable: true, loaded: 5, total: 10 });
      this.onload();
    }
  }
  try {
    globalThis.XMLHttpRequest = FakeRequest;
    setCsrfToken("test-csrf");
    const progress = [];
    const result = await api.uploadPaper("space 1", new File(["%PDF-test"], "paper.pdf", { type: "application/pdf" }), "Custom title", (value) => progress.push(value));
    assert.equal(result.paper_id, "paper-1");
    assert.match(sent.url, /\/spaces\/space%201\/papers\/upload$/);
    assert.equal(sent.method, "POST");
    assert.equal(sent.withCredentials, true);
    assert.equal(sent.headers["X-CSRF-Token"], "test-csrf");
    assert.equal("Content-Type" in sent.headers, false);
    assert.equal(sent.body.get("title"), "Custom title");
    assert.equal(sent.body.get("file").name, "paper.pdf");
    assert.deepEqual(progress, [50]);
  } finally {
    setCsrfToken(null);
    globalThis.XMLHttpRequest = original;
  }
});

test("upload surfaces server validation errors without claiming success", async () => {
  const original = globalThis.XMLHttpRequest;
  class Rejected {
    upload = {};
    status = 413;
    responseText = JSON.stringify({ detail: "PDF exceeds the 30 MB limit" });
    open() {}
    setRequestHeader() {}
    send() { this.onload(); }
  }
  try {
    globalThis.XMLHttpRequest = Rejected;
    await assert.rejects(
      () => api.uploadPaper("s", new File(["%PDF-test"], "paper.pdf"), "", () => {}),
      (error) => error instanceof ApiError && error.status === 413 && /30 MB/.test(error.message)
    );
  } finally {
    globalThis.XMLHttpRequest = original;
  }
});
