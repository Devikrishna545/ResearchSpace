"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api/client";
import type { PaperStatus } from "@/lib/types";
import { mapWithConcurrency } from "@/lib/utils/selection";
import { readIngestionStatus } from "./library-state";

/** A failed status request is not a failed ingestion. Keep polling until the server confirms. */
export function useIngestionPolling(
  paperIds: string[],
  onStatus: (paperId: string, status: PaperStatus) => void,
  onError: (paperId: string, message: string) => void,
) {
  const callbacks = useRef({ onStatus, onError });
  useEffect(() => { callbacks.current = { onStatus, onError }; }, [onStatus, onError]);
  const key = JSON.stringify([...new Set(paperIds)].sort());
  useEffect(() => {
    const ids = JSON.parse(key) as string[];
    if (!ids.length) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      await mapWithConcurrency(ids, 3, async (id) => {
        if (cancelled) return;
        const outcome = await readIngestionStatus(id, api.paperStatus);
        if (cancelled) return;
        if (outcome.response) callbacks.current.onStatus(id, outcome.response);
        else callbacks.current.onError(id, outcome.error);
      });
      if (!cancelled) timer = setTimeout(() => void poll(), 2500);
    }
    timer = setTimeout(() => void poll(), 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [key]);
}
