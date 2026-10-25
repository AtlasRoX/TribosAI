"""
Declarative registry of every environment variable Tribos reads, with typed accessors and startup validation.

One `Setting` per variable: name, type, default, one-line description, group, secret flag and optional
choices/bounds. `scripts/gen_env_reference.py` renders docs/configuration.md and .env.example from it, and its
`--check` fails when a variable read in the code is missing here (or a registered one is no longer read).

The accessors read `os.environ` on every call (so `monkeypatch.setenv` and operators changing the environment of a
running process keep working), apply the registered default, clamp to the registered bounds and never raise on a
bad value: they log one warning per (name, value) and fall back to the default.

Values are never logged for secrets.
"""

from __future__ import annotations

import difflib
import logging
import math
import os
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TYPES = ("str", "int", "float", "bool", "path", "list")
TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")

# off | auto | on switches that also accept boolean words (`auto` = off under pytest, on otherwise).
SWITCH = ("off", "auto", "on")
SWITCH_ALIASES: Mapping[str, str] = {**dict.fromkeys(("1", "true", "yes"), "on"), **dict.fromkeys(("0", "false", "no"), "off")}
# Agentic capability flags (tribos.agentic.config.env_flag): exactly off | auto | on, anything else is the default.
FLAG = ("off", "auto", "on")
FRAMEWORKS = ("auto", "authoritative-react-compiler", "agentic-plan-execute", "multi-agent-supervisor", "multi-agent-swarm",
              "multi-agent-debate")

# TRIBOS_* names read outside tribos/ and app/ (tests, docker compose): not typos, not in the registry.
EXTERNAL_NAMES = frozenset({
    "TRIBOS_LIVE_TESTS",  # tests/conftest.py: run @pytest.mark.network cases
    "TRIBOS_API_PORT",  # docker/compose.yml: host port of the API container
    "TRIBOS_API_BIND",  # docker/compose.yml: host address the API port is published on (default 127.0.0.1)
    "TRIBOS_WEB_PORT",  # docker/compose.yml: host port of the web container
    "TRIBOS_WEB_BIND",  # docker/compose.yml: host address the web port is published on (default 127.0.0.1)
})

_UNSET: Any = object()


@dataclass(frozen=True)
class Setting:
    name: str
    type: str
    default: Any = None
    description: str = ""
    group: str = "Other"
    secret: bool = False
    choices: tuple[str, ...] | None = None
    min: float | None = None
    max: float | None = None
    aliases: Mapping[str, str] = field(default_factory=dict)  # accepted spellings -> choice
    sep: str = ","  # list separator

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise ValueError(f"{self.name}: unknown setting type {self.type!r}")


# Groups in documentation order: title -> variable prefix shown in the heading ("" = none).
GROUPS: dict[str, str] = {
    "State directories": "",
    "Retention and maintenance": "",
    "Authentication": "",
    "API server": "",
    "MCP and A2A endpoints": "TRIBOS_MCP",
    "Background jobs": "TRIBOS_JOB",
    "Models and LLM providers": "",
    "Agentic runtime": "TRIBOS_AGENT",
    "Claim verification (NLI)": "TRIBOS_NLI",
    "Confidence calibration": "TRIBOS_CONFIDENCE",
    "Query planning and synthesis": "",
    "Tool reliability and cache": "",
    "Web search": "",
    "Data sources": "",
    "Uploads and datasets": "TRIBOS_UPLOAD",
    "Simulation and single-cell analysis": "",
    "Code sandbox": "TRIBOS_SANDBOX",
    "Mathematics agent": "TRIBOS_MATH",
    "Image input (OCR and vision)": "TRIBOS_VISION",
    "Evaluations": "TRIBOS_EVAL",
    "Streamlit frontend": "",
    "Testing": "",
}

_DIRS = "State directories"
_RET = "Retention and maintenance"
_AUTH = "Authentication"
_API = "API server"
_MCP = "MCP and A2A endpoints"
_JOBS = "Background jobs"
_LLM = "Models and LLM providers"
_AGENT = "Agentic runtime"
_NLI = "Claim verification (NLI)"
_CONF = "Confidence calibration"
_PLAN = "Query planning and synthesis"
_REL = "Tool reliability and cache"
_WEB = "Web search"
_SRC = "Data sources"
_UP = "Uploads and datasets"
_SIM = "Simulation and single-cell analysis"
_SBX = "Code sandbox"
_MATH = "Mathematics agent"
_VIS = "Image input (OCR and vision)"
_EVAL = "Evaluations"
_ST = "Streamlit frontend"
_TEST = "Testing"

