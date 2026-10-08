import type { GroundedFinding, GroundedReport, Note } from "../../lib/types";

export function comparisonContextFindings(report: GroundedReport | null): GroundedFinding[] {
  if (!report) return [];
  const unique = new Map<string, GroundedFinding>();
  for (const section of Object.values(report.sections)) {
    for (const finding of section) {
      if (finding.display_status === "shown" || finding.display_status === "shown_with_caveat") unique.set(finding.finding_id, finding);
    }
  }
  return [...unique.values()];
}

export function recentNotes(notes: Note[]): Note[] {
  return [...notes].sort((a, b) => (b.updated_at || b.created_at || "").localeCompare(a.updated_at || a.created_at || "")).slice(0, 4);
}
