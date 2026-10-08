"use client";
import { useEffect, useState } from "react";

export function LongOperation({ startedAt, label }: { startedAt: number; label: string }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  return (
    <div className="rounded-2xl border border-indigo/15 bg-indigo-soft/70 p-4" aria-live="polite">
      <div className="mb-3 flex items-center justify-between text-sm"><span className="font-medium text-indigo-deep">{label}</span><span className="text-muted">{elapsed}s</span></div>
      <div className="progress-sheen relative mb-4 h-2 overflow-hidden rounded-full bg-white" />
      <p className="text-xs text-muted">The request is still open. You can switch modules or chats while waiting; the question will be retained.</p>
    </div>
  );
}
