import { clsx, type ClassValue } from "clsx";
import type { JsonValue } from "@/lib/types";

export const cn = (...classes: ClassValue[]) => clsx(classes);
export const dateLabel = (value?: string | null) => value ? new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "Recently";
export const shortId = (id: string) => id.length > 8 ? id.slice(0, 8) : id;
export function textFromJson(value: JsonValue | undefined): string {
  if (value === undefined || value === null) return "?";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => textFromJson(item)).join("; ");
  return Object.entries(value).map(([key, val]) => `${key}: ${textFromJson(val)}`).join("\n");
}
export const isTerminalStatus = (status: string) => ["READY", "DEGRADED", "FAILED", "ready", "degraded", "failed"].includes(status);
