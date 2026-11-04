/**
 * Intelligent Dynamic Title Generator for Scientific & Engineering Conversations.
 * Extracts clean, high-signal, professional topic titles from raw user prompts.
 */

// Acronyms and names from mathematics, physics, engineering and scientific software that keep their casing.
// Only tokens that are never ordinary English words: a title must not turn "all" or "met" into an acronym.
const PRESERVED_ACRONYMS = new Set([
  "ODE", "ODEs", "PDE", "PDEs", "DAE", "FFT", "DFT", "FEM", "FEA", "CFD", "SVD", "PCA", "QR", "LU", "LQR", "PID", "MPC",
  "RLC", "RC", "RL", "LC", "AC", "DC", "EMF", "RF", "IMU", "GPS", "LiDAR", "MOSFET", "BJT", "LED", "CMOS", "FPGA",
  "GPU", "CPU", "API", "MCP", "DAG", "HDF5", "CSV", "JSON", "SI", "CODATA", "NIST", "IEEE", "ISO", "NASA", "ADS",
  "SymPy", "SciPy", "NumPy", "Pint", "MATLAB", "LaTeX", "arXiv", "OEIS", "zbMATH", "OpenAlex", "WolframAlpha",
  "1D", "2D", "3D", "4D",
]);

// Minor words that stay lowercase in titles (unless first word)
const MINOR_WORDS = new Set([
  "a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "from",
  "by", "with", "in", "of", "vs", "versus"
]);

