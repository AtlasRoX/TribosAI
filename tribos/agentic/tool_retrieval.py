"""
Tool retrieval: choose the few registry tools a planner should see for a (sub-)question.

- Each tool document is its name, description, domain, tags and argument names, expanded at index time with
  synthetic intent phrases per domain and per known tool (Re-Invoke, Chen et al., Findings EMNLP 2024,
  arXiv:2408.01875; Toolshed's pre-retrieval tool enrichment, Lumer et al. 2024, arXiv:2410.14594).
- The query is expanded with a small biomedical intent lexicon before ranking (Toolshed's intra-retrieval
  query rewriting and expansion), with the expansion terms weighted below the user's own words.
- Ranking is BM25 over two views of each tool (the full document, and an "intent view" of name, tags and
  synthetic queries only), fused by reciprocal rank with an optional dense ranking from a locally cached
  sentence-transformers model (TRIBOS_TOOL_EMBEDDINGS=<model id>; never downloaded at query time). This is
  the API-retriever step of ToolLLM (Qin et al., ICLR 2024, arXiv:2307.16789) and the Tool Finder of
  ToolUniverse (Gao et al. 2025, arXiv:2509.23426), done lexically: ToolRet (Shi et al., ACL 2025,
  arXiv:2503.01763) shows generic embedders are weak on tool retrieval, so the lexical ranking is the default
  and recall@k is measured on our own catalogue by tests/test_tool_retrieval.py.
- tool_card() is the compact, schema-accurate description shown to planners (Gorilla, Patil et al.,
  NeurIPS 2024, arXiv:2305.15334: ground calls in the tool's own documentation).

Public API (used by other packages; keep stable): retrieve_tools, tool_card, tool_document, recall_at_k,
tokenize, DOMAIN_INTENTS.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by for from has have in into is it its of on or that the to was were will with what which "
    "how does do can this these those via using use".split()
)

# Domain intent phrases used to expand tool documents (synthetic queries per domain).
DOMAIN_INTENTS: dict[str, str] = {
    "archivon": "literature papers preprints publications arxiv zbmath crossref openalex semantic scholar ads citations bibliography review",
    "axiom": "symbolic mathematics algebra calculus simplify solve equation differential equation ode dsolve linear algebra matrix eigenvalues determinant proof identity latex sympy",
    "dynamis": "numerical simulation ode system initial value problem trajectory equilibrium steady state jacobian stability eigenvalues parameter scan sensitivity sweep bifurcation optimize minimize root find fit parameters",
    "calcula": "scientific computing sandbox python numpy scipy sympy mpmath pandas dataset csv tsv hdf5 mat table statistics regression plot",
    "analysis": "scientific computing sandbox python numpy scipy sympy mpmath pandas dataset csv tsv hdf5 mat table statistics regression plot",
    "physis": "reference data fundamental physical constants codata unit conversion dimensional analysis pint oeis integer sequences materials project crystal band gap formation energy wolfram alpha mathematical encyclopedia wikipedia",
    "websurfer": "web search online documentation recent pages websites",
    "lithoscribe": "literature papers publications evidence arxiv abstract citations review",
    "vivarix": "simulate ode model time course steady state parameter scan dynamics",
    "general": "",
}

# Synthetic queries per known tool (Re-Invoke: written once at index time, not per request). Tools not listed
# here are still indexed from their own description, tags and argument names.
TOOL_INTENTS: dict[str, str] = {
    "archivon_literature_search": "find papers preprints publications literature evidence studies arxiv zbmath crossref openalex semantic scholar abstracts citations review what is known",
    "archivon_paper_details": "look up paper metadata abstract authors citations references by arxiv id doi zbmath id semantic scholar id",
    "archivon_recommend": "recommend related papers similar publications citation graph recommendations for a paper",
    "axiom_simplify": "simplify algebraic trigonometric logarithmic exponential expression factor expand collect cancel rationalise",
    "axiom_solve": "solve algebraic equation system of equations polynomial roots symbolic solution exact closed form",
    "axiom_calculus": "compute derivative differentiate integral integrate definite indefinite limit taylor series laurent series expansion residue",
    "axiom_dsolve": "solve ordinary differential equation ode symbolic closed form general solution initial value problem boundary conditions",
    "axiom_linalg": "symbolic linear algebra matrix determinant inverse rank nullspace columnspace eigenvalues eigenvectors characteristic polynomial jordan form",
    "axiom_verify_identity": "verify mathematical identity prove algebraic trigonometric equivalence symbolic simplification zero test",
    "axiom_latex": "convert expression to latex parse latex into symbolic math canonical form",
    "axiom_nsolve": "numeric fallback without a closed form scans an interval for every real root refines with findroot residual checked x equals cos x",
    "axiom_optimize": "maximum minimum maximize minimize extrema global optimum critical points on an interval largest smallest value",
    "axiom_inequality": "solve inequality less than greater than solution intervals sign chart where is the function positive negative",
    "axiom_tangent": "tangent line normal line slope of the curve at a point derivative at x equals a",
    "axiom_vector_calculus": "gradient divergence curl laplacian hessian jacobian of a scalar or vector field partial derivatives",
    "axiom_transform": "laplace transform inverse laplace fourier transform frequency domain transfer function signal",
    "axiom_nintegrate": "numerical definite integral quadrature no closed form approximate value of an integral",
    "axiom_number_theory": "prime factorization is it prime gcd lcm greatest common divisor modular arithmetic inverse mod chinese remainder totient",
    "axiom_recurrence": "solve recurrence relation closed form fibonacci sequence difference equation a n",
    "axiom_probability": "probability distribution normal binomial poisson exponential expected value variance cdf quantile",
    "calcula_statistics": "statistics mean median standard deviation t test p value linear regression correlation confidence interval of data",
    "axiom_interval_verify": "rigorous interval arithmetic certified bound prove f positive on an interval box guaranteed enclosure validated numerics",
    "axiom_precision_check": "floating point precision loss catastrophic cancellation rounding error high precision digits numerically stable",
    "axiom_counterexample_search": "find a counterexample test a conjecture falsify claim check identity inequality for all n exhaustive search primes",
    "calcula_cross_validate": "replicate a computation two independent implementations compare results cross check reproduce numbers agree",
    "calcula_distribution_tests": "normality test shapiro wilk anderson darling kolmogorov skewness kurtosis bootstrap confidence interval qq plot distribution",
    "axiom_solve_problem": "solve a complete math question end to end bounded tool loop independent verifier re checks the answer verified result",
    "dynamis_simulate_ode": "simulate ordinary differential equation ode system initial value problem ivp time course trajectory dynamics phase portrait rk45 bdf radau",
    "dynamis_equilibrium": "find equilibrium points fixed points steady state jacobian eigenvalues linear stability analysis hyperbolic saddle node",
    "dynamis_parameter_scan": "vary a parameter sensitivity analysis parameter sweep bifurcation continuation response curve",
    "dynamis_optimize": "numerical optimization minimize maximize objective function constrained unconstrained bounds nonlinear programming",
    "dynamis_fit_parameters": "fit model parameters to experimental data curve fitting nonlinear least squares parameter estimation calibration residuals",
    "dynamis_root_find": "find numerical roots zeros of nonlinear equation or system of equations brentq newton fsolve",
    "calcula_run_python": "execute python code in scientific sandbox numpy scipy sympy mpmath networkx pint pandas stats plot table verification",
    "calcula_describe_dataset": "inspect attached dataset csv tsv hdf5 mat parquet columns shape summary statistics missing values preview",
    "analysis_run_python": "execute python code in scientific sandbox analyse attached data statistics regression plot table csv",
    "physis_constants": "look up fundamental physical constants codata value uncertainty units planck boltzmann speed of light gravitational avogadro electron mass",
    "physis_units": "convert physical units check dimensional consistency si base units pint dimensional analysis",
    "physis_oeis": "search oeis online encyclopedia of integer sequences sequence terms formula recurrence generating function",
    "physis_materials": "query materials project crystal structure band gap formation energy hull stability density symmetry space group",
    "physis_wolfram": "query wolfram alpha computational knowledge engine formula evaluation special functions reference data",
    "physis_encyclopedia": "search mathematical and scientific encyclopedia definitions theorems proof sketches wikipedia reference",
    "axiom_formal_check": "formal proof check lean theorem prover verify proof compile mathlib formalisation",
    "archivon_read_paper": "read uploaded attached paper pdf extract equations parameters results sections title doi page",
    "archivon_reproduce_paper": "reproduce verify check uploaded paper pdf results claims recompute equations parameters ode reproducibility",
    "physis_engineering_calc": "engineering design calculation beam deflection bending stress cantilever simply supported column buckling euler johnson pressure vessel hoop stress wall thickness asme shaft torsion von mises bolt preload torque fatigue goodman miner endurance pipe pressure drop friction factor colebrook heat exchanger lmtd ntu effectiveness insulation wall conduction u-value safety factor utilisation material steel aluminium",
    "physis_list_calculators": "list engineering calculators available inputs units materials table catalog",
    "physis_propagate_uncertainty": "propagate uncertainty error propagation tolerance measurement uncertainty gum monte carlo combined standard uncertainty tolerance stack error budget contribution",
    "dynamis_solve_pde": "solve partial differential equation heat diffusion wave equation poisson laplace advection diffusion reaction diffusion burgers fisher kpp finite difference boundary conditions initial condition numerical scheme grid convergence",
    "websurfer_search": "search the web online pages documentation websites",
    "lithoscribe_literature_synthesis": "find papers publications literature evidence studies abstracts citations review",
}

# Query expansion lexicon (Toolshed's query rewriting): a query word -> tool-vocabulary terms. Keys are prefixes
# of the raw query word; values are added to the query at a lower weight.
QUERY_EXPANSIONS: dict[str, str] = {
    "paper": "archivon_literature_search literature arxiv publications archivon_read_paper uploaded paper",
    "publication": "archivon_literature_search literature arxiv",
    "article": "archivon_literature_search literature",
    "preprint": "archivon_literature_search arxiv literature",
    "arxiv": "archivon_literature_search archivon_paper_details arxiv literature",
    "zbmath": "archivon_literature_search zbmath literature",
    "doi": "archivon_paper_details archivon_literature_search doi",
    "cite": "archivon_paper_details archivon_recommend citations",
    "citation": "archivon_paper_details archivon_recommend citations",
    "recommend": "archivon_recommend related papers",
    "related": "archivon_recommend related papers",
    "literature": "archivon_literature_search papers",
    "study": "archivon_literature_search literature",
    "review": "archivon_literature_search literature",
    "simplif": "axiom_simplify symbolic algebraic",
    "factor": "axiom_simplify algebraic",
    "expand": "axiom_simplify axiom_calculus series",
    "solv": "axiom_solve dynamis_root_find equation roots",
    "root": "axiom_solve dynamis_root_find zeros polynomial",
    "zero": "dynamis_root_find axiom_solve roots",
    "transcend": "axiom_nsolve numeric roots",
    "findroot": "axiom_nsolve numeric roots",
    "verifi": "axiom_solve_problem axiom_verify_identity verified",
    "verified": "axiom_solve_problem verified answer",
    "polynom": "axiom_solve roots algebraic",
    "integr": "axiom_calculus integrate integral calculus",
    "deriv": "axiom_calculus differentiate derivative calculus",
    "differenti": "axiom_calculus axiom_dsolve derivative differential",
    "limit": "axiom_calculus limit calculus",
    "series": "axiom_calculus taylor series expansion",
    "taylor": "axiom_calculus taylor series",
    "laurent": "axiom_calculus laurent series",
    "residu": "axiom_calculus residue complex",
    "ode": "dynamis_simulate_ode axiom_dsolve differential equation",
    "ivp": "dynamis_simulate_ode initial value problem",
    "dsolve": "axiom_dsolve differential equation",
    "eigen": "axiom_linalg dynamis_equilibrium eigenvalues eigenvectors matrix",
    "matrix": "axiom_linalg linear algebra determinant inverse",
    "matrices": "axiom_linalg linear algebra",
    "determin": "axiom_linalg determinant matrix",
    "nullspac": "axiom_linalg nullspace rank matrix",
    "rank": "axiom_linalg rank matrix",
    "jordan": "axiom_linalg jordan matrix",
    "identit": "axiom_verify_identity equivalence proof",
    "prove": "axiom_verify_identity proof theorem",
    "proof": "axiom_verify_identity theorem",
    "equiv": "axiom_verify_identity simplify",
    "latex": "axiom_latex tex",
    "simulat": "dynamis_simulate_ode simulation ode trajectory dynamics",
    "trajector": "dynamis_simulate_ode simulation ode",
    "dynamic": "dynamis_simulate_ode dynamis_equilibrium dynamics",
    "equilibr": "dynamis_equilibrium fixed point steady state stability",
    "steady": "dynamis_equilibrium steady_state equilibrium",
    "stabil": "dynamis_equilibrium jacobian eigenvalues stability",
    "jacobian": "dynamis_equilibrium stability eigenvalues",
    "bifurcat": "dynamis_parameter_scan dynamis_equilibrium bifurcation",
    "scan": "dynamis_parameter_scan parameter sweep sensitivity",
    "sweep": "dynamis_parameter_scan parameter scan",
    "sensitiv": "dynamis_parameter_scan sensitivity parameter",
    "optim": "dynamis_optimize minimize maximize objective",
    "minim": "dynamis_optimize minimize optimization",
    "maxim": "dynamis_optimize maximize optimization",
    "fit": "dynamis_fit_parameters curve fitting parameter estimation",
    "calibrat": "dynamis_fit_parameters parameter estimation fit",
    "regress": "dynamis_fit_parameters calcula_run_python regression",
    "constant": "physis_constants codata physical constant",
    "codata": "physis_constants physical constant",
    "planck": "physis_constants codata",
    "boltzmann": "physis_constants codata",
    "avogadro": "physis_constants codata",
    "unit": "physis_units unit conversion pint dimensional",
    "convert": "physis_units unit conversion",
    "dimension": "physis_units dimensional analysis units",
    "sequenc": "physis_oeis oeis integer sequence",
    "oeis": "physis_oeis integer sequence",
    "integer": "physis_oeis oeis sequence",
    "fibonacc": "physis_oeis oeis sequence",
    "material": "physis_materials crystal bandgap formation energy",
    "crystal": "physis_materials crystal structure lattice",
    "bandgap": "physis_materials band gap electronic",
    "lattic": "physis_materials crystal lattice",
    "wolfram": "physis_wolfram computational knowledge",
    "encyclop": "physis_encyclopedia definition theorem wikipedia",
    "wiki": "physis_encyclopedia encyclopedia definition",
    "definit": "physis_encyclopedia definition",
    "uncertaint": "physis_propagate_uncertainty error propagation",
    "uncertainty": "physis_propagate_uncertainty error propagation tolerance",
    "propagat": "physis_propagate_uncertainty error propagation uncertainty",
    "toleranc": "physis_propagate_uncertainty tolerance stack",
    "montecarlo": "physis_propagate_uncertainty monte carlo",
    "gum": "physis_propagate_uncertainty gum uncertainty",
    "errorbar": "physis_propagate_uncertainty uncertainty",
    "significan": "physis_propagate_uncertainty uncertainty",
    "pdf": "archivon_read_paper archivon_reproduce_paper uploaded paper",
    "reproduc": "archivon_reproduce_paper reproduce paper results",
    "beam": "physis_engineering_calc beam deflection bending",
    "cantilever": "physis_engineering_calc beam cantilever deflection",
    "deflect": "physis_engineering_calc beam deflection",
    "buckl": "physis_engineering_calc column buckling euler",
    "hoop": "physis_engineering_calc pressure vessel hoop stress",
    "vessel": "physis_engineering_calc pressure vessel",
    "shaft": "physis_engineering_calc shaft torsion",
    "torsion": "physis_engineering_calc shaft torsion",
    "bolt": "physis_engineering_calc bolt preload torque",
    "preload": "physis_engineering_calc bolt preload",
    "fatigue": "physis_engineering_calc fatigue goodman endurance",
    "goodman": "physis_engineering_calc fatigue goodman",
    "endurance": "physis_engineering_calc fatigue endurance",
    "colebrook": "physis_engineering_calc pipe pressure drop friction factor",
    "pipe": "physis_engineering_calc pipe pressure drop",
    "exchanger": "physis_engineering_calc heat exchanger lmtd ntu",
    "lmtd": "physis_engineering_calc heat exchanger lmtd",
    "insulat": "physis_engineering_calc layered wall conduction",
    "utilis": "physis_engineering_calc safety factor utilisation",
    "utiliz": "physis_engineering_calc safety factor utilisation",
    "pde": "dynamis_solve_pde partial differential equation",
    "heat": "dynamis_solve_pde heat equation diffusion",
    "diffus": "dynamis_solve_pde diffusion heat equation",
    "poisson": "dynamis_solve_pde poisson laplace equation",
    "laplace": "dynamis_solve_pde laplace poisson equation",
    "advect": "dynamis_solve_pde advection convection",
    "burgers": "dynamis_solve_pde burgers equation",
    "convect": "dynamis_solve_pde advection convection",
    "dataset": "calcula_describe_dataset calcula_run_python dataset",
    "csv": "calcula_describe_dataset calcula_run_python table",
    "hdf5": "calcula_describe_dataset calcula_run_python hdf5",
    "table": "calcula_describe_dataset calcula_run_python dataframe",
    "python": "calcula_run_python sandbox script",
    "statistic": "calcula_run_python statistics analysis",
    "web": "websurfer_search web search",
    "online": "websurfer_search web",
}

_EXPANSION_WEIGHT = 0.5


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


_STEM_LEN = 6


def _stem(token: str) -> str:
    """Plural stripping plus truncation stemming (first 6 characters), so 'papers'/'paper',
    'simulate'/'simulation' and 'associated'/'association' share a term."""
    if token.isdigit():
        return token
    if len(token) > 4 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "is", "us")):
        token = token[:-1]
    return token[:_STEM_LEN]


def _terms(text: str) -> list[str]:
    return [_stem(t) for t in tokenize((text or "").replace("_", " "))]


def _schema_fields(entry: Any) -> list[tuple[str, str, bool, Any, str]]:
    """(name, type, required, default, description) for the tool's input schema."""
    out: list[tuple[str, str, bool, Any, str]] = []
    schema = getattr(entry, "input_schema", None)
    fields = getattr(schema, "model_fields", {}) or {}
    for name, f in fields.items():
        ann = getattr(f, "annotation", None)
        tname = getattr(ann, "__name__", None) or str(ann).replace("typing.", "")
        required = bool(f.is_required()) if hasattr(f, "is_required") else False
        default = None if required else getattr(f, "default", None)
        try:
            json.dumps(default)
        except (TypeError, ValueError):
            default = str(default)
        out.append((name, tname, required, default, str(getattr(f, "description", "") or "")))
    return out


