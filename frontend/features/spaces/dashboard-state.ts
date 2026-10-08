export function isCurrentSpaceSnapshot(
  request: number,
  latestRequest: number,
  mutationAtRequest: number,
  currentMutation: number
): boolean {
  return request === latestRequest && mutationAtRequest === currentMutation;
}
