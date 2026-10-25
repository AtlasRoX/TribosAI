/** Recognises engineering units typed in a question and names the quantity each one measures. */

const UNITS: [RegExp, string, string][] = [
  [/\bN\s*[·*.]?\s*s\s*\/\s*m\b/, "N·s/m", "damping coefficient"],
  [/\bN\s*\/\s*m\b(?!\s*[²2^])/, "N/m", "spring stiffness"],
  [/\bN\s*[·*.]?\s*m\b/, "N·m", "torque or moment"],
  [/\bkg\s*[·*.]?\s*m(?:\^?2|²)\b/, "kg·m²", "moment of inertia"],
  [/\bkg\s*\/\s*m(?:\^?3|³)\b/, "kg/m³", "density"],
  [/\bPa\s*[·*.]?\s*s\b/, "Pa·s", "dynamic viscosity"],
  [/\bm(?:\^?2|²)\s*\/\s*s\b/, "m²/s", "kinematic viscosity or diffusivity"],
  [/\bW\s*\/\s*\(?\s*m\s*[·*.]?\s*K\s*\)?/, "W/(m·K)", "thermal conductivity"],
  [/\bW\s*\/\s*\(?\s*m(?:\^?2|²)\s*[·*.]?\s*K\s*\)?/, "W/(m²·K)", "heat transfer coefficient"],
  [/\bJ\s*\/\s*\(?\s*kg\s*[·*.]?\s*K\s*\)?/, "J/(kg·K)", "specific heat capacity"],
  [/\brad\s*\/\s*s\b/, "rad/s", "angular frequency"],
  [/\bm\s*\/\s*s(?:\^?2|²)\b/, "m/s²", "acceleration"],
  [/\bm\s*\/\s*s\b(?![²2^])/, "m/s", "velocity"],
  [/\b(?:k|M|G)?Pa\b/, "Pa", "pressure or stress"],
  [/\b(?:k|M)?N\b(?![\s·*./]*[a-zA-Z])/, "N", "force"],
  [/\b(?:k|M)?W\b(?!\s*\/)/, "W", "power"],
  [/\b(?:k|M)?J\b(?!\s*\/)/, "J", "energy"],
  [/\bHz\b/, "Hz", "frequency"],
  [/\bΩ|\bohms?\b/i, "Ω", "electrical resistance"],
  [/\b(?:m|µ|u)?F\b(?=\s*(?:capacitor|capacitance|,|\.|$))/, "F", "capacitance"],
  [/\b(?:m|µ|u)?H\b(?=\s*(?:inductor|inductance|,|\.|$))/, "H", "inductance"],
  [/\bV\b(?=[\s,.)]|$)/, "V", "voltage"],
  [/\b(?:m)?A\b(?=\s*(?:current|,|\.|$))/, "A", "current"],
]

export interface UnitHint {
  unit: string;
  quantity: string;
}

/** Up to `limit` recognised units in the text, each once, in the order they first appear. */
export function unitHints(text: string, limit = 4): UnitHint[] {
  const found: { at: number; hint: UnitHint }[] = [];
  const seen = new Set<string>();
  let rest = text;
  for (const [re, unit, quantity] of UNITS) {
    const m = re.exec(rest);
    if (!m || seen.has(unit)) continue;
    seen.add(unit);
    found.push({ at: m.index, hint: { unit, quantity } });
    // A compound unit is not also read as its parts ("N·s/m" is not also "N/m" or "N").
    rest = rest.slice(0, m.index) + " ".repeat(m[0].length) + rest.slice(m.index + m[0].length);
  }
  return found.sort((a, b) => a.at - b.at).slice(0, limit).map((f) => f.hint);
}