def _model_of(ann: Any) -> Any:
    """The pydantic model inside an annotation (Optional[X], List[X]) or None."""
    if hasattr(ann, "model_fields"):
        return ann
    for arg in getattr(ann, "__args__", ()) or ():
        m = _model_of(arg)
        if m is not None:
            return m
    return None


def output_fields(entry: Any, max_fields: int = 10, max_nested: int = 6) -> list[str]:
    """Reference paths a plan can use into this tool's result data: ["drugs[*].chembl_id", "drugs[*].pref_name", ...].

    Without them the planner guesses ("$n1.results") and the reference fails at run time.
    """
    schema = getattr(entry, "output_schema", None)
    fields = getattr(schema, "model_fields", {}) or {}
    out: list[str] = []
    for name, f in list(fields.items())[:max_fields]:
        ann = getattr(f, "annotation", None)
        is_list = "List" in str(ann) or "list[" in str(ann)
        nested = _model_of(ann)
        sub = list(getattr(nested, "model_fields", {}) or {})[:max_nested] if nested is not None else []
        if sub:
            out.extend(f"{name}{'[*]' if is_list else ''}.{s}" for s in sub)
        else:
            out.append(f"{name}{'[*]' if is_list else ''}")
    return out


def tool_card(entry: Any) -> dict[str, Any]:
    """Compact planner-facing description: name, purpose, domain, exact argument schema and output fields."""
    args = {
        name: {"type": t, "required": req, **({"default": d} if not req and d is not None else {}), **({"description": desc[:160]} if desc else {})}
        for name, t, req, d, desc in _schema_fields(entry)
    }
    return {
        "name": entry.name,
        "domain": entry.domain,
        "description": (entry.description or "")[:400],
        "args": args,
        **({"returns": returns} if (returns := output_fields(entry)) else {}),
        "timeout_seconds": entry.timeout_seconds,
    }


