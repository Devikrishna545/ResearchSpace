"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { api, ApiError, type OpenAlexConsentChoice } from "@/lib/api/client";

type Choice = OpenAlexConsentChoice["choice"];

export function OpenAlexConsentDialog({ accountEmail, firstSignIn, onSaved, onClose }: {
  accountEmail: string;
  firstSignIn: boolean;
  onSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [customEmail, setCustomEmail] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => { if (element?.open) element.close(); };
  }, []);

  function close() {
    dialog.current?.close();
    onClose();
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!choice || (choice !== "decline" && !agreed)) return;
    const body: OpenAlexConsentChoice = choice === "decline"
      ? { choice: "decline", consent: false }
      : choice === "account"
        ? { choice: "account", consent: true }
        : { choice: "custom", contact_email: customEmail.trim(), consent: true };
    setBusy(true);
    setError(null);
    try {
      await api.updateOpenAlexConsent(body);
      await onSaved();
      close();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save your OpenAlex choice. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return <dialog ref={dialog} aria-labelledby="openalex-consent-title" aria-describedby="openalex-consent-explanation" aria-modal="true" onCancel={(event) => { event.preventDefault(); close(); }} className="m-auto max-h-[calc(100vh-2rem)] w-[min(34rem,calc(100vw-2rem))] overflow-y-auto rounded-3xl border border-line bg-paper p-6 text-ink shadow-soft">
    <div className="mb-4 flex items-start justify-between gap-4">
      <div><p className="eyebrow mb-1">Research discovery</p><h2 id="openalex-consent-title" className="font-serif text-2xl">{firstSignIn ? "Choose OpenAlex identification" : "OpenAlex contact preference"}</h2></div>
      <button className="btn h-9 w-9 shrink-0 p-0" type="button" aria-label="Close OpenAlex preference" onClick={close}><X className="h-4 w-4" /></button>
    </div>
    <p id="openalex-consent-explanation" className="text-sm leading-6 text-muted">
      If you opt in, your chosen address is sent to OpenAlex with each scholarly search so OpenAlex can contact you about API usage. This enables its polite pool, with more consistent response times and a separate credit allocation. Declining still allows searches, but under lower shared rate limits. You can change or withdraw this choice later in Settings.
    </p>
    <form className="mt-5 space-y-4" onSubmit={(event) => void save(event)}>
      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-semibold">Choose what to share with OpenAlex</legend>
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-white/70 p-3 text-sm">
          <input type="radio" name="openalex-choice" value="account" checked={choice === "account"} onChange={() => { setChoice("account"); setAgreed(false); }} className="mt-1" />
          <span>Use my account email <span className="block break-all text-muted">{accountEmail}</span></span>
        </label>
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-white/70 p-3 text-sm">
          <input type="radio" name="openalex-choice" value="custom" checked={choice === "custom"} onChange={() => { setChoice("custom"); setAgreed(false); }} className="mt-1" />
          <span>Enter a different address I control</span>
        </label>
        {choice === "custom" ? <label className="block text-sm">Contact email
          <input className="input mt-1" type="email" autoComplete="email" required value={customEmail} onChange={(event) => setCustomEmail(event.target.value)} />
        </label> : null}
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-white/70 p-3 text-sm">
          <input type="radio" name="openalex-choice" value="decline" checked={choice === "decline"} onChange={() => { setChoice("decline"); setAgreed(false); }} className="mt-1" />
          <span>Decline — search without sending an address</span>
        </label>
      </fieldset>
      {choice && choice !== "decline" ? <label className="flex items-start gap-3 text-sm"><input type="checkbox" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} className="mt-1" /><span>I agree to send this address to OpenAlex with each scholarly search.</span></label> : null}
      {error ? <p role="alert" className="rounded-xl bg-rose/10 p-3 text-sm text-rose">{error}</p> : null}
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-primary" disabled={busy || !choice || (choice !== "decline" && !agreed)}>{busy ? "Saving…" : choice === "decline" ? "Continue without sharing" : "Save my choice"}</button>
        <button className="btn" type="button" onClick={close}>{firstSignIn ? "Not now" : "Cancel"}</button>
      </div>
    </form>
  </dialog>;
}
