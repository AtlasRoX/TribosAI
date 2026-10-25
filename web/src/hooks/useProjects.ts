"use client";

// The research projects the user is a member of (owned and shared), for the sidebar and the project view.
// A server without the projects API marks them unavailable, and the sidebar hides the section instead of erroring.

import { useCallback, useEffect, useRef, useState } from "react";
import { createProject, deleteProject, isFeatureMissing, listProjects, patchProject } from "@/services/agentService";
import { type AuthHeaders, errorMessage } from "@/services/apiClient";
import type { Project, ProjectInput, ProjectPatchInput } from "@/types/agentic";

export function useProjects(backendUrl: string, authHeaders: AuthHeaders) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The page recreates its header helper on every render; the hook reads the latest one through a ref.
  const authRef = useRef(authHeaders);
  useEffect(() => {
    authRef.current = authHeaders;
  });
  const auth: AuthHeaders = useCallback((extra) => authRef.current(extra), []);

  const refresh = useCallback(async () => {
    try {
      setProjects(await listProjects(backendUrl, auth));
      setUnavailable(false);
      setError(null);
    } catch (err) {
      if (isFeatureMissing(err)) setUnavailable(true);
      else setError(errorMessage(err, "Projects could not be loaded."));
    }
  }, [backendUrl, auth]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(async (input: ProjectInput) => {
    const p = await createProject(backendUrl, auth, input);
    await refresh();
    return p;
  }, [backendUrl, auth, refresh]);

  const update = useCallback(async (id: string, patch: ProjectPatchInput) => {
    const p = await patchProject(backendUrl, auth, id, patch);
    await refresh();
    return p;
  }, [backendUrl, auth, refresh]);

  const remove = useCallback(async (id: string) => {
    await deleteProject(backendUrl, auth, id);
    await refresh();
  }, [backendUrl, auth, refresh]);

  return { projects, unavailable, error, refresh, create, update, remove, auth };
}