def tool_document(entry: Any) -> str:
    fields = " ".join(f"{n} {d}" for n, _t, _r, _dv, d in _schema_fields(entry))
    name_words = entry.name.replace("_", " ")
    return " ".join(
        [
            name_words,
            name_words,  # the name counts twice: it is the most specific signal
            entry.description or "",
            entry.domain or "",
            " ".join(entry.tags or []),
            fields,
            DOMAIN_INTENTS.get((entry.domain or "").lower(), ""),
            TOOL_INTENTS.get(entry.name, ""),
        ]
    )


def _intent_view(entry: Any) -> str:
    """Name, tags and synthetic queries only: the Re-Invoke 'intent' index, free of schema boilerplate."""
    return " ".join(
        [
            entry.name.replace("_", " "),
            " ".join(t.replace("_", " ") for t in (entry.tags or [])),
            TOOL_INTENTS.get(entry.name, ""),
            (entry.description or "")[:200],
        ]
    )


class _BM25:
    def __init__(self, docs: Sequence[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1, self.b = k1, b
        self.avgdl = sum(len(d) for d in docs) / max(1, len(docs))
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in docs]

    def score(self, query: list[str], i: int, weights: dict[str, float] | None = None) -> float:
        tf, dl = self.tf[i], len(self.docs[i])
        s = 0.0
        for t in query:
            if t not in tf:
                continue
            f = tf[t]
            w = (weights or {}).get(t, 1.0)
            s += w * self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / max(1e-9, self.avgdl)))
        return s


