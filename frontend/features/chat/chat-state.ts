import type { SessionMention, Turn } from "@/lib/types";

export interface ChatDraft { text: string; mentions: SessionMention[] }
export interface PendingQuestion {
  id: string;
  sessionId: string | null;
  text: string;
  mentions: SessionMention[];
  since: number;
  baselineCount: number;
  baselineLastId: string | null;
  status: "creating" | "pending" | "unknown" | "failed";
  userTurnId?: string;
  responseTurnId?: string;
  error?: string;
}
export interface ChatWorkspaceState {
  version: 1;
  selected: boolean;
  activeId: string | null;
  view: "active" | "archived";
  query: string;
  drafts: Record<string, ChatDraft>;
  showFull: Record<string, boolean>;
  pending: PendingQuestion | null;
}

export const initialChatState: ChatWorkspaceState = {
  version: 1, selected: false, activeId: null, view: "active", query: "", drafts: {}, showFull: {}, pending: null,
};
export const draftKey = (sessionId: string | null) => sessionId === null ? "new" : `session:${sessionId}`;
export const emptyDraft: ChatDraft = { text: "", mentions: [] };
export const getDraft = (state: ChatWorkspaceState, sessionId: string | null): ChatDraft => state.drafts[draftKey(sessionId)] ?? emptyDraft;

export function updateDraft(state: ChatWorkspaceState, sessionId: string | null, update: Partial<ChatDraft>): ChatWorkspaceState {
  return { ...state, drafts: { ...state.drafts, [draftKey(sessionId)]: { ...getDraft(state, sessionId), ...update } } };
}

const record = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const nullableString = (value: unknown) => value === null || typeof value === "string";
const mentionsValid = (value: unknown): value is SessionMention[] => Array.isArray(value) && value.every((item) => record(item) && typeof item.id === "string" && typeof item.title === "string");

export function isChatWorkspaceState(value: unknown): value is ChatWorkspaceState {
  if (!record(value) || value.version !== 1 || typeof value.selected !== "boolean" || !nullableString(value.activeId)
    || (value.view !== "active" && value.view !== "archived") || typeof value.query !== "string"
    || !record(value.drafts) || !record(value.showFull)) return false;
  if (!Object.entries(value.drafts).every(([key, draft]) => (key === "new" || key.startsWith("session:")) && record(draft) && typeof draft.text === "string" && mentionsValid(draft.mentions))
    || !Object.values(value.showFull).every((expanded) => typeof expanded === "boolean")) return false;
  const pending = value.pending;
  return pending === null || (record(pending) && typeof pending.id === "string" && nullableString(pending.sessionId)
    && typeof pending.text === "string" && mentionsValid(pending.mentions)
    && typeof pending.since === "number" && Number.isFinite(pending.since) && pending.since >= 0
    && typeof pending.baselineCount === "number" && Number.isSafeInteger(pending.baselineCount) && pending.baselineCount >= 0
    && nullableString(pending.baselineLastId) && typeof pending.status === "string" && ["creating", "pending", "unknown", "failed"].includes(pending.status)
    && [pending.userTurnId, pending.responseTurnId, pending.error].every((item) => item === undefined || typeof item === "string"));
}

/** Use server ids/counts, not text alone: a repeated question must not match an older exchange. */
export function reconcileQuestion(pending: PendingQuestion, turns: Turn[], totalTurnCount: number): {
  status: "missing" | "saved" | "answered";
  userTurnId?: string;
  assistantTurnId?: string;
} {
  const saved = turns.filter((turn) => !turn.id.startsWith("local-"));
  const knownUser = pending.userTurnId ? saved.findIndex((turn) => turn.id === pending.userTurnId) : -1;
  const anchor = pending.baselineLastId ? saved.findIndex((turn) => turn.id === pending.baselineLastId) : -1;
  const offset = Math.max(0, totalTurnCount - saved.length);
  const start = anchor >= 0 ? anchor + 1 : pending.baselineCount >= offset ? pending.baselineCount - offset : saved.length;
  const sameMentions = (turn: Turn) => {
    const ids = new Set((turn.mentions ?? []).map((mention) => mention.id));
    return ids.size === new Set(pending.mentions.map((mention) => mention.id)).size && pending.mentions.every((mention) => ids.has(mention.id));
  };
  const index = knownUser >= 0 ? knownUser : saved.findIndex((turn, i) => i >= start && turn.role === "user" && turn.content.trim() === pending.text.trim() && sameMentions(turn));
  const knownResponse = pending.responseTurnId ? saved.find((turn) => turn.id === pending.responseTurnId && turn.role === "assistant") : undefined;
  if (knownResponse) return { status: "answered", userTurnId: index >= 0 ? saved[index].id : undefined, assistantTurnId: knownResponse.id };
  if (index < 0) return { status: "missing" };
  const next = saved.slice(index + 1).find((turn) => turn.role === "assistant" || turn.role === "user");
  return next?.role === "assistant"
    ? { status: "answered", userTurnId: saved[index].id, assistantTurnId: next.id }
    : { status: "saved", userTurnId: saved[index].id };
}

export function optimisticQuestion(pending: PendingQuestion): Turn {
  return { id: `local-${pending.id}`, role: "user", content: pending.text, mentions: pending.mentions, citations: [], session_id: pending.sessionId, created_at: new Date(pending.since).toISOString() };
}
