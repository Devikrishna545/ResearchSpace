export const WORKSPACE_STORAGE_PREFIX = "r-space:workspace:v1:";

export function workspaceStorageKey(userId: string, spaceId: string, module: string): string {
  return `${WORKSPACE_STORAGE_PREFIX}${encodeURIComponent(userId)}:${encodeURIComponent(spaceId)}:${encodeURIComponent(module)}`;
}

export function readWorkspaceState<T>(raw: string | null, initial: T, validate: (value: unknown) => value is T): T {
  if (raw === null) return initial;
  const parsed: unknown = JSON.parse(raw);
  if (!validate(parsed)) throw new Error("Saved workspace state has an unsupported format.");
  return parsed;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