def expand_query(query: str) -> tuple[list[str], dict[str, float]]:
    """Stemmed query terms plus lexicon expansions, and the weight of each term (expansions weigh less)."""
    raw = tokenize((query or "").replace("_", " "))
    # Notation the tokenizer drops still names the task: "x^2 - 4 > 0" is an inequality, "7 mod 3" modular arithmetic.
    if re.search(r"[<>≤≥]", query or ""):
        raw += ["inequality", "intervals"]
    weights: dict[str, float] = {_stem(t): 1.0 for t in raw}
    for t in raw:
        for key, extra in QUERY_EXPANSIONS.items():
            if t.startswith(key):
                for e in _terms(extra):
                    weights.setdefault(e, _EXPANSION_WEIGHT)
    return list(weights), weights


_EMBEDDER: Any = None
_EMBEDDER_FAILED = False


def _embedder() -> Any:
    global _EMBEDDER, _EMBEDDER_FAILED
    model_id = os.getenv("TRIBOS_TOOL_EMBEDDINGS", "").strip()
    if not model_id or _EMBEDDER_FAILED:
        return None
    if _EMBEDDER is None:
        try:
            from sentence_transformers import SentenceTransformer

            _EMBEDDER = SentenceTransformer(model_id, local_files_only=True)  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001
            _EMBEDDER_FAILED = True
            logger.info("Tool embeddings unavailable (%s); using BM25 only", exc)
            return None
    return _EMBEDDER