_SETTINGS: Sequence[Setting] = (
    # --- State directories ---------------------------------------------------------------------------------------
    Setting("TRIBOS_DATA_DIR", "path", None, "One data root (`~` expanded): memory/, runs/, uploads/, jobs/, tool_cache/ default under it.", _DIRS),
    Setting("TRIBOS_MEMORY_DIR", "path", None, "Research memory vault directory (wins over TRIBOS_DATA_DIR); also the projects store fallback.", _DIRS),
    Setting("TRIBOS_PROJECTS_DIR", "path", None, "Projects store directory (wins over TRIBOS_MEMORY_DIR and TRIBOS_DATA_DIR).", _DIRS),
    Setting("TRIBOS_RUNS_DIR", "path", None, "Run-manifest store (wins over TRIBOS_DATA_DIR; also hosts jobs/ and tool_cache/).", _DIRS),
    Setting("TRIBOS_UPLOAD_ROOT", "path", None, "Uploaded datasets directory (wins over TRIBOS_DATA_DIR).", _DIRS),
    Setting("TRIBOS_JOBS_DIR", "path", None, "Background-job SQLite store directory (wins over TRIBOS_RUNS_DIR/jobs).", _DIRS),
    Setting("TRIBOS_TOOL_CACHE_DIR", "path", None, "Tool-result SQLite cache directory (wins over TRIBOS_RUNS_DIR/tool_cache).", _DIRS),
    Setting("TRIBOS_DATASET_ROOTS", "list", None, "Directories (os.pathsep-separated) that typed dataset paths may point into; <cwd>/data when unset.", _DIRS, sep=os.pathsep),
    # --- Retention and maintenance -------------------------------------------------------------------------------
    Setting("TRIBOS_JOB_TTL_DAYS", "float", 30.0, "Finished jobs older than this many days are purged (0 keeps them).", _RET, min=0.0, max=36500.0),
    Setting("TRIBOS_MAX_RUNS", "int", 500, "Newest run manifests kept across users (0 = unlimited).", _RET, min=0),
    Setting("TRIBOS_MAX_RUNS_PER_USER", "int", 500, "Maximum stored run manifests kept per user (0 = unlimited).", _RET, min=0),
    Setting("TRIBOS_USER_HASH_SALT", "str", None, "Deployment salt for hashing user identifiers in exported run manifests.", _RET, secret=True),
    Setting("TRIBOS_MAINTENANCE", "str", "auto", "Retention sweep switch: off, auto (off under pytest) or on.", _RET, choices=SWITCH, aliases=SWITCH_ALIASES),
    Setting("TRIBOS_MAINTENANCE_INTERVAL_H", "float", 6.0, "Hours between retention sweeps.", _RET, min=0.0),
    # --- Authentication ------------------------------------------------------------------------------------------
    Setting("TRIBOS_AUTH_MODE", "str", None, "`disabled` runs every request as one local user (development only); otherwise bearer auth is required.", _AUTH, choices=("disabled", "bearer")),
    Setting("TRIBOS_API_TOKENS", "list", None, "Static bearer tokens as comma-separated `token:user_id` pairs.", _AUTH, secret=True),
    Setting("TRIBOS_JWT_SECRET", "str", None, "HS256 secret for bearer JWTs (`sub` = user id, `exp` required).", _AUTH, secret=True),
    Setting("TRIBOS_JWT_AUDIENCE", "str", None, "Required JWT `aud` claim when set.", _AUTH),
    Setting("TRIBOS_JWT_ISSUER", "str", None, "Required JWT `iss` claim when set.", _AUTH),
    Setting("TRIBOS_ALLOW_INSECURE", "bool", False, "Allow non-loopback connections when authentication is disabled (unsafe).", _AUTH),
    # --- API server ----------------------------------------------------------------------------------------------
    Setting("TRIBOS_ALLOWED_HOSTS", "list", None, "Allowed HTTP Host header values (comma-separated; defaults to loopback when auth is disabled).", _API),
    Setting("TRIBOS_CORS_ORIGINS", "list", "http://localhost:3000,http://127.0.0.1:3000", "Comma-separated browser origins allowed by CORS (also allowed by the MCP endpoint).", _API),
    Setting("TRIBOS_SSE_HEARTBEAT_S", "float", 15.0, "Seconds between keep-alive comments on chat and job event streams.", _API, min=0.05),
    Setting("TRIBOS_HEALTH_CACHE_S", "float", 60.0, "Seconds the upstream readiness probes of /api/health are cached.", _API, min=0.0),
    Setting("TRIBOS_MAX_CONCURRENT_CHATS_PER_USER", "int", 2, "Questions one user may have running at once (over it the request is refused).", _API, min=1),
    Setting("TRIBOS_MAX_CONCURRENT_TITLES_PER_USER", "int", 2, "Model-generated thread titles per user at once (over it a heuristic title is used).", _API, min=1),
    Setting("TRIBOS_STRICT_ROUTERS", "bool", False, "Fail startup when an optional API router cannot be imported instead of disabling it.", _API),
    Setting("TRIBOS_STRICT_CONFIG", "bool", False, "Fail startup when configuration validation reports a problem instead of only logging it.", _API),
    Setting("TRIBOS_MAX_BODY_MB", "float", 2.0, "Largest request body in MB (larger requests get 413).", _API, min=0.01),
    Setting("TRIBOS_MAX_EXPORT_BODY_MB", "float", 16.0, "Largest request body in MB for the export and report endpoints.", _API, min=0.01),
    Setting("TRIBOS_PUBLIC_URL", "str", None, "Public base URL of the API (e.g. https://tribos.example.org) used in the A2A Agent Card; default: the request's own base URL.", _API),
    # --- MCP and A2A -----------------------------------------------------------------------------------------------
    Setting("TRIBOS_MCP_ALLOWED_ORIGINS", "list", None, "Extra comma-separated origins the MCP endpoint accepts besides TRIBOS_CORS_ORIGINS.", _MCP),
    Setting("TRIBOS_MCP_MAX_CONCURRENT", "int", 2, "Concurrent MCP research calls per user.", _MCP, min=1),
    Setting("TRIBOS_MCP_RESEARCH_TIMEOUT_S", "float", 900.0, "Seconds an MCP research call may run before it is cancelled.", _MCP, min=0.0),
    Setting("TRIBOS_MCP_TOOLS", "list", None, "Comma-separated registry tools exposed over MCP (default: the built-in allowlist).", _MCP),
    Setting("TRIBOS_A2A_BLOCKING_TIMEOUT_S", "float", 300.0, "Seconds a blocking A2A message/send waits for its job before returning the task.", _MCP, min=0.0),
    # --- Background jobs -------------------------------------------------------------------------------------------
    Setting("TRIBOS_JOB_WORKERS", "int", 2, "Background-job worker tasks.", _JOBS, min=1, max=16),
    Setting("TRIBOS_MAX_JOBS_PER_USER", "int", 3, "Queued + running background jobs per user.", _JOBS, min=1, max=100),
    Setting("TRIBOS_JOB_MAX_EVENTS", "int", 20_000, "Progress events kept per job; older ones are dropped.", _JOBS, min=100, max=1_000_000),
    Setting("TRIBOS_JOB_CANCEL_GRACE_S", "float", 20.0, "Seconds a cancelled job may take to stop before it is marked cancelled anyway.", _JOBS, min=0.0, max=600.0),
    # --- Models and LLM providers ----------------------------------------------------------------------------------
    Setting("NVIDIA_API_KEY", "str", None, "NVIDIA NIM models (default LLM provider) and the NIM structure tools.", _LLM, secret=True),
    Setting("NVIDIA_NIM_API_KEY", "str", None, "Alternative name for NVIDIA_API_KEY (used when that one is unset).", _LLM, secret=True),
    Setting("OPENAI_API_KEY", "str", None, "OpenAI models; also the fallback when no NVIDIA key is set.", _LLM, secret=True),
    Setting("TRIBOS_LLM_MODEL", "str", None, "Default model id when a request names none (the orchestrator default when unset; gpt-4o-mini for the Lumicell SCP agent).", _LLM),
    Setting("TRIBOS_ALLOWED_MODELS", "list", None, "Extra comma-separated model ids callers may select besides the built-in catalog.", _LLM),
    Setting("TRIBOS_SYNTHESIS_MODEL", "str", None, "Model that writes the final answer (default: the turn's model).", _LLM),
    Setting("LLM_TIMEOUT", "float", 60.0, "Per-request LLM client timeout in seconds.", _LLM),
    Setting("LLM_STREAM_TIMEOUT", "float", 120.0, "Read timeout in seconds between streamed completion chunks.", _LLM),
    Setting("LLM_STREAM_TOTAL_TIMEOUT", "float", 1800.0, "Wall-clock cap in seconds on one streamed completion.", _LLM),
    Setting("TRIBOS_LLM_FALLBACK", "bool", True, "Allow fallback to an available provider when the requested model key is unset.", _LLM),
    # --- Agentic runtime -------------------------------------------------------------------------------------------
    Setting("TRIBOS_DEFAULT_FRAMEWORK", "str", None, "Orchestration framework used when a request names none or an unknown one (default: auto routing for API requests; the classic pipeline for direct orchestrator calls).", _AGENT, choices=FRAMEWORKS),
    Setting("TRIBOS_ROUTER_LLM", "str", "auto", "Auto routing: off scores the deterministic signals only; auto/on add the model's semantic features.", _AGENT, choices=FLAG),
    Setting("TRIBOS_ROUTER_SAMPLES", "int", 1, "Auto routing: semantic feature samples averaged per question (self-consistency).", _AGENT, min=1, max=5),
    Setting("TRIBOS_ROUTER_LEARNING", "str", "auto", "Auto routing outcome learning: off, auto (off under pytest) or on.", _AGENT, choices=SWITCH, aliases=SWITCH_ALIASES),
    Setting("TRIBOS_ROUTER_DIR", "path", None, "Auto routing outcome store (default <TRIBOS_RUNS_DIR>/router, else <TRIBOS_DATA_DIR>/router, else data/router).", _AGENT),
    Setting("TRIBOS_AGENT_MODEL", "str", None, "Model for agentic planning/critique calls (default: the turn's model).", _AGENT),
    Setting("TRIBOS_AGENT_THINKING", "bool", False, "Keep model reasoning on for short agent calls (plans, critiques, JSON verdicts).", _AGENT),
    Setting("TRIBOS_AGENT_CALL_TIMEOUT", "float", 180.0, "Seconds one agent model call (plan, critique, verdict) may take.", _AGENT),
    Setting("TRIBOS_AGENT_PLAN", "str", "auto", "Plan-and-execute phase: off disables it.", _AGENT, choices=FLAG),
    Setting("TRIBOS_AGENT_PLAN_MODE", "str", "dag", "Plan execution: dag (one plan, parallel nodes) or react (step-by-step tool rounds).", _AGENT, choices=("dag", "react")),
    Setting("TRIBOS_AGENT_PLAN_CONCURRENCY", "int", 4, "Plan nodes executed in parallel.", _AGENT, min=1, max=16),
    Setting("TRIBOS_AGENT_REACT_STEPS", "int", 4, "Maximum tool rounds in react plan mode.", _AGENT, min=1, max=12),
    Setting("TRIBOS_AGENT_DECOMPOSE", "str", "auto", "Sub-question decomposition: off, auto (complex questions only) or on (always).", _AGENT, choices=FLAG),
    Setting("TRIBOS_AGENT_APPROVAL_TIMEOUT", "float", 300.0, "Seconds a plan waits for the user's approval before running as proposed.", _AGENT, min=5.0, max=3600.0),
    Setting("TRIBOS_APPROVAL_TIMEOUT_S", "float", 300.0, "Seconds a tool-approval request waits for the user before it is denied.", _AGENT, min=5.0, max=3600.0),
    Setting("TRIBOS_APPROVAL_ON_TIMEOUT", "str", "withhold_expensive", "Action on approval timeout: withhold_expensive (default) or reject.", _AGENT, choices=("withhold_expensive", "reject")),
    Setting("TRIBOS_COUNTER_EVIDENCE", "str", "auto", "Counter-evidence search for research answers: off disables it.", _AGENT, choices=FLAG),
    Setting("TRIBOS_AGENT_MAX_TOOL_CALLS", "int", 40, "Run budget: tool calls.", _AGENT, min=1, max=200),
    Setting("TRIBOS_AGENT_MAX_LLM_CALLS", "int", 40, "Run budget: agent model calls.", _AGENT, min=1, max=120),
    Setting("TRIBOS_AGENT_MAX_TOKENS", "int", 250_000, "Run budget: model tokens.", _AGENT, min=1_000, max=2_000_000),
    Setting("TRIBOS_AGENT_MAX_OUTPUT_TOKENS", "int", 0, "Explicit per-reply output token cap for agent calls (0/unset = budget-derived only).", _AGENT, min=0),
    Setting("TRIBOS_AGENT_MAX_SECONDS", "float", 0.0, "Run budget: wall-clock seconds (0 = no limit).", _AGENT, min=0.0, max=7_200.0),
    Setting("TRIBOS_AGENT_MAX_DRAFT_ROUNDS", "int", 2, "Run budget: draft/critique/revise rounds.", _AGENT, min=0, max=5),
    Setting("TRIBOS_AGENT_MAX_PLAN_NODES", "int", 12, "Run budget: nodes in one plan.", _AGENT, min=1, max=40),
    Setting("TRIBOS_AGENT_MAX_REPLANS", "int", 1, "Run budget: replans after failed or missing evidence.", _AGENT, min=0, max=3),
    Setting("TRIBOS_AGENT_FINAL_RESERVE_TOKENS", "int", None, "Run budget tokens kept for the final rewrite and verifier revision; optional agent work stops before them (unset = 12% of the token budget, at least 20k, at most 30%).", _AGENT, min=0),
    Setting("TRIBOS_AGENT_FINAL_RESERVE_CALLS", "int", 2, "Agent model calls kept for the final rewrite and verifier revision (0 when the call budget is below 6).", _AGENT, min=0),
    Setting("TRIBOS_AGENT_OUTPUT_RESERVE_TOKENS", "int", 4096, "Output tokens admitted per agent model call; also its max_tokens, so concurrent calls cannot overshoot the budget together.", _AGENT, min=1),
    Setting("TRIBOS_REWRITE_MAX_OUTPUT_TOKENS", "int", 8192, "Most output tokens one answer rewrite or verifier revision may produce (never more than the run budget has left; a rewrite that would be cut off is skipped).", _AGENT, min=1),
    Setting("TRIBOS_FIRST_DRAFT_MAX_OUTPUT_TOKENS", "int", 16000, "Output tokens (reasoning included) admitted for the first draft of an agentic run and sent as its max_tokens.", _AGENT, min=256),
    Setting("TRIBOS_CANCEL_GRACE_S", "float", 2.0, "Seconds a cancelled or deadline-expired model call is waited for before it is abandoned.", _AGENT, min=0.0),
    Setting("TRIBOS_PROGRESS_HEARTBEAT_S", "float", 5.0, "Seconds between liveness re-emits of a step waiting on a long model call (0 disables).", _AGENT, min=0.0),
    Setting("TRIBOS_TOOL_EMBEDDINGS", "str", None, "Local sentence-transformers model id for embedding-based tool retrieval (unset = lexical only).", _AGENT),
    # --- Claim verification (NLI) ----------------------------------------------------------------------------------
    Setting("TRIBOS_NLI", "str", "auto", "Claim-vs-evidence NLI: off, auto (cross-encoder, else LLM), model (cross-encoder only) or llm.", _NLI, choices=("off", "auto", "model", "llm"), aliases={"on": "auto"}),
    Setting("TRIBOS_NLI_MODEL", "str", "cross-encoder/nli-deberta-v3-base", "Hugging Face cross-encoder used for NLI.", _NLI),
    Setting("TRIBOS_NLI_ENTAIL", "float", 0.5, "Entailment probability at or above which a claim is supported.", _NLI, min=0.05, max=0.99),
    Setting("TRIBOS_NLI_CONTRADICT", "float", 0.8, "Contradiction probability at or above which a claim is contradicted.", _NLI, min=0.3, max=0.999),
    Setting("TRIBOS_NLI_UNSUPPORTED", "float", 0.15, "Entailment probability below which a claim is unsupported.", _NLI, min=0.0, max=0.9),
    Setting("TRIBOS_NLI_BATCH", "int", 16, "Cross-encoder batch size.", _NLI, min=1, max=128),
    Setting("TRIBOS_NLI_CHUNK_WORDS", "int", 120, "Words per evidence window scored against a claim.", _NLI, min=20, max=400),
    Setting("TRIBOS_NLI_LLM_BATCH", "int", 4, "Claims per LLM NLI call.", _NLI, min=1, max=8),
    Setting("TRIBOS_NLI_MAX_LLM_CALLS", "int", 12, "LLM NLI calls per run (hard ceiling 12).", _NLI, min=0, max=12),
    # --- Confidence calibration ------------------------------------------------------------------------------------
    Setting("TRIBOS_CONFIDENCE_CALIBRATION", "path", None, "JSON file with a fitted temperature, conformal threshold and feature weights.", _CONF),
    Setting("TRIBOS_CONFIDENCE_T", "float", None, "Confidence temperature override (positive; clamped to 0.05-20).", _CONF, min=0.05, max=20.0),
    Setting("TRIBOS_CONFIDENCE_ELICIT", "str", "auto", "Model-elicited confidence for claims: off disables it.", _CONF, choices=FLAG),
    # --- Query planning and synthesis ------------------------------------------------------------------------------
    Setting("TRIBOS_PLANNER", "str", "auto", "LLM query planner: off, auto (when heuristics are unsure) or always.", _PLAN, choices=("off", "auto", "always")),
    Setting("TRIBOS_RESOLVER_DISABLED", "bool", False, "Skip the entity resolver in query normalization (1/true/yes).", _PLAN),
    Setting("TRIBOS_NORMALIZER_BUDGET_S", "float", None, "Seconds for query normalization when the caller keeps the 3.5 s default.", _PLAN, min=0.1),
    Setting("TRIBOS_SEARCH_PLAN_WAIT_S", "float", 6.0, "Seconds the pipeline waits for the LLM search plan before using the heuristic one.", _PLAN, min=0.0),
    Setting("TRIBOS_SHOW_REASONING", "bool", False, "Stream raw model reasoning to the client (it is not checked by the verifier).", _PLAN),
    # --- Tool reliability and cache --------------------------------------------------------------------------------
    Setting("TRIBOS_RELIABILITY", "str", "auto", "Tool retry/breaker/cache policies: off, auto (off under pytest) or on.", _REL, choices=SWITCH, aliases=SWITCH_ALIASES),
    Setting("TRIBOS_TOOL_CACHE", "str", "auto", "Tool-result cache (needs TRIBOS_RELIABILITY): off, auto (off under pytest) or on.", _REL, choices=SWITCH, aliases=SWITCH_ALIASES),
    Setting("TRIBOS_TOOL_CACHE_TTL_S", "float", None, "Overrides the per-adapter tool-cache TTL (seconds).", _REL, min=0.0),
    Setting("TRIBOS_TOOL_RETRIES", "int", 2, "Retries of a networked tool after a transient failure.", _REL, min=0, max=5),
    Setting("TRIBOS_BREAKER_THRESHOLD", "int", 5, "Consecutive failures that open an adapter's circuit breaker.", _REL, min=1, max=100),
    Setting("TRIBOS_BREAKER_COOLDOWN_S", "float", 60.0, "Seconds an open circuit breaker waits before a trial call.", _REL, min=0.0, max=3600.0),
    Setting("TRIBOS_NATIVE_WORKERS", "int", 4, "Thread pool size for CPU-bound native tools.", _REL, min=1),
    Setting("TRIBOS_NETWORK_WORKERS", "int", 16, "Thread pool size for synchronous networked tools.", _REL, min=1),
    # --- Web search ------------------------------------------------------------------------------------------------
    Setting("TAVILY_API_KEY", "str", None, "Tavily web search (first provider when set).", _WEB, secret=True),
    Setting("TRIBOS_SEARXNG_URL", "str", None, "Base URL of a SearXNG instance with the JSON format enabled (used after Tavily).", _WEB),
    # --- Data sources ----------------------------------------------------------------------------------------------
    Setting("TRIBOS_S2_API_KEY", "str", None, "Optional Semantic Scholar API key for higher rate limits in Archivon.", _SRC, secret=True),
    Setting("TRIBOS_OPENALEX_API_KEY", "str", None, "Optional OpenAlex API key for polite/premium pool requests in Archivon.", _SRC, secret=True),
    Setting("TRIBOS_ADS_API_TOKEN", "str", None, "Optional NASA ADS Bearer API token for astrophysics literature search in Archivon.", _SRC, secret=True),
    Setting("TRIBOS_WOLFRAM_APPID", "str", None, "Optional Wolfram|Alpha LLM API AppID for Physis external reference queries.", _SRC, secret=True),
    Setting("TRIBOS_MP_API_KEY", "str", None, "Optional Materials Project API v2 key for live crystalline/electronic material queries in Physis.", _SRC, secret=True),
    Setting("TRIBOS_CONTACT_EMAIL", "str", "contact@tribos.science", "Polite-pool contact e-mail sent in User-Agent headers for arXiv, Crossref, OpenAlex, and Wikipedia.", _SRC),
    Setting("NCBI_API_KEY", "str", None, "NCBI E-utilities key (raises the rate limit from 3 to 10 requests/s).", _SRC, secret=True),
    Setting("TRIBOS_CROSSREF_MAILTO", "str", None, "Contact e-mail for the Crossref polite pool (citation integrity checks).", _SRC),
    Setting("TRIBOS_PROVENANCE_PROBES", "str", "auto", "Live source-version probes for run manifests: off, auto (off under pytest) or on.", _SRC, choices=SWITCH, aliases=SWITCH_ALIASES),
    # --- Uploads and datasets --------------------------------------------------------------------------------------
    Setting("TRIBOS_UPLOAD_MAX_MB_H5AD", "float", 500.0, "Deprecated: fallback for TRIBOS_UPLOAD_MAX_MB_HDF5.", _UP),
    Setting("TRIBOS_UPLOAD_MAX_MB_CSV", "float", 100.0, "Largest table (CSV/TSV) upload in MB.", _UP),
    Setting("TRIBOS_UPLOAD_MAX_MB_HDF5", "float", 500.0, "Largest HDF5 (.h5/.hdf5) upload in MB.", _UP),
    Setting("TRIBOS_UPLOAD_MAX_MB_MAT", "float", 100.0, "Largest MATLAB (.mat) upload in MB.", _UP),
    Setting("TRIBOS_UPLOAD_MAX_TOTAL_MB", "float", 2048.0, "Total upload storage per user in MB.", _UP),
    Setting("TRIBOS_UPLOAD_MAX_DATASETS", "int", 50, "Uploaded datasets kept per user.", _UP),
    # --- Partial differential equations (tribos/dynamis/pde) -----------------------------------------------------
    Setting("TRIBOS_PDE_MAX_GRID_1D", "int", 20000, "Largest number of grid points in a 1D PDE solve.", _SIM,
            min=100, max=1000000),
    Setting("TRIBOS_PDE_MAX_GRID_2D", "int", 6400, "Largest number of grid points in a 2D PDE solve (80 x 80).", _SIM,
            min=100, max=1000000),
    Setting("TRIBOS_PDE_MAX_SECONDS", "float", 20.0, "Wall-clock limit of one PDE solve, convergence study included.",
            _SIM, min=1.0, max=600.0),
    Setting("TRIBOS_PDE_MAX_SNAPSHOTS", "int", 25, "Snapshots one PDE solve returns.", _SIM, min=2, max=200),
    Setting("TRIBOS_PDE_MAX_CONVERGENCE_LEVELS", "int", 3, "Nested grids of the PDE mesh-convergence study.", _SIM,
            min=2, max=4),
    # --- Interactive simulation API (app/backend/routers/simulate.py) ---------------------------------------------
    Setting("TRIBOS_SIMULATE_TIMEOUT_S", "float", 10.0, "Seconds one interactive simulate, bifurcation or vector-field "
            "call may run.", _SIM, min=1.0, max=60.0),
    Setting("TRIBOS_SIMULATE_RATE_PER_MIN", "int", 60, "Interactive simulation calls one user may make per minute.",
            _SIM, min=1, max=10000),
    Setting("TRIBOS_SIMULATE_MAX_CONCURRENT", "int", 2, "Interactive simulation calls one user may have running at "
            "once.", _SIM, min=1, max=32),
    # --- Code sandbox ----------------------------------------------------------------------------------------------
    Setting("TRIBOS_SANDBOX", "bool", True, "Code-execution sandbox tool; on by default, off/0/false/no disables it.", _SBX),
    Setting("TRIBOS_SANDBOX_TIMEOUT_S", "int", 60, "Seconds one sandboxed execution may run.", _SBX, min=5, max=110),
    Setting("TRIBOS_SANDBOX_MEMORY_MB", "int", 2048, "Memory limit of one sandboxed execution in MB.", _SBX, min=256, max=16384),
    # --- Mathematics agent -----------------------------------------------------------------------------------------
    Setting("TRIBOS_MATH_AGENT", "bool", True, "Run the verified mathematics agent (bounded ReAct loop over the Axiom tools with an independent verifier) on mathematical questions.", _MATH),
    Setting("TRIBOS_MATH_AGENT_MAX_STEPS", "int", 12, "Tool calls one mathematics-agent run may make.", _MATH, min=2, max=40),
    Setting("TRIBOS_MATH_AGENT_MAX_REPAIRS", "int", 4, "Local repairs of one failed step before the agent switches strategy.", _MATH, min=0, max=10),
    Setting("TRIBOS_MATH_TRAJECTORY_DIR", "path", None, "Append every mathematics-agent trajectory here as JSONL (tool calls, observations, verification labels) for evaluation and fine-tuning data.", _MATH),
    Setting("TRIBOS_SAGEMATH_PATH", "str", None, "SageMath executable, or `wsl:<wsl.exe arguments>` to run it inside WSL; discovered on PATH and in WSL when unset.", _MATH),
    # --- Image input (OCR and vision) --------------------------------------------------------------------------------
    Setting("TRIBOS_VISION", "bool", True, "Accept images attached to questions (POST /api/vision/read); they are read into text before the question is solved.", _VIS),
    Setting("TRIBOS_VISION_OCR_MATH", "bool", True, "Load Indra OCR's math models so formulas are read as LaTeX (about 60% slower OCR on math lines).", _VIS),
    Setting("TRIBOS_VISION_PROVIDER", "str", "nim", "Vision model that corrects the OCR draft: `nim` (NVIDIA NIM, TRIBOS_VISION_MODEL), `ollama` (a local model through Ollama), or `ocr` (Indra OCR only; the image never leaves this machine).", _VIS, choices=("nim", "ollama", "ocr")),
    Setting("TRIBOS_VISION_MODEL", "str", "nvidia/nemotron-3.5-super-vl-120b-a12b", "NVIDIA NIM vision model for `nim` (must be in the allowed model list).", _VIS),
    Setting("TRIBOS_VISION_OLLAMA_MODEL", "str", None, "Ollama vision model for `ollama` (e.g. qwen2.5vl:7b); the first installed vision-family model when unset.", _VIS),
    Setting("TRIBOS_VISION_OLLAMA_URL", "str", "http://127.0.0.1:11434", "Base URL of the local Ollama server.", _VIS),
    Setting("TRIBOS_VISION_TIMEOUT_S", "int", 300, "Seconds one vision-model transcription may take (CPU inference of a 7B model can need minutes).", _VIS, min=10, max=1800),
    Setting("TRIBOS_VISION_MAX_MB", "int", 10, "Largest image upload in MB.", _VIS, min=1, max=50),
    Setting("TRIBOS_VISION_MAX_IMAGES", "int", 4, "Images one question may carry.", _VIS, min=1, max=10),
    Setting("TRIBOS_VISION_MAX_PAGES", "int", 4, "Pages of an attached PDF that are read (each like one image).", _VIS, min=1, max=20),
    # --- Evaluations -----------------------------------------------------------------------------------------------
    Setting("TRIBOS_EVAL_CACHE", "path", None, "Downloaded benchmark datasets cache (default ~/.cache/tribos/evals).", _EVAL),
    Setting("TRIBOS_EVAL_JUDGE_MODEL", "str", None, "Model id of the evaluation judge; also added to the models callers may select.", _EVAL),
    Setting("TRIBOS_EVAL_TOKEN", "str", None, "Bearer token the eval runner sends to a remote Tribos API.", _EVAL, secret=True),
    Setting("TRIBOS_CASSETTE_PROMPTS", "bool", False, "Store full normalised prompts in recorded eval cassettes (easier miss diagnosis, larger files).", _EVAL),
    Setting("HF_TOKEN", "str", None, "Hugging Face user access token for gated benchmark downloads (GPQA Diamond).", _EVAL, secret=True),
    # --- Milvus and the PrimeKG vector dump ------------------------------------------------------------------------
    # --- Streamlit frontend ----------------------------------------------------------------------------------------
    # --- Testing ---------------------------------------------------------------------------------------------------
    Setting("PYTEST_CURRENT_TEST", "str", None, "Set by pytest; `auto` switches and default stores treat its presence as a test run. Never set it yourself.", _TEST),
    Setting("TRIBOS_LOAD_DOTENV", "bool", True, "Load the workspace `.env` when the API module is imported; tests/conftest.py sets 0 so a developer `.env` never reaches pytest.", _TEST),
)

