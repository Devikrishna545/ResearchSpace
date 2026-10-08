export const TASK_EVENT = "research-task-completed";
export const CONTEXT_EVENT = "research-context-changed";

export type WorkspaceModule = "library" | "chat" | "compare" | "notes";
export interface WorkspaceTask {
  id: string;
  spaceId: string;
  module: WorkspaceModule;
  title: string;
  message?: string;
  status: "success" | "error" | "info";
  createdAt: number;
}

export function notifyTask(task: Omit<WorkspaceTask, "createdAt">): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<WorkspaceTask>(TASK_EVENT, { detail: { ...task, createdAt: Date.now() } }));
  refreshWorkspaceContext(task.spaceId);
}

export function refreshWorkspaceContext(spaceId: string): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(CONTEXT_EVENT, { detail: { spaceId } }));
}
