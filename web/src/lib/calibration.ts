export interface CalibrationSeries {
  time?: number[];
  observed?: (number | null)[];
  simulated?: (number | null)[];
}

export function calibrationResiduals(series: CalibrationSeries): { x: number; y: number }[] {
  return (series.time ?? []).flatMap((x, i) => {
    const observed = series.observed?.[i];
    const simulated = series.simulated?.[i];
    return typeof observed === "number" && typeof simulated === "number" &&
      Number.isFinite(x) && Number.isFinite(observed) && Number.isFinite(simulated)
      ? [{ x, y: observed - simulated }] : [];
  });
}
