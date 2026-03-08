import { pushPerfEntry } from "./perf-store";

export async function measureAsyncStep<T>(
  label: string,
  fn: () => Promise<T>,
): Promise<T> {
  const startedAt = performance.now();
  try {
    const result = await fn();
    pushPerfEntry({
      kind: "async",
      label,
      durationMs: performance.now() - startedAt,
    });
    return result;
  } catch (error) {
    pushPerfEntry({
      kind: "async",
      label: `${label} (error)`,
      durationMs: performance.now() - startedAt,
    });
    throw error;
  }
}
