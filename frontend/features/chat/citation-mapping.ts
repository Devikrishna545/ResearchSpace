import type { Citation } from "@/lib/types";

export function mapCitationOccurrences(content: string, citations: Citation[]) {
  const byChunk = new Map<string, Array<{ citation: Citation; index: number }>>();
  citations.forEach((citation, index) => byChunk.set(citation.chunk_id, [...(byChunk.get(citation.chunk_id) ?? []), { citation, index: index + 1 }]));
  const occurrences = new Map<string, number>();
  const parts = content.split(/(\[[^\]]+\])/g);
  const hits = new Map<number, { citation: Citation; index: number }>();
  parts.forEach((part, index) => {
    const match = /^\[([^\]]+)\]$/.exec(part);
    if (!match) return;
    const occurrence = occurrences.get(match[1]) ?? 0;
    occurrences.set(match[1], occurrence + 1);
    const candidates = byChunk.get(match[1]);
    const hit = candidates?.[occurrence] ?? candidates?.[0];
    if (hit) hits.set(index, hit);
  });
  return { parts, hits };
}
