import { ApiError } from "../api/client";
import { useAsync, type AsyncState } from "./useAsync";

export type OptionalState<T> = AsyncState<T> | { status: "unavailable" };

/**
 * `useAsync` for payloads the backend precomputes at publish time (v0.5 importance and summary): a 404 means "not
 * available yet" and is a state of its own, not an error. Any other failure stays an error.
 */
export function useOptionalAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  enabled = true,
): OptionalState<T> & { reload: () => void } {
  const state = useAsync<{ data: T | null }>(
    async (signal) => {
      try {
        return { data: await fn(signal) };
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return { data: null };
        throw error;
      }
    },
    deps,
    enabled,
  );
  if (state.status !== "ok") return state as OptionalState<T> & { reload: () => void };
  return state.data.data === null ? { status: "unavailable", reload: state.reload } : { status: "ok", data: state.data.data, reload: state.reload };
}
