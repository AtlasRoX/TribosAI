/** Thinning a long series for drawing without losing its extremes. */

/**
 * Indices of the samples the path is drawn through: all of them when few, otherwise each bucket's minimum and maximum
 * in time order (plus the last sample), so peaks and troughs are never thinned away.
 */
export function pathIndices(y: number[], maxPoints: number): number[] {
  const finite = (i: number) => Number.isFinite(y[i]);
  if (y.length <= maxPoints) return y.map((_, i) => i).filter(finite);
  const bucket = Math.ceil(y.length / Math.max(1, Math.floor(maxPoints / 2)));
  const out: number[] = [];
  for (let start = 0; start < y.length; start += bucket) {
    let lo = -1;
    let hi = -1;
    for (let i = start; i < Math.min(y.length, start + bucket); i++) {
      if (!finite(i)) continue;
      if (lo < 0 || y[i] < y[lo]) lo = i;
      if (hi < 0 || y[i] > y[hi]) hi = i;
    }
    if (lo < 0) continue;
    out.push(...(lo === hi ? [lo] : lo < hi ? [lo, hi] : [hi, lo]));
  }
  const last = y.length - 1;
  if (finite(last) && out[out.length - 1] !== last) out.push(last);
  if (finite(0) && out[0] !== 0) out.unshift(0);
  return out;
}