REGISTRY: dict[str, Setting] = {s.name: s for s in _SETTINGS}
if len(REGISTRY) != len(_SETTINGS):  # pragma: no cover - guards copy/paste mistakes at import
    raise RuntimeError("duplicate names in the settings registry")
for _s in _SETTINGS:
    if _s.group not in GROUPS:  # pragma: no cover
        raise RuntimeError(f"{_s.name}: unknown settings group {_s.group!r}")


# -----------------------------------------------------------------------------
# Accessors
# -----------------------------------------------------------------------------

_warned: set[tuple[str, str]] = set()
_warn_lock = threading.Lock()


def _reset_warnings() -> None:
    """Forget which bad values were already reported (tests)."""
    with _warn_lock:
        _warned.clear()


def _shown(setting: Setting | None, raw: str) -> str:
    return "<redacted>" if setting is not None and setting.secret else repr(raw)


def _warn_once(name: str, raw: str, message: str) -> None:
    with _warn_lock:
        key = (name, raw)
        if key in _warned:
            return
        _warned.add(key)
    logger.warning("%s", message)


def _raw(name: str) -> str | None:
    """The stripped value, or None when the variable is unset or blank."""
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _lookup(name: str, default: Any) -> tuple[Setting | None, Any]:
    setting = REGISTRY.get(name)
    if default is _UNSET:
        if setting is None:
            raise KeyError(f"{name} is not a registered setting; register it in tribos/config/settings.py")
        default = setting.default
    return setting, default


