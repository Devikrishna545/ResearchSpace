/** Shared multi-select helpers for checklists (compare, library, bulk actions). */
export function allSelected(selected: readonly string[], ids: readonly string[]): boolean {
  return ids.length > 0 && ids.every((id) => selected.includes(id));
}

/** Select-all toggle: selects every id, or clears them when all are already selected. Keeps unrelated selections. */
export function toggleAll(selected: readonly string[], ids: readonly string[]): string[] {
  if (allSelected(selected, ids)) return selected.filter((id) => !ids.includes(id));
  return [...new Set([...selected, ...ids])];
}

export function toggleOne(selected: readonly string[], id: string, on = !selected.includes(id)): string[] {
  return on ? (selected.includes(id) ? [...selected] : [...selected, id]) : selected.filter((item) => item !== id);
}

/** Run async work over items with bounded concurrency, collecting settled results in input order. */
export async function mapWithConcurrency<T, R>(items: readonly T[], limit: number, worker: (item: T) => Promise<R>): Promise<PromiseSettledResult<R>[]> {
  const results: PromiseSettledResult<R>[] = new Array(items.length);
  let next = 0;
  async function run() {
    while (next < items.length) {
      const index = next;
      next += 1;
      try {
        results[index] = { status: "fulfilled", value: await worker(items[index]) };
      } catch (reason) {
        results[index] = { status: "rejected", reason };
      }
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, run));
  return results;
}
