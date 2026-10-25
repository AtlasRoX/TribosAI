export interface UnitsAudit {
  checked: number;
  consistent: number;
  inconsistent: { statement: string; lhs_dim?: string; rhs_dim?: string; reason?: string }[];
  not_evaluated: number;
}

export function unitsSummary(units?: Partial<UnitsAudit>): string {
  return units && typeof units.checked === "number" && Array.isArray(units.inconsistent)
    ? `Units: ${units.checked} checked, ${units.inconsistent.length} inconsistent` : "";
}