def _bounds(setting: Setting | None, lo: Any, hi: Any) -> tuple[float | None, float | None]:
    if lo is _UNSET:
        lo = setting.min if setting is not None else None
    if hi is _UNSET:
        hi = setting.max if setting is not None else None
    return lo, hi


def _clamp(value: Any, lo: float | None, hi: float | None) -> Any:
    # max(lo, min(hi, value)), the order of the historical env helpers.
    if hi is not None:
        value = min(hi, value)
    if lo is not None:
        value = max(lo, value)
    return value


def _number(name: str, kind: type, default: Any, lo: Any, hi: Any) -> Any:
    setting, default = _lookup(name, default)
    lo, hi = _bounds(setting, lo, hi)
    raw = _raw(name)
    label = "an integer" if kind is int else "a number"
    parsed = False
    if raw is None:
        value = default
    else:
        try:
            value = kind(raw)
            if kind is float and math.isnan(value):
                raise ValueError("nan")
            parsed = True
        except ValueError:
            _warn_once(name, raw, f"{name}={_shown(setting, raw)} is not {label}; using the default {default!r}")
            value = default
    if value is None:
        return None
    clamped = _clamp(value, lo, hi)
    if parsed and raw is not None and clamped != value:
        _warn_once(name, raw, f"{name}={_shown(setting, raw)} is outside [{lo}, {hi}]; using {clamped!r}")
    return clamped


