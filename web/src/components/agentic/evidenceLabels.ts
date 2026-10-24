// Reader-facing names for evidence keys ("agent.gaps.4.archivon" -> "Scholarly literature (gap search)"). The backend sends
// `evidence_labels` next to `evidence_keys` when it can; this is the fallback for keys without one.

/** Public names of tool and source keys (mirrors tribos/sources/names.py `public`). */
export const SOURCE_NAMES: Record<string, string> = {
  archivon: "Scholarly literature",
  axiom: "SymPy symbolic engine",
  dynamis: "SciPy numerical solver",
  calcula: "Python computation",
  physis: "CODATA / Pint / OEIS",
  websurfer: "web search",
  arxiv: "arXiv",
  s2: "Semantic Scholar",
  semantic_scholar: "Semantic Scholar",
  openalex: "OpenAlex",
  crossref: "Crossref",
  zbmath: "zbMATH",
  ads: "NASA ADS",
  nasa_ads: "NASA ADS",
  oeis: "OEIS",
  codata: "NIST CODATA 2022",
  materials_project: "Materials Project",
  mp: "Materials Project",
  wolfram: "Wolfram|Alpha",
  wikipedia: "Wikipedia",
  pint: "Pint units",
  sympy: "SymPy",
  scipy: "SciPy",
  europepmc: "Europe PMC",
  axiom_simplify: "SymPy simplify",
  axiom_solve: "SymPy solve",
  axiom_calculus: "SymPy calculus",
  axiom_dsolve: "SymPy ODE solver",
  axiom_linalg: "SymPy linear algebra",
  axiom_verify_identity: "SymPy identity check",
  dynamis_ode: "SciPy ODE trajectory",
  dynamis_bvp: "SciPy BVP solver",
  dynamis_equilibrium: "Equilibrium & Jacobian",
  dynamis_optimize: "SciPy optimization",
  dynamis_scan: "Parameter sweep",
  physis_constant: "NIST CODATA 2022",
  physis_convert: "Pint unit conversion",
  physis_dimensions: "Dimensional analysis",
  physis_oeis: "OEIS",
  physis_material: "Materials Project",
};

/** Reader-facing labels for the 6-tier Tribos evidence hierarchy. */
export const EVIDENCE_TIER_LABELS: Record<string, string> = {
  formal_proof: "Formal / symbolic proof",
  established_theory: "Established theory / reference",
  peer_reviewed: "Peer-reviewed literature",
  preprint: "Preprint",
  verified_computation: "Verified computation",
  heuristic: "Heuristic / approximation",
};

const PHASE_NAMES: Record<string, string> = {
  gaps: "gap search",
  plan_execute: "plan step",
  plan_join: "plan step",
  supervisor: "supervisor",
  swarm: "swarm",
  debate: "debate",
  counter_evidence: "counter-evidence",
  counter_evidence_recheck: "counter-evidence",
  hypothesis: "hypothesis test",
  calibrate: "calibration",
  analyst: "analysis",
  decompose: "decomposition",
};

const AGENT_KEY_RE = /^agent\.([a-z_]+)\.(\d+)\.([A-Za-z0-9_-]+)$/;

/** Public name of a tool or source key; the key, readable, when unknown. */
export function sourceName(key: string): string {
  const k = key.trim();
  const lower = k.toLowerCase();
  return SOURCE_NAMES[lower] || SOURCE_NAMES[lower.split("_")[0]] || k.replace(/_/g, " ");
}

/** "agent.gaps.4.archivon" -> "Scholarly literature (gap search)"; "tool:arxiv" -> "arXiv"; "oeis" -> "OEIS".
 * Citation-like keys ("ARXIV:2309.17452", "DOI:...") are returned unchanged. */
export function prettyEvidenceKey(key: unknown): string {
  const k = typeof key === "string" ? key.trim() : String(key ?? "").trim();
  if (!k) return "";
  const m = AGENT_KEY_RE.exec(k);
  if (m) {
    const where = PHASE_NAMES[m[1]] || m[1].replace(/_/g, " ");
    return `${sourceName(m[3])} (${where})`;
  }
  const bare = k.startsWith("tool:") ? k.slice(5) : k;
  return bare && !bare.includes(":") ? sourceName(bare) : k;
}

/** Display names for `keys`: the backend's parallel `labels` where present, else the prettified key. Duplicate
 * names collapse to one ("Scholarly literature (gap search)" twice reads once). */
export function evidenceDisplayNames(keys: unknown, labels?: unknown): string[] {
  const ks = Array.isArray(keys) ? keys : [];
  const ls = Array.isArray(labels) ? labels : [];
  const out: string[] = [];
  ks.forEach((k, i) => {
    const given = typeof ls[i] === "string" ? (ls[i] as string).trim() : "";
    const name = given || prettyEvidenceKey(k);
    if (name && !out.includes(name)) out.push(name);
  });
  return out;
}
