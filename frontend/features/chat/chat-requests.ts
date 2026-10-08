/** The API has no cancellation option; bound read-only checks without resending a chat request. */
export async function withChatReadTimeout<T>(request: Promise<T>, timeoutMs = 30_000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      request,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error("Checking saved chat data timed out. Your question is retained; you can try checking again.")), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
