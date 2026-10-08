"use client";
import { CheckCircle2, AlertTriangle } from "lucide-react";

export function ConfidenceBadge({ verified, confidence, warning, iterations }: { verified?: boolean | null; confidence?: number | null; warning?: string | null; iterations?: number | null }) {
  const low = Boolean(warning) || (typeof confidence === "number" && confidence < 0.55) || verified === false;
  return (
    <div className={`inline-flex max-w-full items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${low ? "border-amber/30 bg-amber/10 text-amber" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`} title={warning ?? undefined}>
      {low ? <AlertTriangle className="h-4 w-4 shrink-0" /> : <CheckCircle2 className="h-4 w-4 shrink-0" />}
      <span>{verified ? "Verified" : low ? "Low confidence" : "Grounded"}</span>
      {typeof confidence === "number" ? <span>{Math.round(confidence * 100)}%</span> : null}
      {typeof iterations === "number" ? <span>· {iterations} iteration{iterations === 1 ? "" : "s"}</span> : null}
    </div>
  );
}