def get_int(name: str, default: Any = _UNSET, *, min: Any = _UNSET, max: Any = _UNSET) -> Any:  # noqa: A002
    """The variable as an int: registered default when unset/blank/invalid, clamped to the bounds.

    `default`, `min` and `max` override the registered values (None = no bound)."""
    return _number(name, int, default, min, max)


def get_float(name: str, default: Any = _UNSET, *, min: Any = _UNSET, max: Any = _UNSET) -> Any:  # noqa: A002
    """The variable as a float: registered default when unset/blank/invalid/NaN, clamped to the bounds."""
    value = _number(name, float, default, min, max)
    return float(value) if isinstance(value, int) and not isinstance(value, bool) else value


def get_bool(name: str, default: Any = _UNSET) -> Any:
    """1/true/yes/on -> True, 0/false/no/off -> False (any case); unset/blank/other -> the default."""
    setting, default = _lookup(name, default)
    raw = _raw(name)
    if raw is None:
        return default
    word = raw.lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    _warn_once(name, raw, f"{name}={_shown(setting, raw)} is not a boolean (1/0, true/false, yes/no, on/off); using {default!r}")
    return default


def get_str(name: str, default: Any = _UNSET, *, choices: Any = _UNSET) -> Any:
    """The stripped value, or the default when unset/blank.

    With choices (registered or passed), the value is matched case-insensitively (after the registered aliases)
    and returned lowercased; an unknown value logs a warning and returns the default."""
    setting, default = _lookup(name, default)
    if choices is _UNSET:
        choices = setting.choices if setting is not None else None
    raw = _raw(name)
    if raw is None:
        return default
    if not choices:
        return raw
    word = raw.lower()
    if setting is not None:
        word = setting.aliases.get(word, word)
    if word in choices:
        return word
    _warn_once(name, raw, f"{name}={_shown(setting, raw)} is not one of {', '.join(choices)}; using {default!r}")
    return default


