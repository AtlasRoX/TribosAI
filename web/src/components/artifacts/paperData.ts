// Data shaping for the paper card (PaperArtifact.tsx), free of React so node tests can import it.
//
// The backend (tribos/papers, tribos/extensions/papers.py) sends execution_artifacts.paper_reproduction: the paper's
// metadata, its extracted equations, ODEs and parameters, and (after archivon_reproduce_paper) one row per stated
// result with a status.

export type PaperSource = { page?: number; line?: string; ocr?: boolean };
export type PaperEquation = PaperSource & { lhs?: string; state?: string; rhs?: string; latex?: string | null; number?: string | null };
export type PaperParameter = PaperSource & { name?: string; value?: number; unit?: string; as_written?: string; stated_result?: boolean };
export type ClaimStatus = "reproduced" | "differs" | "not_reproducible";
export type PaperClaim = PaperSource & {
  name?: string;
  stated?: number;
  unit?: string;
  status?: ClaimStatus;
  computed?: number;
  stated_si?: number;
  relative_difference?: number;
  missing?: string[];
  reason?: string;
  equation?: string;
  equation_page?: number;
  notes?: string[];
};
export type PaperData = {
  paper?: { title?: string | null; authors?: string | null; doi?: string | null; arxiv_id?: string | null; n_pages?: number; file?: string };
  equations?: PaperEquation[];
  odes?: PaperEquation[];
  parameters?: PaperParameter[];
  claims?: PaperClaim[];
  stated_results?: PaperParameter[];
  counts?: Partial<Record<ClaimStatus, number>>;
  note?: string;
};

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function paperData(data: unknown): PaperData | null {
  return data && typeof data === "object" && "paper" in data ? (data as PaperData) : null;
}

export const STATUS_LABEL: Record<ClaimStatus, string> = {
  reproduced: "reproduced",
  differs: "differs",
  not_reproducible: "not reproducible",
};

export function statusTone(status: unknown): "ok" | "bad" | "warn" | "neutral" {
  return status === "reproduced" ? "ok" : status === "differs" ? "bad" : status === "not_reproducible" ? "warn" : "neutral";
}

/** "3 reproduced · 1 differs · 2 not reproducible", in that order, leaving out zeros. */
export function countsLine(counts: PaperData["counts"]): string {
  return (["reproduced", "differs", "not_reproducible"] as ClaimStatus[])
    .filter((s) => (counts?.[s] ?? 0) > 0)
    .map((s) => `${counts?.[s]} ${STATUS_LABEL[s]}`)
    .join(" · ");
}

/** What the reproduction found for one claim, in words. */
export function claimDetail(c: PaperClaim): string {
  if (c.status === "not_reproducible") {
    return c.missing?.length ? `The paper gives no value for ${c.missing.join(", ")}.` : c.reason || "No equation for it in the paper.";
  }
  if (!finite(c.computed)) return "";
  const pct = finite(c.relative_difference) ? ` (${(c.relative_difference * 100).toPrecision(2)}% apart)` : "";
  return `Recomputed ${Number(c.computed.toPrecision(5))} (SI)${pct}`;
}

/** "p. 3" or "p. 3 (OCR)". */
export function pageRef(s: PaperSource): string {
  return s.page ? `p. ${s.page}${s.ocr ? " (OCR)" : ""}` : "";
}

/** The LaTeX of an equation line: its own LaTeX when the backend converted it, else the verbatim text. */
export function equationTex(e: PaperEquation): { tex: string; converted: boolean } {
  const head = e.state ? `\\frac{d${e.state}}{dt}` : (e.lhs ?? "");
  if (e.latex) return { tex: `${head} = ${e.latex}`, converted: true };
  return { tex: `${e.state ? `d${e.state}/dt` : (e.lhs ?? "")} = ${e.rhs ?? ""}`, converted: false };
}

export function doiUrl(doi: string | null | undefined): string | null {
  return doi && /^10\.\d{4,9}\/\S+$/.test(doi) ? `https://doi.org/${doi}` : null;
}

export function arxivUrl(id: string | null | undefined): string | null {
  return id && /^\d{4}\.\d{4,5}(v\d+)?$/.test(id) ? `https://arxiv.org/abs/${id}` : null;
}
