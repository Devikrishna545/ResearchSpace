"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, AuthStatus, setCsrfToken } from "@/lib/api/client";
import { AccountSettings } from "./account-settings";
import { LegacyNotifications } from "./legacy-notifications";
import { OpenAlexConsentDialog } from "@/features/discovery/components/openalex-consent-dialog";
import { BrandAuth, BrandWordmark } from "@/components/ui/brand";
import { WorkspaceStateProvider } from "@/features/spaces/use-workspace-state";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Request failed. Please try again.";
}

export function AuthShell({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dismissedConsentFor, setDismissedConsentFor] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setStatus(await api.authStatus());
    } catch (err) {
      setStatus(null);
      setCsrfToken(null);
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const expired = () => {
      setStatus((previous) => previous ? { ...previous, authenticated: false, user: null, csrf_token: null } : null);
      void refresh();
    };
    window.addEventListener("research-auth-expired", expired);
    return () => window.removeEventListener("research-auth-expired", expired);
  }, [refresh]);

  async function authenticate(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setDismissedConsentFor(null);
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!status) return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-5">
      <div className="panel w-full p-8">
        <h1 className="text-3xl"><BrandWordmark /></h1>
        {error ? <><p role="alert" className="mt-4 text-sm text-rose">{error}</p><button className="btn mt-5" onClick={() => void refresh()}>Retry connection</button></> : <p className="mt-4 text-muted">Checking your session…</p>}
      </div>
    </main>
  );

  if (!status.authenticated) return (
    <AuthForm
      setup={status.setup_required}
      busy={busy}
      error={error}
      onSubmit={(token, email, password) => authenticate(() => status.setup_required ? api.bootstrap(token, email, password) : api.login(email, password))}
    />
  );

  if (!status.user) return <main className="p-8"><p role="alert">Your session has no account information. Please sign in again.</p><button className="btn mt-4" onClick={() => void authenticate(api.logout)}>Sign out</button></main>;

  return <WorkspaceStateProvider key={status.user.id} userId={status.user.id}>
    <header className="relative z-50 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-white/70 px-5 py-2 text-sm md:px-10">
      <BrandWordmark className="text-lg" />
      <div className="flex items-center gap-2">
        <LegacyNotifications warning={status.legacy_warning} userId={status.user.id} />
        {status.user ? <AccountSettings user={status.user} consent={status.openalex_consent} busy={busy} onConsentChanged={refresh} onLogoutAll={() => authenticate(api.logoutAll)} /> : null}
        <button className="btn" disabled={busy} onClick={() => void authenticate(api.logout)}>Log out</button>
      </div>
      {error ? <p role="alert" className="w-full text-rose">{error}</p> : null}
    </header>
    {children}
    {status.user && status.openalex_consent?.state === "unset" && dismissedConsentFor !== status.user.id ?
      <OpenAlexConsentDialog
        accountEmail={status.user.email}
        firstSignIn
        onSaved={refresh}
        onClose={() => setDismissedConsentFor(status.user?.id ?? null)}
      /> : null}
  </WorkspaceStateProvider>;
}

function AuthForm({ setup, busy, error, onSubmit }: {
  setup: boolean;
  busy: boolean;
  error: string | null;
  onSubmit: (token: string, email: string, password: string) => Promise<void>;
}) {
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onSubmit(token.trim(), email.trim(), password);
  }
  return <main className="mx-auto flex min-h-screen max-w-lg items-center px-5">
    <form className="panel w-full space-y-5 p-8" onSubmit={submit}>
      <div><div className="mb-6"><BrandAuth /></div><h1 className="font-serif text-3xl">{setup ? "Set up your account" : "Welcome back"}</h1>
        <p className="mt-2 text-sm text-muted">{setup ? "Use your one-time setup token to create the first administrator." : "Sign in to open your research spaces."}</p></div>
      {setup ? <label className="block text-sm font-medium">Setup token<input className="input mt-2" type="password" autoComplete="off" required value={token} onChange={(event) => setToken(event.target.value)} /></label> : null}
      <label className="block text-sm font-medium">Email<input className="input mt-2" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label className="block text-sm font-medium">Password<input className="input mt-2" type="password" autoComplete={setup ? "new-password" : "current-password"} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {error ? <p role="alert" className="text-sm text-rose">{error}</p> : null}
      <button className="btn btn-primary w-full" disabled={busy}>{busy ? "Please wait…" : setup ? "Create administrator" : "Sign in"}</button>
    </form>
  </main>;
}