def get_path(name: str, default: Any = _UNSET) -> Path | None:
    """The variable as a Path (`~` expanded), or the default (None unless registered/passed) when unset/blank."""
    _, default = _lookup(name, default)
    raw = _raw(name)
    if raw is None:
        return Path(default).expanduser() if default not in (None, "") else None
    return Path(os.path.expanduser(raw))


def get_list(name: str, default: Any = _UNSET) -> list[str]:
    """The variable split on its separator (`,` unless registered otherwise), items stripped, blanks dropped."""
    setting, default = _lookup(name, default)
    sep = setting.sep if setting is not None else ","
    raw = _raw(name)
    if raw is None:
        if default in (None, ""):
            return []
        if isinstance(default, str):
            raw = default
        else:
            return [str(v) for v in default]
    return [item.strip() for item in raw.split(sep) if item.strip()]


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

def _problem(setting: Setting, raw: str) -> str | None:
    shown = _shown(setting, raw)
    if setting.type in ("int", "float"):
        kind = int if setting.type == "int" else float
        try:
            value = kind(raw)
        except ValueError:
            return f"{setting.name}={shown} is not {'an integer' if kind is int else 'a number'}; the default {setting.default!r} is used"
        if kind is float and math.isnan(value):
            return f"{setting.name}={shown} is not a number; the default {setting.default!r} is used"
        if setting.min is not None and value < setting.min:
            return f"{setting.name}={shown} is below the minimum {setting.min!r}; {setting.min!r} is used"
        if setting.max is not None and value > setting.max:
            return f"{setting.name}={shown} is above the maximum {setting.max!r}; {setting.max!r} is used"
        return None
    if setting.type == "bool":
        if raw.lower() in TRUE_WORDS + FALSE_WORDS:
            return None
        return f"{setting.name}={shown} is not a boolean (1/0, true/false, yes/no, on/off)"
    if setting.choices:
        word = raw.lower()
        word = setting.aliases.get(word, word)
        if word in setting.choices:
            return None
        guess = difflib.get_close_matches(word, setting.choices, n=1, cutoff=0.6)
        hint = f" (did you mean {guess[0]}?)" if guess else ""
        fallback = f"the default {setting.default!r} is used" if setting.default is not None else "it is ignored"
        return f"{setting.name}={shown} is not one of {', '.join(setting.choices)}{hint}; {fallback}"
    return None


