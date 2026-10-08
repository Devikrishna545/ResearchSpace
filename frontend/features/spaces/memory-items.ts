/** Short headline for a collapsed memory item: its first sentence, clipped. */
export function memoryHeadline(text: string, max = 90): string {
  const clean = text.replace(/\s+/g, " ").trim();
  const sentence = /^(.+?[.!?])(\s|$)/.exec(clean)?.[1] ?? clean;
  return sentence.length <= max ? sentence : `${sentence.slice(0, max - 1).trimEnd()}…`;
}

/** True when the headline does not already show the whole item, so expanding reveals more. */
export function hasMoreDetail(text: string, max = 90): boolean {
  return memoryHeadline(text, max) !== text.replace(/\s+/g, " ").trim();
}

/** Stable key for a memory item so per-item UI state survives memory refreshes. */
export function memoryKey(text: string): string {
  let hash = 0;
  for (const char of text.trim().toLowerCase()) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return `m${(hash >>> 0).toString(36)}`;
}
