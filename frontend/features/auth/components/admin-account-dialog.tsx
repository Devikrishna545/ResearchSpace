"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { api, ApiError, type AuthUser } from "@/lib/api/client";

export type AdminAction = "create" | "reset";

export function AdminAccountDialog({ action, onClose }: { action: AdminAction; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const emailField = useRef<HTMLInputElement>(null);
  const userField = useRef<HTMLSelectElement>(null);
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [userId, setUserId] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingUsers, setLoadingUsers] = useState(action === "reset");
  const [feedback, setFeedback] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    (action === "create" ? emailField : userField).current?.focus();
    return () => { if (element?.open) element.close(); };
  }, [action]);

  useEffect(() => {
    if (action !== "reset") return;
    let active = true;
    api.listUsers().then((accounts) => {
      if (active) setUsers(accounts);
    }).catch((error: unknown) => {
      if (active) setFeedback({ kind: "error", text: errorMessage(error) });
    }).finally(() => {
      if (active) setLoadingUsers(false);
    });
    return () => { active = false; };
  }, [action]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setFeedback(null);
    try {
      if (action === "create") {
        const account = await api.createUser(email.trim(), password);
        setEmail("");
        setPassword("");
        setFeedback({ kind: "success", text: `User ${account.email} created.` });
      } else {
        await api.resetUserPassword(userId, password);
        setPassword("");
        setFeedback({ kind: "success", text: "Password reset. That account's existing sessions were revoked." });
      }
    } catch (error) {
      setFeedback({ kind: "error", text: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  }

  function close() {
    dialog.current?.close();
    onClose();
  }

  const title = action === "create" ? "Create user" : "Reset user password";
  return <dialog ref={dialog} aria-labelledby="admin-dialog-title" aria-modal="true" onCancel={(event) => { event.preventDefault(); close(); }} onClick={(event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (event.target === event.currentTarget && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) close();
  }} className="m-auto max-h-[calc(100vh-2rem)] w-[min(28rem,calc(100vw-2rem))] overflow-y-auto rounded-3xl border border-line bg-paper p-6 text-ink shadow-soft">
    <div className="mb-5 flex items-start justify-between gap-4">
      <div><p className="eyebrow mb-1">Account administration</p><h2 id="admin-dialog-title" className="font-serif text-2xl">{title}</h2></div>
      <button className="btn h-9 w-9 shrink-0 p-0" type="button" aria-label={`Close ${title.toLowerCase()}`} onClick={close}><X className="h-4 w-4" /></button>
    </div>
    <form className="space-y-4" onSubmit={(event) => void submit(event)}>
      {action === "create" ?
        <label className="block text-sm">Email
          <input ref={emailField} className="input mt-1" type="email" autoComplete="off" required value={email} onChange={(event) => setEmail(event.target.value)} />
        </label> :
        <label className="block text-sm">User
          <select ref={userField} className="input mt-1" required disabled={loadingUsers} value={userId} onChange={(event) => setUserId(event.target.value)}>
            <option value="">{loadingUsers ? "Loading accounts…" : "Select an account"}</option>
            {users.map((account) => <option key={account.id} value={account.id}>{account.email}</option>)}
          </select>
        </label>}
      <label className="block text-sm">{action === "create" ? "Temporary password" : "New password"}
        <input className="input mt-1" type="password" autoComplete="new-password" minLength={12} required value={password} onChange={(event) => setPassword(event.target.value)} />
      </label>
      <p className="text-xs text-muted">Use at least 12 characters.</p>
      {feedback ? <p role={feedback.kind === "error" ? "alert" : "status"} className={feedback.kind === "error" ? "rounded-xl bg-rose/10 p-3 text-sm text-rose" : "rounded-xl bg-indigo-soft p-3 text-sm text-indigo-deep"}>{feedback.text}</p> : null}
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-primary" disabled={busy || loadingUsers || (action === "reset" && !userId)}>{busy ? "Please wait…" : title}</button>
        <button className="btn" type="button" onClick={close}>Cancel</button>
      </div>
    </form>
  </dialog>;
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Request failed. Please try again.";
}