MIN_TOKEN_CHARS = 32
MIN_JWT_SECRET_BYTES = 32


def secret_problems(environ: Mapping[str, str] | None = None) -> list[str]:
    """Weak bearer secrets (SEC-009): TRIBOS_API_TOKENS entries whose token is shorter than 32 characters, and a
    TRIBOS_JWT_SECRET (HS256) shorter than 32 bytes. Entries are named by position; values are never included."""
    env = os.environ if environ is None else environ
    problems: list[str] = []
    entries = [p.strip() for p in (env.get("TRIBOS_API_TOKENS") or "").split(",") if p.strip()]
    short = [str(i) for i, pair in enumerate(entries, 1) if len(pair.rpartition(":")[0]) < MIN_TOKEN_CHARS]
    if short:
        problems.append(f"TRIBOS_API_TOKENS entr{'y' if len(short) == 1 else 'ies'} {', '.join(short)} of {len(entries)} "
                        f"ha{'s' if len(short) == 1 else 've'} a token shorter than {MIN_TOKEN_CHARS} characters; "
                        "use long random tokens (e.g. `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`)")
    secret = (env.get("TRIBOS_JWT_SECRET") or "").strip()
    if secret and len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        problems.append(f"TRIBOS_JWT_SECRET is shorter than {MIN_JWT_SECRET_BYTES} bytes, too weak for HS256")
    return problems


