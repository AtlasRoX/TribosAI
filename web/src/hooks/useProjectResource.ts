"use client";

// Loads one part of a project (members, files, memory, activity) and says whether the server supports it: a route the
// server lacks (agentService.isFeatureMissing) hides that part with a notice instead of an error.

import { useCallback, useEffect, useState } from "react";
import { isFeatureMissing } from "@/services/agentService";
import { errorMessage } from "@/services/apiClient";

export type ResourceState<T> = {
  data: T | null;
  error: string | null;
  unavailable: boolean;
  loading: boolean;
  reload: () => Promise<void>;
};

/** The state of a resource loaded by `load`; errors are classified with `classifyLoadError`. */
export function classifyLoadError(err: unknown): { unavailable: boolean; error: string | null } {
  return isFeatureMissing(err) ? { unavailable: true, error: null } : { unavailable: false, error: errorMessage(err, "Could not load.") };
}

export function useProjectResource<T>(load: () => Promise<T>, key: string): ResourceState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await load());
      setError(null);
      setUnavailable(false);
    } catch (err) {
      const c = classifyLoadError(err);
      setUnavailable(c.unavailable);
      setError(c.error);
    } finally {
      setLoading(false);
    }
    // `key` names what is loaded; `load` is a fresh closure on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, unavailable, loading, reload };
}