def _dense_ranking(query: str, docs: list[str]) -> list[int] | None:
    model = _embedder()
    if model is None:
        return None
    try:
        import numpy as np

        vecs = model.encode([query, *docs], normalize_embeddings=True)
        sims = np.asarray(vecs[1:]) @ np.asarray(vecs[0])
        return [int(i) for i in np.argsort(-sims)]
    except Exception as exc:  # noqa: BLE001
        logger.info("Dense tool ranking failed: %s", exc)
        return None


def rank_tools(registry: Any, query: str, entries: list[Any] | None = None) -> list[tuple[Any, float]]:
    """Every candidate entry with its fused score, best first (used by retrieve_tools)."""
    entries = list(entries if entries is not None else registry.list_tools())
    if not entries:
        return []
    docs = [tool_document(e) for e in entries]
    q, weights = expand_query(query)
    full = _BM25([_terms(d) for d in docs])
    intent = _BM25([_terms(_intent_view(e)) for e in entries])
    full_scores = [full.score(q, i, weights) for i in range(len(entries))]
    intent_scores = [intent.score(q, i, weights) for i in range(len(entries))]
    rankings = [
        sorted(range(len(entries)), key=lambda i: (-full_scores[i], i)),
        sorted(range(len(entries)), key=lambda i: (-intent_scores[i], i)),
    ]
    dense = _dense_ranking(query, docs)
    if dense is not None:
        rankings.append(dense)
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking):
            fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank + 1)
    # Post-retrieval rerank (Toolshed): a tool whose name words all occur in the query is a direct mention.
    qset = set(q)
    for i, e in enumerate(entries):
        name_terms = set(_terms(e.name))
        if name_terms and name_terms <= qset:
            fused[i] += 0.01
        if full_scores[i] <= 0 and intent_scores[i] <= 0:
            fused[i] -= 0.005  # no lexical overlap at all: rank after every matching tool
    order = sorted(fused, key=lambda i: (-fused[i], i))
    return [(entries[i], fused[i]) for i in order]