// Patterns of conversational preamble to strip
const PREAMBLE_PATTERNS = [
  /^(?:hello|hi|hey|good\s+(?:morning|afternoon|evening))\b[,\s.:!]*/i,
  /^(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:help\s+me\s+)?(?:to\s+)?(?:explain|tell\s+me\s+(?:about)?|summarize|analyze|find|give\s+me|show\s+me|list|search|describe|discuss|compare|evaluate|check|provide|run|simulate|look\s+up)\b[,\s:]*/i,
  /^(?:please\s+)?(?:explain|tell\s+me\s+(?:about)?|summarize|analyze|find|give\s+me|show\s+me|list|search|describe|discuss|compare|evaluate|check|provide|run|simulate|look\s+up)\b[,\s:]*/i,
  /^(?:what|how|why|when|where|who)\s+(?:is|are|do|does|did|can|could|would|should|to|about|was|were)\s+/i,
  /^(?:i\s+(?:want|need|would\s+like)\s+to\s+(?:know|understand|learn|find|see|analyze|investigate|explore))\s+(?:about\s+)?/i,
  /^(?:i'm\s+looking\s+for|i\s+am\s+looking\s+for|tell\s+me\s+about|give\s+me\s+a\s+summary\s+of|can\s+we\s+look\s+at|about)\s+/i,
];

const MATH_SYMBOLS: Record<string, string> = {
  cdot: "·", times: "×", le: "≤", leq: "≤", ge: "≥", geq: "≥", neq: "≠", ne: "≠", approx: "≈", int: "∫", sum: "Σ",
  prod: "Π", sqrt: "√", infty: "∞", pi: "π", alpha: "α", beta: "β", gamma: "γ", delta: "δ", theta: "θ", lambda: "λ",
  mu: "μ", sigma: "σ", omega: "ω", partial: "∂", nabla: "∇", to: "→", rightarrow: "→", in: "∈",
};

/** LaTeX as plain text for a title: "$\frac{x^4+2y^2}{6}$" -> "(x^4+2y^2)/6", no "$" signs or backslash commands. */
export function plainMath(text: string): string {
  return (text || "")
    .replace(/\\[[\]()]/g, " ") // display and inline math delimiters: \[ \] \( \)
    .replace(/\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, "($1)/($2)")
    .replace(/\((\w+)\)\//g, "$1/")
    .replace(/\/\((\w+)\)/g, "/$1")
    .replace(/\\(?:left|right|displaystyle)\b/g, "")
    .replace(/\\(?:quad|qquad)\b|\\[,;! ]/g, " ")
    .replace(/\\([A-Za-z]+)/g, (_m, name: string) => MATH_SYMBOLS[name] ?? name)
    .replace(/\\\$/g, "$")
    .replace(/\$\$/g, "")
    // A "$" opening or closing math (not money such as "$60") is dropped.
    .replace(/(?<![\w\\])\$(?!\d)|(?<=[^\s$])\$(?!\d)/g, "")
    .replace(/[{}]/g, "");
}

/**
 * Format a single word for title casing, keeping the casing of known acronyms.
 */
function formatTitleWord(word: string, isFirst: boolean): string {
  // Check exact acronym match or uppercase match
  const upper = word.toUpperCase();
  for (const acr of PRESERVED_ACRONYMS) {
    if (upper === acr.toUpperCase()) {
      return acr;
    }
  }

  // Variables and expressions keep their case: "x = 2", "x^2", "(x^4+2y^2)/6".
  if ((word.length === 1 && /[A-Za-z]/.test(word) && !/^[aAiI]$/.test(word)) || /[\^_=+*/()\d]/.test(word)) {
    return word;
  }

  // Format each part of a hyphenated name (e.g. FFT-based, Runge-Kutta)
  if (word.includes("-")) {
    return word
      .split("-")
      .map((part, i) => formatTitleWord(part, isFirst && i === 0))
      .join("-");
  }

  const lower = word.toLowerCase();
  if (!isFirst && MINOR_WORDS.has(lower)) {
    return lower;
  }

  // If word is already mixed case like SymPy or LaTeX, keep it
  if (/[a-z]/.test(word) && /[A-Z]/.test(word) && word.length > 2) {
    return word;
  }

  // Otherwise standard capitalize
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/**
 * Generates an elegant, high-signal, professional title from a user inquiry.
 * Trims conversational filler, formats into Title Case, and keeps clean lengths.
 */
export function generateDynamicTitle(prompt: string, maxChars = 52): string {
  if (!prompt || typeof prompt !== "string") return "Investigation";

  const clean = plainMath(prompt)
    .replace(/```[\s\S]*?```/g, " ") // remove code blocks
    .replace(/https?:\/\/\S+/g, " ")   // remove URLs
    .replace(/\s+/g, " ")
    .trim();

  if (!clean) return "Investigation";

  // Iteratively strip conversational preambles
  let stripped = clean;
  let changed = true;
  let iterations = 0;
  while (changed && iterations < 4) {
    changed = false;
    iterations++;
    for (const pat of PREAMBLE_PATTERNS) {
      if (pat.test(stripped)) {
        stripped = stripped.replace(pat, "").trim();
        changed = true;
      }
    }
    // Also strip leading articles like "the ", "a ", "an " if remaining text is substantial
    if (/^(?:the|a|an)\s+/i.test(stripped) && stripped.length > 8) {
      stripped = stripped.replace(/^(?:the|a|an)\s+/i, "").trim();
      changed = true;
    }
  }

  // If preamble stripping left very little, fall back to original clean text
  const target = stripped.length >= 3 ? stripped : clean;

  // Clean trailing punctuation: question marks, colons, dashes, ellipses, periods
  const normalized = target
    .replace(/^["'`\s\-_=]+/, "")
    .replace(/[?!:;.,'"'`\s\-_=]+$/, "")
    .trim();

  if (!normalized) return "Investigation";

  // Split into words and format
  const words = normalized.split(/\s+/).filter(Boolean);
  if (words.length === 0) return "Investigation";

  // Format words with domain awareness
  const formattedWords = words.map((w, idx) => formatTitleWord(w, idx === 0));

  // Build title up to maxChars
  let result = "";
  for (const w of formattedWords) {
    const candidate = result ? `${result} ${w}` : w;
    if (candidate.length > maxChars) {
      // If we already have at least 2 words, stop at word boundary
      if (result.split(" ").length >= 2) break;
      // Otherwise allow current word or cut
      result = candidate.slice(0, maxChars).replace(/[,.:;_\-\s]+$/, "");
      break;
    }
    result = candidate;
  }

  // Clean trailing punctuation left by a word-boundary cut ("…Heat Equation,") and trailing minor words
  const trailingCleaned = result
    .replace(/[,.:;\-\s]+$/, "")
    .replace(/\s+(?:in|of|and|for|on|with|to|at|by|a|the|vs)$/i, "")
    .trim();
  const finalTitle = trailingCleaned || result;

  return finalTitle || "Investigation";
}
