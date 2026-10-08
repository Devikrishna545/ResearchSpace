import assert from "node:assert/strict";
import { test } from "node:test";
import { mapCitationOccurrences } from "../features/chat/citation-mapping.ts";

test("repeated chunk markers open the excerpt aligned to each claim", () => {
  const first = { chunk_id: "shared", quote: "first passage", claim_text: "First claim" };
  const second = { chunk_id: "shared", quote: "second passage", claim_text: "Second claim" };
  const { parts, hits } = mapCitationOccurrences("First [shared]. Second [shared].", [first, second]);
  const markers = parts.map((part, index) => part === "[shared]" ? hits.get(index) : undefined).filter(Boolean);
  assert.deepEqual(markers.map((hit) => hit.citation.quote), ["first passage", "second passage"]);
  assert.deepEqual(markers.map((hit) => hit.index), [1, 2]);
});

test("legacy single citations still resolve repeated markers and missing IDs stay unlinked", () => {
  const citation = { chunk_id: "existing", quote: "passage" };
  const { parts, hits } = mapCitationOccurrences("[existing] [existing] [missing]", [citation]);
  assert.deepEqual(parts.map((part, index) => part.startsWith("[") ? hits.get(index)?.citation : null).filter((_, index) => parts[index].startsWith("[")), [
    citation, citation, undefined,
  ]);
});
