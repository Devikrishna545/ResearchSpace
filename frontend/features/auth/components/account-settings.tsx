"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { KeyRound, LogOut, Settings2, UserPlus } from "lucide-react";
import type { AuthUser, OpenAlexConsent } from "@/lib/api/client";
import { accountInitials, type ThemePreference } from "@/lib/utils/theme";
import { AdminAccountDialog, type AdminAction } from "./admin-account-dialog";
import { OpenAlexConsentDialog } from "@/features/discovery/components/openalex-consent-dialog";
import { useTheme } from "@/components/ui/theme-provider";

export function AccountSettings({ user, consent, busy, onLogoutAll, onConsentChanged }: {
  user: AuthUser;
  consent: OpenAlexConsent | null | undefined;
  busy: boolean;
  onLogoutAll: () => Promise<void>;
  onConsentChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [adminAction, setAdminAction] = useState<AdminAction | null>(null);
  const [openAlexDialog, setOpenAlexDialog] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const { preference, setPreference } = useTheme();
  const isAdmin = user.is_admin || user.role === "admin";
  const closeAdminDialog = useCallback(() => {
    setAdminAction(null);
    trigger.current?.focus();
  }, []);
  const closeOpenAlexDialog = useCallback(() => {
    setOpenAlexDialog(false);
    trigger.current?.focus();
  }, []);

  useEffect(() => {
    const closeForNotifications = () => setOpen(false);
    window.addEventListener("research-notifications-open", closeForNotifications);
    return () => window.removeEventListener("research-notifications-open", closeForNotifications);
  }, []);

  useEffect(() => {
    if (!open) return;
    (dialog.current?.querySelector<HTMLInputElement>('input[name="appearance"]:checked') ?? dialog.current)?.focus();
    function onPointerDown(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function openAdminDialog(action: AdminAction) {
    setOpen(false);
    setAdminAction(action);
  }

  function manageOpenAlex() {
    setOpen(false);
    setOpenAlexDialog(true);
  }

  function toggleSettings() {
    if (!open) window.dispatchEvent(new Event("research-settings-open"));
    setOpen((current) => !current);
  }

  return <div ref={root} className="relative">
    <button ref={trigger} type="button" className="btn gap-2 pl-1.5" aria-haspopup="dialog" aria-expanded={open} aria-controls="account-settings" onClick={toggleSettings}>
      <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-full bg-indigo-soft text-xs font-bold text-indigo-deep">{accountInitials(user.email)}</span>
      <Settings2 className="h-4 w-4" aria-hidden="true" />
      <span>Settings</span>
    </button>
    {open ? <section ref={dialog} id="account-settings" role="dialog" aria-label="Account settings" tabIndex={-1} className="fixed inset-x-4 top-28 z-[90] max-h-[calc(100vh-8rem)] overflow-y-auto rounded-2xl border border-line bg-paper p-5 text-ink shadow-soft sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:max-h-[min(42rem,calc(100vh-5rem))] sm:w-[min(25rem,calc(100vw-2.5rem))]">
      <div className="mb-5 border-b border-line pb-4">
        <p className="eyebrow mb-1">Profile</p>
        <p className="break-all font-medium">{user.email}</p>
        <p className="mt-1 text-xs text-muted">{isAdmin ? "Administrator" : "Member"}</p>
      </div>
      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-semibold">Appearance</legend>
        {(["light", "dark", "system"] as const).map((choice: ThemePreference) =>
          <label key={choice} className="flex cursor-pointer items-center gap-3 rounded-xl border border-line bg-white/70 px-3 py-2 text-sm hover:border-indigo/40">
            <input type="radio" name="appearance" value={choice} checked={preference === choice} onChange={() => setPreference(choice)} />
            <span>{choice === "system" ? "System" : choice === "dark" ? "Dark" : "Light"}</span>
          </label>
        )}
      </fieldset>
      <div className="mt-5 border-t border-line pt-4">
        <h2 className="text-sm font-semibold">OpenAlex contact</h2>
        <p className="mt-1 break-all text-sm text-muted">{consent?.state === "granted" ? `Sharing ${consent.contact_email} with OpenAlex` : consent?.state === "declined" ? "Declined — searching without an address" : "Not decided — searching without an address"}</p>
        <button type="button" className="btn mt-3 w-full justify-start" onClick={manageOpenAlex}>Change or withdraw consent</button>
      </div>
      {isAdmin ? <div className="mt-5 space-y-2 border-t border-line pt-4">
        <h2 className="text-sm font-semibold">Account administration</h2>
        <button type="button" className="btn w-full justify-start" onClick={() => openAdminDialog("create")}><UserPlus className="h-4 w-4" />Create user</button>
        <button type="button" className="btn w-full justify-start" onClick={() => openAdminDialog("reset")}><KeyRound className="h-4 w-4" />Reset user password</button>
      </div> : null}
      <div className="mt-5 border-t border-line pt-4">
        <button className="btn w-full" type="button" disabled={busy} onClick={() => void onLogoutAll()}><LogOut className="h-4 w-4" />Log out everywhere</button>
      </div>
    </section> : null}
    {adminAction && typeof document !== "undefined" ? createPortal(
      <AdminAccountDialog action={adminAction} onClose={closeAdminDialog} />,
      document.body
    ) : null}
    {openAlexDialog && typeof document !== "undefined" ? createPortal(
      <OpenAlexConsentDialog accountEmail={user.email} firstSignIn={false} onSaved={onConsentChanged} onClose={closeOpenAlexDialog} />,
      document.body
    ) : null}
  </div>;
}
