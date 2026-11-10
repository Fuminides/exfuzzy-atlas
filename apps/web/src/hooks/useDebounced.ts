import { useEffect, useState } from "react";

/** `value` after it has stopped changing for `ms` (slider drags over thousands of steps must not fire a request per tick). */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return settled;
}
