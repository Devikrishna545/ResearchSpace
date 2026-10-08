"use client";

import { useEffect, useId, useReducer, useRef } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { AlertTriangle, Bell, CheckCircle2, Info, X } from "lucide-react";
import { TASK_EVENT } from "@/lib/task-events";
import {
  createNotificationState,
  isWorkspaceTask,
  legacyWarningSummary,
  notificationReducer,
  notificationStorageKey,
  serializeNotificationHistory,
  TASK_TOAST_DURATION,
  unreadNotificationCount,
  type LegacyWarning,
  type TaskNotification,
} from "@/features/auth/notifications";

export type LegacyNotificationsProps = { warning: LegacyWarning | null | undefined; userId: string };

export function LegacyNotifications(props: LegacyNotificationsProps) {
  return <NotificationCenter key={props.userId} {...props} />;
}

const MODULE_LABELS = { library: "Library", chat: "Chat", compare: "Compare", notes: "Notes" };
const STATUS_LABELS = { success: "Completed", error: "Failed", info: "Update" };

function TaskSummary({ item }: { item: TaskNotification }) {
  const { task } = item;
  const Icon = task.status === "error" ? AlertTriangle : task.status === "success" ? CheckCircle2 : Info;
  return <>
    <p className="mb-1 text-xs font-semibold text-muted">{MODULE_LABELS[task.module]} · {STATUS_LABELS[task.status]}</p>
    <p className="flex items-start gap-2 font-semibold"><Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{task.title}</p>
    {task.message ? <p className="mt-2 whitespace-pre-wrap break-words text-muted">{task.message}</p> : null}
  </>;
}