def retrieve_tools(
    registry: Any,
    query: str,
    k: int = 8,
    domains: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    always: Iterable[str] | None = None,
) -> list[Any]:
    """Top-k registry entries for query (multi-view BM25 with query expansion, RRF-fused with a dense ranking
    when configured).

    `always` names are included first when registered (e.g. the literature tool for any research question).
    """
    excluded = set(exclude or [])
    wanted = {d.lower() for d in domains} if domains else None
    entries = [
        e for e in registry.list_tools()
        if e.name not in excluded and (wanted is None or (e.domain or "").lower() in wanted)
    ]
    if not entries:
        return []
    ranked = rank_tools(registry, query, entries)
    picked: list[Any] = []
    by_name = {e.name: e for e in entries}
    for name in always or []:
        if name in by_name and by_name[name] not in picked:
            picked.append(by_name[name])
    for entry, _score in ranked:
        if k > 0 and len(picked) >= k:
            break
        if entry not in picked:
            picked.append(entry)
    return picked[:k] if k > 0 else picked


def recall_at_k(registry: Any, cases: Sequence[tuple[str, str]], k: int = 5) -> float:
    """Fraction of (query, expected_tool) cases whose tool is in the top k (ToolRet's recall@k)."""
    if not cases:
        return 0.0
    hits = sum(1 for q, tool in cases if tool in {e.name for e in retrieve_tools(registry, q, k=k)})
    return hits / len(cases)
