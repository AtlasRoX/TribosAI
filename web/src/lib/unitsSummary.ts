export interface UnitsAudit {
  checked: number;
  consistent: number;
  inconsistent: { statement: string; lhs_dim?: string; rhs_dim?: string; reason?: string }[];
  not_evaluated: number;
}

/** The unit-check coverage, including zero when statements with units went unchecked; nothing for an answer that
 *  states no quantity with units (pure mathematics), where "0 checked, 0 inconsistent" would only be noise. */
export function unitsSummary(units?: Partial<UnitsAudit>): string {
  if (!units || typeof units.checked !== "number" || !Array.isArray(units.inconsistent)) return "";
  if (units.checked === 0 && units.inconsistent.length === 0 && !units.not_evaluated) return "";
  return `Units: ${units.checked} checked, ${units.inconsistent.length} inconsistent`;
}
