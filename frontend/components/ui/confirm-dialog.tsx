"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";

export interface ConfirmOptions { title: string; message: string; confirmLabel?: string; tone?: "danger" | "default" }
type Pending = ConfirmOptions & { resolve: (value: boolean) => void };

/**
 * Promise-based confirmation dialog: `if (await confirm({...})) doIt()`.
 * Render the returned `dialog` element once in the component tree.
 */
export function useConfirm() {
  const [pending, setPending] = useState<Pending | null>(null);
  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>((resolve) => setPending({ ...options, resolve })), []);
  const settle = useCallback((value: boolean) => {
    setPending((current) => { current?.resolve(value); return null; });
  }, []);
  const dialog = pending ? <ConfirmDialog options={pending} onSettle={settle} /> : null;
  return { confirm, dialog };
}

function ConfirmDialog({ options, onSettle }: { options: ConfirmOptions; onSettle: (value: boolean) => void }) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); onSettle(false); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onSettle]);
  const danger = options.tone !== "default";
  return <div className="fixed inset-0 z-[80] grid place-items-center bg-ink/30 p-4 backdrop-blur-sm" onClick={() => onSettle(false)}>
    <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message" className="w-full max-w-md rounded-3xl border border-line bg-paper p-6 shadow-soft" onClick={(event) => event.stopPropagation()}>
      <div className="flex items-start gap-3">
        {danger ? <span className="rounded-2xl bg-rose/10 p-2 text-rose"><AlertTriangle className="h-5 w-5" /></span> : null}
        <div><h2 id="confirm-title" className="font-serif text-2xl">{options.title}</h2><p id="confirm-message" className="mt-2 text-sm text-muted">{options.message}</p></div>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <button type="button" className="btn" onClick={() => onSettle(false)}>Cancel</button>
        <button ref={confirmRef} type="button" className={danger ? "btn btn-danger" : "btn btn-primary"} onClick={() => onSettle(true)}>{options.confirmLabel ?? "Confirm"}</button>
      </div>
    </div>
  </div>;
}
