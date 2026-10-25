// Client of the interactive simulation API (app/backend/routers/simulate.py) for the Explore panel.
//
// Every call goes through apiFetch, so the page's onStatus hook sees a 401 and raises the auth banner; the messages
// for rate limits and timeouts are rewritten for a reader who is dragging a slider.

import { type AuthHeaders, type RequestOptions, errorStatus, isAbortError, jsonInit, requestJson, detailOf, ApiError } from "./apiClient.ts";
import type { SimSpec } from "../lib/simulationExplore.ts";

export type SimulateApi = { backendUrl: string; authHeaders: AuthHeaders; options?: RequestOptions };

function post<T>(api: SimulateApi, path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(`${api.backendUrl}/api/simulate${path}`, jsonInit("POST", body, api.authHeaders, { signal }), {
    ...api.options,
    toError: (status, payload) => new ApiError(status, simulateErrorMessage(status, detailOf(payload)), { detail: detailOf(payload), body: payload }),
  });
}

export function simulate(api: SimulateApi, spec: SimSpec, numPoints = 400, signal?: AbortSignal) {
  return post<Record<string, unknown>>(api, "", { ...spec, num_points: numPoints }, signal);
}

export function bifurcation(
  api: SimulateApi,
  req: { spec: SimSpec; parameter: string; start: number; stop: number; steps: number; observable?: string; transient_fraction?: number },
  signal?: AbortSignal,
) {
  return post<Record<string, unknown>>(api, "/bifurcation", req, signal);
}

export function vectorField(
  api: SimulateApi,
  req: { spec: SimSpec; x_var: string; y_var: string; x_range: number[]; y_range: number[]; n?: number },
  signal?: AbortSignal,
) {
  return post<Record<string, unknown>>(api, "/vector_field", req, signal);
}

/** A readable message for a failed simulation call. */
export function simulateErrorMessage(status: number, detail = ""): string {
  switch (status) {
    case 0:
      return "The Tribos backend is unreachable.";
    case 401:
    case 403:
      return "Not authorized: check the access token in Settings.";
    case 404:
      return "This backend has no interactive simulation endpoint (update the server).";
    case 422:
      return detail ? `The inputs were rejected: ${detail}` : "The inputs were rejected.";
    case 429:
      return "Too many simulations at once; wait a moment and move the slider again.";
    case 504:
      return detail || "The simulation took too long; shorten the time span or try a stiff method.";
    default:
      return detail || `The simulation failed (${status}).`;
  }
}

/** The message to show for an error thrown by a call, or null for an abort (a newer request replaced it). */
export function shownError(err: unknown): string | null {
  if (isAbortError(err)) return null;
  if (err instanceof ApiError) return err.message;
  return simulateErrorMessage(errorStatus(err));
}
