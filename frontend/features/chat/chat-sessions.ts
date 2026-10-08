import type { ChatSession, SessionMention, Turn } from "@/lib/types";

/** Minimum messages before the backend allows compressing a conversation. */
export const COMPRESS_MIN_TURNS = 8;
/** Turns the backend always keeps verbatim at the end of a compressed conversation. */
export const COMPRESS_KEEP_RECENT = 4;
const MAX_MENTION_QUERY = 40;

const time = (value?: string | null) => (value ? new Date(value).getTime() || 0 : 0);

/** Pinned first, then most recently active — the same order the API returns. */
export function sortSessions(sessions: ChatSession[]): ChatSession[] {
  return [...sessions].sort((a, b) => Number(b.pinned) - Number(a.pinned) || time(b.updated_at) - time(a.updated_at));
}

/** The session before (-1) or after (+1) the active one in display order, or null at the ends. */
export function neighborSession(sessions: ChatSession[], activeId: string | null, direction: -1 | 1): string | null {
  if (!sessions.length) return null;
  const index = activeId ? sessions.findIndex((session) => session.id === activeId) : -1;
  if (index < 0) return direction === 1 ? sessions[0].id : null;
  return sessions[index + direction]?.id ?? null;
}

/** When the caret sits inside an `@query`, return where the mention starts and the text typed so far. */
export function activeMentionQuery(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  if (at > 0 && !/\s/.test(before[at - 1])) return null;
  const query = before.slice(at + 1);
  if (query.length > MAX_MENTION_QUERY || /[\n\r]/.test(query) || /\s{2,}/.test(query) || query.startsWith(" ")) return null;
  return { start: at, query };
}

export function insertMention(text: string, start: number, caret: number, title: string): { text: string; caret: number } {
  const token = `@${title} `;
  const rest = text.slice(caret).replace(/^\s+/, "");
  return { text: text.slice(0, start) + token + rest, caret: start + token.length };
}

/** Mentions whose `@Title` token is still present in the draft (the user may have deleted some). */
export function presentMentions(text: string, mentions: SessionMention[]): SessionMention[] {
  const seen = new Set<string>();
  return mentions.filter((mention) => {
    if (seen.has(mention.id) || !text.includes(`@${mention.title}`)) return false;
    seen.add(mention.id);
    return true;
  });
}

export type MentionPart = { text: string; mention?: SessionMention };

/** Split message text into plain text and `@Title` mention parts for rendering links. */
export function splitMentions(content: string, mentions: SessionMention[] = []): MentionPart[] {
  const ordered = [...mentions].filter((m) => m.title).sort((a, b) => b.title.length - a.title.length);
  if (!ordered.length) return [{ text: content }];
  const parts: MentionPart[] = [];
  let cursor = 0;
  while (cursor < content.length) {
    let best: { index: number; mention: SessionMention } | null = null;
    for (const mention of ordered) {
      const index = content.indexOf(`@${mention.title}`, cursor);
      if (index >= 0 && (!best || index < best.index)) best = { index, mention };
    }
    if (!best) break;
    if (best.index > cursor) parts.push({ text: content.slice(cursor, best.index) });
    const token = `@${best.mention.title}`;
    parts.push({ text: token, mention: best.mention });
    cursor = best.index + token.length;
  }
  if (cursor < content.length) parts.push({ text: content.slice(cursor) });
  return parts;
}

/**
 * How many of the loaded turns are covered by the session summary. Turns are loaded
 * newest-limited, so the summary count is shifted by any older turns not loaded.
 */
export function summarizedCount(session: Pick<ChatSession, "summary" | "summary_turn_count" | "turn_count"> | null | undefined, loadedTurns: Turn[]): number {
  if (!session?.summary || !session.summary_turn_count) return 0;
  const offset = Math.max(0, (session.turn_count ?? loadedTurns.length) - loadedTurns.length);
  return Math.min(loadedTurns.length, Math.max(0, session.summary_turn_count - offset));
}

/** True when enough new messages arrived since the last compression to make an update worthwhile. */
export function canCompress(session: Pick<ChatSession, "summary" | "summary_turn_count" | "turn_count"> | null | undefined): boolean {
  if (!session || session.turn_count < COMPRESS_MIN_TURNS) return false;
  const target = session.turn_count - COMPRESS_KEEP_RECENT;
  return !session.summary || target > session.summary_turn_count;
}
