"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { readWorkspaceState, workspaceStorageKey } from "./workspace-state";

const UserContext = createContext<string | null>(null);
const STORAGE_ERROR_EVENT = "research-workspace-storage-error";

export function WorkspaceStateProvider({ userId, children }: { userId: string; children: ReactNode }) {
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const listener = (event: Event) => setError((event as CustomEvent<string>).detail);
    window.addEventListener(STORAGE_ERROR_EVENT, listener);
    return () => window.removeEventListener(STORAGE_ERROR_EVENT, listener);
  }, []);
  return <UserContext.Provider value={userId}>
    {error ? <div role="alert" className="mx-4 my-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber/30 bg-amber/10 p-3 text-sm">
      <span>{error} Keep this page open to retain your current work.</span>
      <button type="button" className="btn py-1" onClick={() => setError(null)}>Dismiss</button>
    </div> : null}
    {children}
  </UserContext.Provider>;
}

export function useWorkspaceState<T>(
  spaceId: string, module: string, initial: T, validate: (value: unknown) => value is T,
): [T, Dispatch<SetStateAction<T>>, boolean] {
  const userId = useContext(UserContext);
  if (!userId) throw new Error("Workspace state requires an authenticated user.");
  const key = workspaceStorageKey(userId, spaceId, module);
  const [defaults] = useState(() => ({ initial, validate }));
  const [entry, setEntry] = useState<{ key: string; value: T; ready: boolean }>({ key, value: initial, ready: false });
  const lastSaved = useRef<string | null>(null);
  const storageUnavailable = useRef(false);

  useEffect(() => {
    storageUnavailable.current = false;
    let value = defaults.initial;
    try {
      const raw = window.sessionStorage.getItem(key);
      value = readWorkspaceState(raw, value, defaults.validate);
      lastSaved.current = raw;
    } catch (error) {
      storageUnavailable.current = true;
      console.error("Unable to restore workspace state", error);
      window.dispatchEvent(new CustomEvent(STORAGE_ERROR_EVENT, { detail: "Saved view state could not be restored. Your saved server data is unaffected." }));
    }
    setEntry({ key, value, ready: true });
  }, [defaults, key]);

  useEffect(() => {
    if (!entry.ready || entry.key !== key || storageUnavailable.current) return;
    try {
      const serialized = JSON.stringify(entry.value);
      if (serialized !== lastSaved.current) {
        window.sessionStorage.setItem(key, serialized);
        lastSaved.current = serialized;
      }
    } catch (error) {
      storageUnavailable.current = true;
      console.error("Unable to save workspace state", error);
      window.dispatchEvent(new CustomEvent(STORAGE_ERROR_EVENT, { detail: "This browser cannot save view state for reload recovery." }));
    }
  }, [entry, key]);

  const setValue = useCallback<Dispatch<SetStateAction<T>>>((action) => {
    setEntry((previous) => {
      const current = previous.key === key ? previous.value : defaults.initial;
      return { key, ready: previous.key === key && previous.ready, value: typeof action === "function" ? (action as (value: T) => T)(current) : action };
    });
  }, [defaults, key]);
  return [entry.key === key ? entry.value : defaults.initial, setValue, entry.key === key && entry.ready];
}
