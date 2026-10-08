import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";

async function dimensions(path) {
  const bytes = await readFile(new URL(path, import.meta.url));
  assert.equal(bytes.subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
  assert.equal(bytes[25], 6, "logo PNGs must keep RGBA transparency");
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

test("user-supplied logo has appropriately sized transparent derivatives", async () => {
  assert.deepEqual(await dimensions("../public/brand/source.png"), [1600, 600]);
  assert.deepEqual(await dimensions("../public/brand/tile-192.png"), [192, 192]);
  assert.deepEqual(await dimensions("../public/brand/lockup-840.png"), [840, 358]);
  assert.deepEqual(await dimensions("../app/icon.png"), [64, 64]);
});
