// Compact number display for result cards (AUDIT-021): `digits` decimal places for |v| >= 1, but at least `digits`
// significant figures below 1 (0.0012345 shows as 0.00123, not 0.001), and exponent form outside [1e-3, 1e5).
export function formatNumber(v: number, digits = 3): string {
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(2);
  if (a !== 0 && a < 1) return Number(v.toPrecision(Math.max(1, digits))).toString();
  return Number(v.toFixed(digits)).toString();
}