function NotificationCenter({ warning, userId }: LegacyNotificationsProps) {
  const [state, dispatch] = useReducer(notificationReducer, userId, createNotificationState);
  const { items, ready } = state;
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const toastRoot = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const headingId = useId();
  const unread = unreadNotificationCount(state);
  const visible = state.items.filter((item) => !item.dismissed);
  const toast = state.items.find((item): item is TaskNotification => item.kind === "task" && item.id === state.toastId && !item.dismissed);

  useEffect(() => {
    let serialized: string | null = null;
    try { serialized = sessionStorage.getItem(notificationStorageKey(userId)); } catch { /* In-memory notifications still work when storage is blocked. */ }
    dispatch({ type: "restore", userId, serialized });
  }, [userId]);

  useEffect(() => {
    dispatch({ type: "warning", userId, warning });
  }, [userId, warning]);

  useEffect(() => {
    if (!ready) return;
    try { sessionStorage.setItem(notificationStorageKey(userId), serializeNotificationHistory({ userId, items })); } catch { /* Storage may be disabled or full. */ }
  }, [items, ready, userId]);

  useEffect(() => {
    function onTask(event: Event) {
      const task: unknown = (event as CustomEvent<unknown>).detail;
      if (isWorkspaceTask(task)) dispatch({ type: "task", userId, task });
    }
    const closeForSettings = () => dispatch({ type: "close", userId });
    window.addEventListener(TASK_EVENT, onTask);
    window.addEventListener("research-settings-open", closeForSettings);
    return () => {
      window.removeEventListener(TASK_EVENT, onTask);
      window.removeEventListener("research-settings-open", closeForSettings);
    };
  }, [userId]);

  useEffect(() => {
    if (!state.toastId) return;
    const id = state.toastId;
    const timer = window.setTimeout(() => {
      if (toastRoot.current?.contains(document.activeElement)) trigger.current?.focus();
      dispatch({ type: "expire-toast", userId, id });
    }, TASK_TOAST_DURATION);
    return () => window.clearTimeout(timer);
  }, [state.toastId, userId]);

  useEffect(() => {
    if (!state.open) return;
    panel.current?.focus();
    function onPointerDown(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node)) dispatch({ type: "close", userId });
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        dispatch({ type: "close", userId });
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [state.open, userId]);

  function showNotifications() {
    window.dispatchEvent(new Event("research-notifications-open"));
    dispatch({ type: "open", userId });
  }

  function closeNotifications() {
    dispatch({ type: "close", userId });
    trigger.current?.focus();
  }

  function dismissNotification(id: string, fromToast = false) {
    dispatch({ type: "dismiss", userId, id });
    if (fromToast) trigger.current?.focus();
    else panel.current?.focus();
  }

  return <div ref={root} className="relative" onBlurCapture={(event) => {
    if (state.open && event.relatedTarget instanceof Node && !root.current?.contains(event.relatedTarget)) {
      dispatch({ type: "close", userId });
    }
  }}>
    <button ref={trigger} type="button" className="btn relative h-10 w-10 p-0" aria-label={unread ? `Notifications: ${unread} unread` : "Notifications"} aria-haspopup="dialog" aria-expanded={state.open} aria-controls={panelId} onClick={() => state.open ? closeNotifications() : showNotifications()}>
      <Bell className="h-4 w-4" aria-hidden="true" />
      {unread > 0 ? <span aria-hidden="true" className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber px-1 text-[10px] font-bold text-ink">{unread}</span> : null}
    </button>
    {state.open ? <section ref={panel} id={panelId} role="dialog" aria-labelledby={headingId} tabIndex={-1} className="fixed inset-x-4 top-28 z-[90] max-h-[calc(100dvh-8rem)] overflow-y-auto rounded-2xl border border-line bg-paper p-5 text-sm text-ink shadow-soft sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[min(26rem,calc(100vw-2.5rem))]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 id={headingId} className="font-serif text-xl">Notifications</h2>
        <button type="button" className="btn h-8 w-8 shrink-0 p-0" aria-label="Close notifications" onClick={closeNotifications}><X className="h-4 w-4" aria-hidden="true" /></button>
      </div>
      <p className="mb-4 text-xs text-muted">Recent updates for this account in this browser tab. Opening notifications marks them as read.</p>
      {visible.length === 0 ? <p className="rounded-xl border border-line p-4 text-muted">No notifications. Task updates will appear here.</p> : <ul className="space-y-3">
        {visible.map((item) => <li key={item.id} className={`break-words rounded-xl border p-4 ${item.kind === "maintenance" ? "border-amber-300 bg-amber-50" : "border-line bg-paper"}`}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              {item.kind === "task" ? <TaskSummary item={item} /> : <>
                <p className="mb-1 text-xs font-semibold text-muted">Maintenance</p>
                <p className="flex items-start gap-2 font-semibold"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber" aria-hidden="true" />Saved data needs review</p>
                <p className="mt-2">{legacyWarningSummary(item.warning)}</p>
                <p className="mt-2 text-muted">{item.warning.message}</p>
                <p className="mt-2 text-xs text-muted">Dismissing this notice does not repair or change any data.</p>
              </>}
            </div>
            <button type="button" className="btn h-7 w-7 shrink-0 p-0" aria-label={`Dismiss notification: ${item.kind === "task" ? item.task.title : "Saved data needs review"}`} onClick={() => dismissNotification(item.id)}><X className="h-3.5 w-3.5" aria-hidden="true" /></button>
          </div>
          {item.kind === "task" ? <Link href={`/spaces/${encodeURIComponent(item.task.spaceId)}`} prefetch={false} className="mt-3 inline-block font-semibold text-indigo-deep underline" onClick={closeNotifications}>Open workspace</Link> : null}
        </li>)}
      </ul>}
    </section> : null}
    {toast && typeof document !== "undefined" ? createPortal(
      <div ref={toastRoot} className="fixed right-4 top-28 z-[95] max-h-[calc(100dvh-8rem)] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-line bg-paper p-4 text-sm text-ink shadow-soft sm:top-20" onKeyDown={(event) => {
        if (event.key === "Escape") { event.preventDefault(); dismissNotification(toast.id, true); }
      }}>
        <div className="flex items-start justify-between gap-3">
          <div role="status" aria-live="polite" aria-atomic="true" className="min-w-0 flex-1 break-words"><TaskSummary item={toast} /></div>
          <button type="button" className="btn h-7 w-7 shrink-0 p-0" aria-label={`Dismiss notification: ${toast.task.title}`} onClick={() => dismissNotification(toast.id, true)}><X className="h-3.5 w-3.5" aria-hidden="true" /></button>
        </div>
        <button className="mt-3 text-sm font-semibold text-indigo-deep underline" type="button" onClick={showNotifications}>View notifications</button>
      </div>,
      document.body
    ) : null}
  </div>;
}
