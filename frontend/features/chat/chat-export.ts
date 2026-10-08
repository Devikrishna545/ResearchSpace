import type { ChatSession, Turn } from "@/lib/types";

// The existing endpoint has no pagination and rejects larger limits.
export const CHAT_TURNS_LIMIT = 1000;
export type ChatExportFormat = "markdown" | "json";

export function createChatExport(session: ChatSession, turns: Turn[], format: ChatExportFormat, exportedAt = new Date().toISOString()) {
  const saved = [...new Map(turns.filter((turn) => !turn.id.startsWith("local-")).map((turn) => [turn.id, turn])).values()];
  if (session.turn_count > CHAT_TURNS_LIMIT || saved.length < session.turn_count) {
    throw new Error(`A complete export is unavailable: this chat has ${session.turn_count} saved messages, and the current API can return at most ${CHAT_TURNS_LIMIT}. No partial file was downloaded.`);
  }
  if (saved.some((turn) => turn.session_id && turn.session_id !== session.id)) throw new Error("The returned messages do not belong to this chat.");
  const filename = (session.title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-").replace(/[. ]+$/g, "").trim().slice(0, 100) || "chat");
  const data = { version: 1, exported_at: exportedAt, session, turns: saved };
  if (format === "json") return { content: JSON.stringify(data, null, 2), filename: `${filename}.json`, mime: "application/json;charset=utf-8" };
  const jsonBlock = (value: unknown) => {
    const json = JSON.stringify(value, null, 2);
    const fence = "`".repeat(Math.max(3, ...[...json.matchAll(/`+/g)].map((match) => match[0].length + 1)));
    return `${fence}json\n${json}\n${fence}`;
  };
  const content = [
    `# ${session.title.replace(/[\r\n]+/g, " ")}`,
    `Exported: ${exportedAt}`,
    "## Chat metadata",
    jsonBlock(session),
    ...(session.summary ? ["## Summary", session.summary] : []),
    "## Original conversation",
    ...saved.flatMap((turn, index) => [
      `### ${index + 1}. ${turn.role === "user" ? "You" : turn.role === "assistant" ? "Assistant" : turn.role}${turn.created_at ? ` — ${turn.created_at}` : ""}`,
      turn.content,
      "#### Citations and message metadata",
      jsonBlock(Object.fromEntries(Object.entries(turn).filter(([key]) => key !== "content"))),
    ]),
  ].join("\n\n");
  return { content: `${content}\n`, filename: `${filename}.md`, mime: "text/markdown;charset=utf-8" };
}
