/**
 * Locate a cited quote inside a chunk's text, tolerating whitespace/case differences and
 * trailing ellipses from truncated quotes. Returns offsets into the original text.
 */
export function findQuoteRange(text: string, quote?: string | null): { start: number; end: number } | null {
  const cleaned = (quote ?? "").trim().replace(/^["“”']+|["“”']+$/g, "").replace(/(\.{3}|…)+$/, "").trim();
  if (!text || cleaned.length < 3) return null;
  const map: number[] = [];
  let normalized = "";
  let previousSpace = false;
  for (let index = 0; index < text.length; index += 1) {
    const isSpace = /\s/.test(text[index]);
    if (isSpace) {
      if (previousSpace || normalized.length === 0) continue;
      normalized += " ";
    } else {
      normalized += text[index].toLowerCase();
    }
    map.push(index);
    previousSpace = isSpace;
  }
  const needle = cleaned.replace(/\s+/g, " ").toLowerCase();
  for (const candidate of [needle, needle.slice(0, 80).trim()]) {
    if (candidate.length < 3) continue;
    const found = normalized.indexOf(candidate);
    if (found >= 0) {
      const last = found + candidate.length - 1;
      return { start: map[found], end: map[last] + 1 };
    }
  }
  return null;
}