# Old product name (CI-6): environment variables and default state directories that are no longer read.
LEGACY_PREFIX = "PHRONESIS_"
LEGACY_DIRS = (".phronesis_memory", ".phronesis_runs", ".phronesis_uploads")
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]  # the same root as tribos.utils.paths.WORKSPACE_ROOT


def legacy_problems(environ: Mapping[str, str] | None = None, *, check_dirs: bool = True) -> list[str]:
    """Leftovers of the rename to Tribos: PHRONESIS_* variables (with their TRIBOS_* name) and .phronesis_* state
    directories in the default locations (the workspace root and the current directory), which Tribos ignores."""
    env = os.environ if environ is None else environ
    problems: list[str] = []
    for name in sorted(env):
        if not name.upper().startswith(LEGACY_PREFIX):
            continue
        new = "TRIBOS_" + name[len(LEGACY_PREFIX):].upper()
        target = f"rename it to {new}" if new in REGISTRY else f"no {new} setting exists, so remove it"
        problems.append(f"{name} is set but is no longer read (Phronesis was renamed to Tribos); {target}")
    if check_dirs:
        roots = dict.fromkeys((_WORKSPACE_ROOT, Path.cwd().resolve()))
        for root in roots:
            for legacy in LEGACY_DIRS:
                path = root / legacy
                try:
                    found = path.is_dir()
                except OSError:
                    found = False
                if found:
                    current = ".tribos_" + legacy.split("_", 1)[1]
                    problems.append(f"legacy state directory {path} is ignored; move its contents to {root / current} "
                                    "(or set TRIBOS_DATA_DIR)")
    return problems


def validate_environment(environ: Mapping[str, str] | None = None) -> list[str]:
    """Human-readable configuration problems: unparsable or out-of-range numbers, unknown choices, non-boolean
    flags, TRIBOS_* variables that no code reads (likely typos, with a suggestion) and weak bearer secrets.
    Never raises. Leftovers of the Phronesis rename (PHRONESIS_* variables; .phronesis_* directories when reading os.environ)
    are logged once as warnings but not returned, so TRIBOS_STRICT_CONFIG=1 does not refuse to start over them."""
    env = os.environ if environ is None else environ
    problems: list[str] = []
    try:
        problems.extend(secret_problems(env))
        for message in legacy_problems(env, check_dirs=environ is None):
            _warn_once("legacy", message, f"Configuration: {message}")
    except Exception as exc:  # noqa: BLE001 - validation must never break startup
        problems.append(f"configuration check failed ({type(exc).__name__})")
    for name, setting in REGISTRY.items():
        value = env.get(name)
        if value is None or not value.strip():
            continue
        try:
            problem = _problem(setting, value.strip())
        except Exception as exc:  # noqa: BLE001 - validation must never break startup
            problem = f"{name} could not be validated ({type(exc).__name__})"
        if problem:
            problems.append(problem)
    # Compare without the shared prefix, which would otherwise make every name look similar.
    prefix = "TRIBOS_"
    known = {n[len(prefix):]: n for n in REGISTRY if n.startswith(prefix)}
    for name in sorted(env):
        upper = name.upper()
        if not upper.startswith(prefix) or upper in REGISTRY or upper in EXTERNAL_NAMES:
            continue
        guess = difflib.get_close_matches(upper[len(prefix):], list(known), n=1, cutoff=0.75)
        hint = f"; did you mean {known[guess[0]]}?" if guess else ""
        problems.append(f"{name} is set but no setting of that name exists{hint}")
    return problems


def describe_type(setting: Setting) -> str:
    """Short type text for the docs: `int (1 to 16)`, `off | auto | on`, `bool`, ..."""
    if setting.choices:
        return " | ".join(setting.choices)
    text = setting.type

    def fmt(v: float) -> str:
        return str(int(v)) if setting.type == "int" else f"{float(v):g}"

    if setting.min is not None and setting.max is not None:
        text += f" ({fmt(setting.min)} to {fmt(setting.max)})"
    elif setting.min is not None:
        text += f" (>= {fmt(setting.min)})"
    elif setting.max is not None:
        text += f" (<= {fmt(setting.max)})"
    return text


def format_default(setting: Setting) -> str | None:
    """The registered default as it would be written in a .env file (None when there is none)."""
    value = setting.default
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return setting.sep.join(str(v) for v in value)
    return str(value)
