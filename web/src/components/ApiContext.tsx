"use client";

// The backend URL, the bearer-header helper and the page's request options (the auth-banner hook), for result cards
// that call the API themselves (the simulation Explore panel). Null outside the page: such a card then hides its
// interactive parts.

import { createContext, useContext } from "react";
import type { SimulateApi } from "@/services/simulateService";

export const ApiContext = createContext<SimulateApi | null>(null);

export function useApi(): SimulateApi | null {
  return useContext(ApiContext);
}
