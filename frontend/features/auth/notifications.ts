import type { AuthStatus } from "@/lib/api/client";
import type { WorkspaceTask } from "@/lib/task-events";

export type LegacyWarning = NonNullable<AuthStatus["legacy_warning"]>;

export function legacyNoticeKey(warning: LegacyWarning): string {
  return JSON.stringify([warning.foreign_key_violations, warning.comparison_orphans, warning.message]);
}

export const NOTIFICATION_LIMIT = 50;
export const TASK_TOAST_DURATION = 7000;

type NotificationFlags = { id: string; read: boolean; dismissed: boolean };
export type TaskNotification = NotificationFlags & { kind: "task"; task: WorkspaceTask };
export type MaintenanceNotification = NotificationFlags & { kind: "maintenance"; warning: LegacyWarning };
export type NotificationItem = TaskNotification | MaintenanceNotification;

export type NotificationState = {
  userId: string;
  ready: boolean;
  items: NotificationItem[];
  open: boolean;
  toastId: string | null;
};

export type NotificationAction = { userId: string } & (
  | { type: "restore"; serialized: string | null }
  | { type: "warning"; warning: LegacyWarning | null | undefined }
  | { type: "task"; task: WorkspaceTask }
  | { type: "open" | "close" | "read-all" }
  | { type: "read" | "dismiss" | "expire-toast"; id: string }
);

export function notificationStorageKey(userId: string): string {
  return `research-assistant-notifications:v1:${encodeURIComponent(userId)}`;
}

export function createNotificationState(userId: string): NotificationState {
  return { userId, ready: false, items: [], open: false, toastId: null };
}

export function hasLegacyIssues(warning: LegacyWarning | null | undefined): warning is LegacyWarning {
  return Boolean(warning && (warning.foreign_key_violations > 0 || warning.comparison_orphans > 0));
}

export function legacyWarningSummary(warning: LegacyWarning): string {
  const parts: string[] = [];
  if (warning.foreign_key_violations > 0) {
    parts.push(`${warning.foreign_key_violations} broken reference${warning.foreign_key_violations === 1 ? "" : "s"}`);
  }
  if (warning.comparison_orphans > 0) {
    parts.push(`${warning.comparison_orphans} comparison${warning.comparison_orphans === 1 ? "" : "s"} with missing papers`);
  }
  return parts.length ? `${parts.join(" and ")}.` : "No broken references or comparisons with missing papers.";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isWorkspaceTask(value: unknown): value is WorkspaceTask {
  if (!isRecord(value)) return false;
  return typeof value.id === "string" && value.id.length > 0
    && typeof value.spaceId === "string" && value.spaceId.length > 0
    && typeof value.title === "string" && value.title.trim().length > 0
    && (value.message === undefined || typeof value.message === "string")
    && typeof value.module === "string" && ["library", "chat", "compare", "notes"].includes(value.module)
    && typeof value.status === "string" && ["success", "error", "info"].includes(value.status)
    && typeof value.createdAt === "number" && Number.isFinite(value.createdAt);
}

function isLegacyWarning(value: unknown): value is LegacyWarning {
  return isRecord(value)
    && typeof value.foreign_key_violations === "number" && Number.isFinite(value.foreign_key_violations)
    && typeof value.comparison_orphans === "number" && Number.isFinite(value.comparison_orphans)
    && typeof value.message === "string";
}

function taskNoticeKey(task: WorkspaceTask): string {
  return `task:${task.id}`;
}

function maintenanceNoticeKey(warning: LegacyWarning): string {
  return `maintenance:${legacyNoticeKey(warning)}`;
}

function boundHistory(items: NotificationItem[]): NotificationItem[] {
  // Keep the current maintenance item's read/dismiss state even after many tasks.
  const maintenance = items.find((item) => item.kind === "maintenance");
  const tasks = items.filter((item) => item.kind === "task").slice(0, NOTIFICATION_LIMIT - (maintenance ? 1 : 0));
  return maintenance ? [...tasks, maintenance] : tasks;
}

export function serializeNotificationHistory(state: Pick<NotificationState, "userId" | "items">): string {
  return JSON.stringify({ version: 1, userId: state.userId, items: boundHistory(state.items) });
}

export function readNotificationHistory(serialized: string | null, userId: string): NotificationItem[] {
  if (!serialized) return [];
  try {
    const saved: unknown = JSON.parse(serialized);
    if (!isRecord(saved) || saved.version !== 1 || saved.userId !== userId || !Array.isArray(saved.items)) return [];
    const items: NotificationItem[] = [];
    const ids = new Set<string>();
    for (const value of saved.items) {
      if (!isRecord(value) || typeof value.read !== "boolean" || typeof value.dismissed !== "boolean") continue;
      let item: NotificationItem;
      if (value.kind === "task" && isWorkspaceTask(value.task)) {
        item = { kind: "task", id: taskNoticeKey(value.task), task: value.task, read: value.read, dismissed: value.dismissed };
      } else if (value.kind === "maintenance" && isLegacyWarning(value.warning) && hasLegacyIssues(value.warning)) {
        item = { kind: "maintenance", id: maintenanceNoticeKey(value.warning), warning: value.warning, read: value.read, dismissed: value.dismissed };
      } else {
        continue;
      }
      if (!ids.has(item.id)) {
        ids.add(item.id);
        items.push(item);
      }
    }
    return boundHistory(items);
  } catch {
    return [];
  }
}

export function unreadNotificationCount(state: NotificationState): number {
  return state.items.filter((item) => !item.read && !item.dismissed).length;
}

export function notificationReducer(state: NotificationState, action: NotificationAction): NotificationState {
  if (action.userId !== state.userId) return state;
  switch (action.type) {
    case "restore":
      return state.ready ? state : { ...state, ready: true, items: readNotificationHistory(action.serialized, state.userId) };
    case "warning": {
      const current = state.items.find((item) => item.kind === "maintenance");
      if (!hasLegacyIssues(action.warning)) {
        return current ? { ...state, items: state.items.filter((item) => item.kind !== "maintenance") } : state;
      }
      const id = maintenanceNoticeKey(action.warning);
      if (current?.id === id) return state;
      return {
        ...state,
        items: boundHistory([
          ...state.items.filter((item) => item.kind !== "maintenance"),
          { kind: "maintenance", id, warning: action.warning, read: state.open, dismissed: false },
        ]),
      };
    }
    case "task": {
      if (!isWorkspaceTask(action.task)) return state;
      const id = taskNoticeKey(action.task);
      if (state.items.some((item) => item.id === id)) return state;
      const item: TaskNotification = { kind: "task", id, task: { ...action.task }, read: state.open, dismissed: false };
      return { ...state, items: boundHistory([item, ...state.items]), toastId: state.open ? null : id };
    }
    case "open":
    case "read-all":
      return {
        ...state,
        open: action.type === "open" || state.open,
        toastId: null,
        items: state.items.map((item) => item.read ? item : { ...item, read: true }),
      };
    case "close":
      return { ...state, open: false };
    case "read":
    case "dismiss":
      return {
        ...state,
        toastId: state.toastId === action.id ? null : state.toastId,
        items: state.items.map((item) => item.id === action.id
          ? { ...item, read: true, dismissed: action.type === "dismiss" || item.dismissed }
          : item),
      };
    case "expire-toast":
      return state.toastId === action.id ? { ...state, toastId: null } : state;
  }
}
