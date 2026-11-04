"""Offline lexicon of mathematical concepts, physical constants, named equations,
engineering materials, and dynamical systems for Tribos.

Used by :mod:`tribos.agents.query_planner` to ground STEM entities when network
APIs are unavailable or before issuing upstream searches. Also preserves
backward-compatible symbol/acronym helpers for callers during transition.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Mathematical Concepts & Theorems
# ---------------------------------------------------------------------------
CONCEPT_LEXICON: dict[str, dict[str, Any]] = {
    "banach fixed-point theorem": {
        "canonical": "Banach fixed-point theorem",
        "domain": "mathematics",
        "subdomain": "functional analysis",
        "aliases": ("contraction mapping theorem", "contraction mapping principle", "banach fixed point theorem"),
        "description": "Every contraction mapping on a non-empty complete metric space has a unique fixed point.",
    },
    "cauchy-schwarz inequality": {
        "canonical": "Cauchy-Schwarz inequality",
        "domain": "mathematics",
        "subdomain": "linear algebra / analysis",
        "aliases": ("cauchy schwarz", "cauchy-bunyakovsky-schwarz inequality"),
        "description": "Upper bound on the absolute value of an inner product in terms of the product of norms.",
    },
    "spectral theorem": {
        "canonical": "Spectral theorem",
        "domain": "mathematics",
        "subdomain": "linear algebra / operator theory",
        "aliases": ("spectral decomposition", "hermitian eigendecomposition"),
        "description": "Normal or self-adjoint operators admit an orthogonal spectral decomposition.",
    },
    "fourier transform": {
        "canonical": "Fourier transform",
        "domain": "mathematics",
        "subdomain": "harmonic analysis",
        "aliases": ("fast fourier transform", "fft", "dft", "discrete fourier transform"),
        "description": "Integral transform decomposing a function into its constituent frequencies.",
    },
    "laplace transform": {
        "canonical": "Laplace transform",
        "domain": "mathematics",
        "subdomain": "integral transforms",
        "aliases": ("inverse laplace transform", "s-domain transform"),
        "description": "Integral transform converting linear differential equations into algebraic equations in s.",
    },
    "central limit theorem": {
        "canonical": "Central limit theorem",
        "domain": "mathematics",
        "subdomain": "probability theory",
        "aliases": ("clt", "lindeberg-levy clt"),
        "description": "Normalized sums of independent random variables converge in distribution to a normal law.",
    },
    "noether's theorem": {
        "canonical": "Noether's theorem",
        "domain": "physics",
        "subdomain": "theoretical mechanics",
        "aliases": ("noether theorem", "noether symmetry"),
        "description": "Every differentiable symmetry of the action of a physical system has a corresponding conservation law.",
    },
    "riemann zeta function": {
        "canonical": "Riemann zeta function",
        "domain": "mathematics",
        "subdomain": "analytic number theory",
        "aliases": ("zeta function", "riemann hypothesis"),
        "description": "Analytic continuation of the Dirichlet series sum(n^-s) encoding prime number distribution.",
    },
    "stokes' theorem": {
        "canonical": "Stokes' theorem",
        "domain": "mathematics",
        "subdomain": "differential geometry / vector calculus",
        "aliases": ("stokes theorem", "generalized stokes theorem", "kelvin-stokes theorem"),
        "description": "Integral of a differential form omega over the boundary of an orientable manifold equals the integral of d(omega) over the manifold.",
    },
    "divergence theorem": {
        "canonical": "Divergence theorem",
        "domain": "mathematics",
        "subdomain": "vector calculus",
        "aliases": ("gauss's theorem", "gauss divergence theorem", "ostrogradsky's theorem"),
        "description": "Outward flux of a vector field through a closed surface equals the volume integral of the divergence.",
    },
    "residue theorem": {
        "canonical": "Cauchy's residue theorem",
        "domain": "mathematics",
        "subdomain": "complex analysis",
        "aliases": ("residue theorem", "cauchy residue theorem", "contour integration"),
        "description": "Line integral of a meromorphic function around a closed curve equals 2*pi*i times the sum of residues.",
    },
    "singular value decomposition": {
        "canonical": "Singular value decomposition",
        "domain": "mathematics",
        "subdomain": "numerical linear algebra",
        "aliases": ("svd",),
        "description": "Factorization of a real or complex matrix into U Sigma V^*.",
    },
    "lyapunov stability": {
        "canonical": "Lyapunov stability",
        "domain": "engineering",
        "subdomain": "nonlinear dynamical systems",
        "aliases": ("lyapunov function", "lyapunov exponent", "asymptotic stability"),
        "description": "Stability characterization of dynamical system trajectories near an equilibrium point.",
    },
    "kalman filter": {
        "canonical": "Kalman filter",
        "domain": "engineering",
        "subdomain": "estimation and control",
        "aliases": ("linear quadratic estimation", "ekf", "extended kalman filter"),
        "description": "Recursive minimum-variance state estimator for linear dynamical systems under Gaussian noise.",
    },
    "catalan numbers": {
        "canonical": "Catalan numbers",
        "domain": "mathematics",
        "subdomain": "combinatorics",
        "aliases": ("catalan sequence", "a000108"),
        "id": "A000108",
        "description": "Combinatorial sequence C_n = (1/(n+1)) binomial(2n, n) (OEIS A000108).",
    },
    "fibonacci numbers": {
        "canonical": "Fibonacci sequence",
        "domain": "mathematics",
        "subdomain": "number theory / combinatorics",
        "aliases": ("fibonacci sequence", "a000045"),
        "id": "A000045",
        "description": "Integer sequence F_n = F_{n-1} + F_{n-2} with F_0=0, F_1=1 (OEIS A000045).",
    },
}

# ---------------------------------------------------------------------------
# Named Equations & Physical Laws
# ---------------------------------------------------------------------------
EQUATION_LEXICON: dict[str, dict[str, Any]] = {
    "navier-stokes equations": {
        "canonical": "Navier-Stokes equations",
        "domain": "physics / fluid mechanics",
        "aliases": ("navier-stokes", "navier stokes", "incompressible navier-stokes"),
        "latex": r"\rho (\partial_t \mathbf{u} + (\mathbf{u}\cdot\nabla)\mathbf{u}) = -\nabla p + \mu \nabla^2 \mathbf{u} + \mathbf{f}",
        "description": "Partial differential equations governing momentum conservation in viscous fluids.",
    },
    "schrodinger equation": {
        "canonical": "Schrödinger equation",
        "domain": "physics / quantum mechanics",
        "aliases": ("schroedinger equation", "schrödinger equation", "time-dependent schrodinger equation", "time-independent schrodinger equation"),
        "latex": r"i\hbar \frac{\partial \Psi}{\partial t} = \hat{H}\Psi",
        "description": "Fundamental wave equation governing the quantum state evolution of a physical system.",
    },
    "maxwell's equations": {
        "canonical": "Maxwell's equations",
        "domain": "physics / electromagnetism",
        "aliases": ("maxwell equations", "maxwell-faraday equation", "ampere-maxwell law"),
        "latex": r"\nabla \cdot \mathbf{E} = \rho/\varepsilon_0,\; \nabla \times \mathbf{B} = \mu_0 \mathbf{J} + \mu_0\varepsilon_0 \partial_t \mathbf{E}",
        "description": "Coupled partial differential equations describing classical electric and magnetic fields.",
    },
    "euler-bernoulli beam equation": {
        "canonical": "Euler-Bernoulli beam equation",
        "domain": "engineering / solid mechanics",
        "aliases": ("euler-bernoulli beam", "beam deflection equation", "cantilever beam deflection"),
        "latex": r"\frac{\mathrm{d}^2}{\mathrm{d}x^2}\left(EI\frac{\mathrm{d}^2 w}{\mathrm{d}x^2}\right) = q(x)",
        "description": "Fourth-order ODE/PDE relating transverse load q(x) to small-deflection bending w(x) of a slender beam.",
    },
    "heat equation": {
        "canonical": "Heat equation",
        "domain": "physics / PDEs",
        "aliases": ("fourier heat conduction equation", "diffusion equation"),
        "latex": r"\frac{\partial u}{\partial t} = \alpha \nabla^2 u",
        "description": "Parabolic partial differential equation describing thermal diffusion or Brownian transport.",
    },
    "wave equation": {
        "canonical": "Wave equation",
        "domain": "physics / PDEs",
        "aliases": ("d'alembert wave equation", "acoustic wave equation"),
        "latex": r"\frac{\partial^2 u}{\partial t^2} = c^2 \nabla^2 u",
        "description": "Hyperbolic partial differential equation governing linear wave propagation at speed c.",
    },
    "helmholtz equation": {
        "canonical": "Helmholtz equation",
        "domain": "mathematics / mathematical physics",
        "aliases": ("reduced wave equation",),
        "latex": r"\nabla^2 u + k^2 u = 0",
        "description": "Elliptic eigenvalue PDE arising from time-harmonic solutions of the wave equation.",
    },
    "poisson's equation": {
        "canonical": "Poisson's equation",
        "domain": "mathematics / electrostatics",
        "aliases": ("poisson equation", "laplace's equation", "laplace equation"),
        "latex": r"\nabla^2 \varphi = f",
        "description": "Elliptic partial differential equation relating a scalar potential to its source density.",
    },
    "euler-lagrange equation": {
        "canonical": "Euler-Lagrange equation",
        "domain": "mathematics / calculus of variations",
        "aliases": ("euler lagrange equation", "stationary action equation"),
        "latex": r"\frac{\partial L}{\partial q_i} - \frac{\mathrm{d}}{\mathrm{d}t}\frac{\partial L}{\partial \dot{q}_i} = 0",
        "description": "Second-order differential conditions satisfied by stationary paths of an action functional.",
    },
    "bernoulli's equation": {
        "canonical": "Bernoulli's equation",
        "domain": "physics / fluid mechanics",
        "aliases": ("bernoulli equation", "bernoulli principle"),
        "latex": r"p + \tfrac{1}{2}\rho v^2 + \rho g z = \text{const}",
        "description": "Conservation of mechanical energy along a streamline in steady, inviscid, incompressible flow.",
    },
    "carnot efficiency": {
        "canonical": "Carnot efficiency",
        "domain": "physics / thermodynamics",
        "aliases": ("carnot cycle efficiency", "carnot limit"),
        "latex": r"\eta_{\max} = 1 - \frac{T_C}{T_H}",
        "description": "Maximum thermodynamic efficiency achievable by a heat engine operating between reservoirs at T_C and T_H.",
    },
    "shannon-hartley theorem": {
        "canonical": "Shannon-Hartley channel capacity",
        "domain": "engineering / information theory",
        "aliases": ("shannon capacity", "awgn channel capacity"),
        "latex": r"C = B \log_2(1 + \mathrm{SNR})",
        "description": "Maximum error-free information rate over an additive white Gaussian noise channel of bandwidth B.",
    },
    "black-scholes equation": {
        "canonical": "Black-Scholes PDE",
        "domain": "applied mathematics",
        "aliases": ("black-scholes", "black scholes formula"),
        "latex": r"\frac{\partial V}{\partial t} + \tfrac{1}{2}\sigma^2 S^2 \frac{\partial^2 V}{\partial S^2} + r S \frac{\partial V}{\partial S} - rV = 0",
        "description": "Parabolic PDE governing derivative pricing under geometric Brownian motion.",
    },
}

# ---------------------------------------------------------------------------
# CODATA Physical Constants
# ---------------------------------------------------------------------------
CONSTANT_LEXICON: dict[str, dict[str, Any]] = {
    "speed of light": {
        "canonical": "speed of light in vacuum",
        "symbol": "c",
        "value": 299792458.0,
        "units": "m/s",
        "aliases": ("speed of light in vacuum", "vacuum speed of light", "c_0"),
        "id": "CODATA:c",
    },
    "planck constant": {
        "canonical": "Planck constant",
        "symbol": "h",
        "value": 6.62607015e-34,
        "units": "J*s",
        "aliases": ("planck's constant",),
        "id": "CODATA:h",
    },
    "reduced planck constant": {
        "canonical": "reduced Planck constant",
        "symbol": "hbar",
        "value": 1.054571817e-34,
        "units": "J*s",
        "aliases": ("dirac constant", "h-bar", "hbar"),
        "id": "CODATA:hbar",
    },
    "gravitational constant": {
        "canonical": "Newtonian constant of gravitation",
        "symbol": "G",
        "value": 6.67430e-11,
        "units": "m^3/(kg*s^2)",
        "aliases": ("newtonian constant of gravitation", "universal gravitational constant", "newton's constant"),
        "id": "CODATA:G",
    },
    "boltzmann constant": {
        "canonical": "Boltzmann constant",
        "symbol": "k_B",
        "value": 1.380649e-23,
        "units": "J/K",
        "aliases": ("boltzmann's constant", "k_b"),
        "id": "CODATA:k_B",
    },
    "elementary charge": {
        "canonical": "elementary charge",
        "symbol": "e",
        "value": 1.602176634e-19,
        "units": "C",
        "aliases": ("electron charge magnitude", "fundamental charge"),
        "id": "CODATA:e",
    },
    "avogadro constant": {
        "canonical": "Avogadro constant",
        "symbol": "N_A",
        "value": 6.02214076e23,
        "units": "1/mol",
        "aliases": ("avogadro's number", "avogadro number"),
        "id": "CODATA:N_A",
    },
    "molar gas constant": {
        "canonical": "molar gas constant",
        "symbol": "R",
        "value": 8.314462618,
        "units": "J/(mol*K)",
        "aliases": ("universal gas constant", "ideal gas constant"),
        "id": "CODATA:R",
    },
    "stefan-boltzmann constant": {
        "canonical": "Stefan-Boltzmann constant",
        "symbol": "sigma",
        "value": 5.670374419e-8,
        "units": "W/(m^2*K^4)",
        "aliases": ("stefan boltzmann constant",),
        "id": "CODATA:sigma",
    },
    "vacuum electric permittivity": {
        "canonical": "vacuum electric permittivity",
        "symbol": "epsilon_0",
        "value": 8.8541878188e-12,
        "units": "F/m",
        "aliases": ("permittivity of free space", "electric constant", "epsilon_0"),
        "id": "CODATA:epsilon_0",
    },
    "vacuum magnetic permeability": {
        "canonical": "vacuum magnetic permeability",
        "symbol": "mu_0",
        "value": 1.25663706127e-6,
        "units": "N/A^2",
        "aliases": ("permeability of free space", "magnetic constant", "mu_0"),
        "id": "CODATA:mu_0",
    },
    "standard acceleration of gravity": {
        "canonical": "standard acceleration of gravity",
        "symbol": "g_0",
        "value": 9.80665,
        "units": "m/s^2",
        "aliases": ("standard gravity", "earth standard gravity"),
        "id": "CODATA:g_0",
    },
    "electron mass": {
        "canonical": "electron mass",
        "symbol": "m_e",
        "value": 9.1093837139e-31,
        "units": "kg",
        "aliases": ("rest mass of electron",),
        "id": "CODATA:m_e",
    },
    "proton mass": {
        "canonical": "proton mass",
        "symbol": "m_p",
        "value": 1.67262192595e-27,
        "units": "kg",
        "aliases": ("rest mass of proton",),
        "id": "CODATA:m_p",
    },
    "fine-structure constant": {
        "canonical": "fine-structure constant",
        "symbol": "alpha",
        "value": 7.2973525643e-3,
        "units": "dimensionless",
        "aliases": ("fine structure constant", "sommerfeld constant"),
        "id": "CODATA:alpha",
    },
}

# ---------------------------------------------------------------------------
# Engineering Materials & Substances
# ---------------------------------------------------------------------------
MATERIAL_LEXICON: dict[str, dict[str, Any]] = {
    "structural steel": {
        "canonical": "Structural steel (A36 / S235)",
        "aliases": ("a36 steel", "carbon steel", "mild steel", "aisi 1020", "aisi 4140"),
        "youngs_modulus_gpa": 200.0,
        "density_kg_m3": 7850.0,
        "yield_strength_mpa": 250.0,
        "thermal_conductivity_w_mk": 50.0,
    },
    "stainless steel 304": {
        "canonical": "Stainless steel 304",
        "aliases": ("aisi 304", "304 stainless steel", "316 stainless steel", "aisi 316", "stainless steel"),
        "youngs_modulus_gpa": 193.0,
        "density_kg_m3": 8000.0,
        "yield_strength_mpa": 215.0,
        "thermal_conductivity_w_mk": 16.2,
    },
    "aluminum 6061": {
        "canonical": "Aluminum 6061-T6",
        "aliases": ("6061-t6", "aluminum 6061-t6", "aluminium 6061", "al 6061", "aluminum 7075", "7075-t6", "aluminum alloy"),
        "youngs_modulus_gpa": 68.9,
        "density_kg_m3": 2700.0,
        "yield_strength_mpa": 276.0,
        "thermal_conductivity_w_mk": 167.0,
    },
    "titanium ti-6al-4v": {
        "canonical": "Titanium Ti-6Al-4V",
        "aliases": ("ti-6al-4v", "ti6al4v", "grade 5 titanium", "titanium alloy"),
        "youngs_modulus_gpa": 113.8,
        "density_kg_m3": 4430.0,
        "yield_strength_mpa": 880.0,
        "thermal_conductivity_w_mk": 6.7,
    },
    "copper": {
        "canonical": "Copper (OFHC)",
        "aliases": ("oxygen-free copper", "pure copper", "cu"),
        "youngs_modulus_gpa": 117.0,
        "density_kg_m3": 8960.0,
        "yield_strength_mpa": 70.0,
        "thermal_conductivity_w_mk": 401.0,
        "id": "mp-30",
    },
    "silicon": {
        "canonical": "Silicon (crystalline)",
        "aliases": ("crystalline silicon", "monocrystalline silicon", "si wafer"),
        "youngs_modulus_gpa": 150.0,
        "density_kg_m3": 2329.0,
        "band_gap_ev": 1.12,
        "thermal_conductivity_w_mk": 149.0,
        "id": "mp-149",
    },
    "gallium nitride": {
        "canonical": "Gallium nitride (GaN)",
        "aliases": ("gan", "wurtzite gan"),
        "band_gap_ev": 3.4,
        "density_kg_m3": 6150.0,
        "id": "mp-804",
    },
    "silicon carbide": {
        "canonical": "Silicon carbide (SiC)",
        "aliases": ("4h-sic", "6h-sic", "sic"),
        "youngs_modulus_gpa": 410.0,
        "density_kg_m3": 3210.0,
        "band_gap_ev": 3.26,
        "id": "mp-11714",
    },
}

# ---------------------------------------------------------------------------
# Dynamical Systems & Canonical Models
# ---------------------------------------------------------------------------
SYSTEM_LEXICON: dict[str, dict[str, Any]] = {
    # The two entries match the Dynamis presets of the same canonical name (tribos/dynamis/engine.py ODE_PRESETS).
    "harmonic oscillator": {
        "canonical": "harmonic_oscillator",
        "display_name": "Simple Harmonic Oscillator",
        "aliases": ("simple harmonic oscillator", "undamped oscillator", "undamped harmonic oscillator",
                    "mass-spring system", "spring-mass system", "mass-spring", "spring-mass", "sho"),
        "state_vars": ("x", "v"),
        "params": {"omega": 1.0},
        "description": "Undamped linear oscillator dx/dt = v, dv/dt = -omega^2*x.",
    },
    "damped oscillator": {
        "canonical": "damped_oscillator",
        "display_name": "Damped Harmonic Oscillator",
        "aliases": ("damped harmonic oscillator", "forced damped oscillator", "damped driven oscillator",
                    "forced oscillator", "mass-spring-damper", "damped spring mass", "damped mass spring"),
        "state_vars": ("x", "v"),
        "params": {"omega": 2.0, "zeta": 0.15},
        "description": "Second-order linear oscillator dx/dt = v, dv/dt = -2*zeta*omega*v - omega^2*x.",
    },
    "van der pol": {
        "canonical": "van_der_pol",
        "display_name": "Van der Pol Oscillator",
        "aliases": ("van der pol oscillator", "van-der-pol", "vdp oscillator"),
        "state_vars": ("x", "y"),
        "params": {"mu": 1.0},
        "description": "Nonlinear oscillator with non-conservative damping exhibiting a stable limit cycle.",
    },
    "lorenz": {
        "canonical": "lorenz",
        "display_name": "Lorenz Attractor System",
        "aliases": ("lorenz system", "lorenz attractor", "lorenz equations", "lorenz 63"),
        "state_vars": ("x", "y", "z"),
        "params": {"sigma": 10.0, "rho": 28.0, "beta": 2.6666667},
        "description": "Three-dimensional chaotic atmospheric convection ODE system.",
    },
    "lotka-volterra": {
        "canonical": "lotka_volterra",
        "display_name": "Lotka-Volterra Predator-Prey System",
        "aliases": ("lotka volterra", "predator-prey model", "predator prey system", "lotka-volterra equations"),
        "state_vars": ("x", "y"),
        "params": {"alpha": 1.1, "beta": 0.4, "delta": 0.1, "gamma": 0.4},
        "description": "Coupled first-order nonlinear ODEs modeling two-species population dynamics.",
    },
    "sir": {
        "canonical": "sir",
        "display_name": "SIR Compartmental System",
        "aliases": ("sir model", "kermack-mckendrick model", "susceptible-infectious-recovered"),
        "state_vars": ("S", "I", "R"),
        "params": {"beta": 0.3, "gamma": 0.1},
        "description": "Three-compartment dynamical system dS/dt = -beta*S*I, dI/dt = beta*S*I - gamma*I, dR/dt = gamma*I.",
    },
    "double pendulum": {
        "canonical": "double_pendulum",
        "display_name": "Double Pendulum",
        "aliases": ("chaotic double pendulum", "coupled pendulum"),
        "state_vars": ("theta1", "omega1", "theta2", "omega2"),
        "params": {"m1": 1.0, "m2": 1.0, "L1": 1.0, "L2": 1.0, "g": 9.80665},
        "description": "Hamiltonian mechanical system of two coupled pendulums exhibiting chaotic trajectories.",
    },
    "duffing": {
        "canonical": "duffing",
        "display_name": "Duffing Oscillator",
        "aliases": ("duffing oscillator", "duffing equation"),
        "state_vars": ("x", "v"),
        "params": {"delta": 0.2, "alpha": -1.0, "beta": 1.0, "gamma": 0.3, "omega": 1.2},
        "description": "Driven damped oscillator with cubic nonlinear restoring stiffness.",
    },
    "rc circuit": {
        "canonical": "rc_rlc_circuit",
        "display_name": "RLC Circuit",
        "aliases": ("rlc circuit", "series rlc circuit", "parallel rlc circuit", "rc circuit", "rl circuit"),
        "state_vars": ("q", "I"),
        "params": {"R": 10.0, "L": 0.1, "C": 1e-4},
        "description": "Linear lumped-element electrical circuit governed by L d^2q/dt^2 + R dq/dt + q/C = V(t).",
    },
}


def _match_lexicon(text: str, lexicon: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Find all lexicon entries whose key or alias appears in ``text``."""
    lower = (text or "").lower()
    if not lower.strip():
        return []
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, info in lexicon.items():
        canonical = str(info.get("canonical") or key)
        if canonical in seen:
            continue
        candidates = (key, *info.get("aliases", ()))
        for cand in candidates:
            if not cand:
                continue
            # "mass-spring", "mass spring" and "mass–spring" (en dash) are the same name.
            words = re.split(r"[\s\-‐‑‒–—]+", cand.lower())
            pattern = r"(?<![a-z0-9])" + r"[\s\-‐‑‒–—]+".join(re.escape(w) for w in words) + r"(?![a-z0-9])"
            m = re.search(pattern, lower)
            if m:
                seen.add(canonical)
                span = (m.start(), m.end())
                mention = text[m.start():m.end()]
                hits.append({"key": key, "mention": mention, "span": span, **info})
                break
    return hits


def find_offline_concepts(text: str) -> list[dict[str, Any]]:
    """Return mathematical/scientific concepts matched in ``text``."""
    return _match_lexicon(text, CONCEPT_LEXICON)


def find_offline_equations(text: str) -> list[dict[str, Any]]:
    """Return named equations or physical laws matched in ``text``."""
    return _match_lexicon(text, EQUATION_LEXICON)


def find_offline_constants(text: str) -> list[dict[str, Any]]:
    """Return CODATA physical constants matched in ``text``."""
    return _match_lexicon(text, CONSTANT_LEXICON)


def find_offline_materials(text: str) -> list[dict[str, Any]]:
    """Return engineering materials or crystal substances matched in ``text``."""
    return _match_lexicon(text, MATERIAL_LEXICON)


def find_offline_systems(text: str) -> list[dict[str, Any]]:
    """Return dynamical systems matched in ``text``. A match inside a longer one is dropped: "damped harmonic
    oscillator" is the damped system, not also the undamped "harmonic oscillator" it contains."""
    found = _match_lexicon(text, SYSTEM_LEXICON)

    def inside(a: dict[str, Any], b: dict[str, Any]) -> bool:
        (s1, e1), (s2, e2) = a.get("span") or (0, 0), b.get("span") or (0, 0)
        return s2 <= s1 and e1 <= e2 and (e2 - s2) > (e1 - s1)

    return [m for m in found if not any(inside(m, other) for other in found if other is not m)]


_QUANTITY_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:([A-Za-z][A-Za-z0-9_\']*(?:\([0-9]+\))?)\s*=\s*)?"
    r"([+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"(m/s\^2|m/s2|m/s|km/s|km/h|m\^2|m\^3|mm|cm|km|nm|um|"
    r"kg/m\^3|kg|g|mg|"
    r"GPa|MPa|kPa|Pa|bar|atm|"
    r"GN|MN|kN|N\*s/m|N·s/m|N s/m|N/m|kN/m|N/mm|N|N\*m|N·m|"
    r"GeV|MeV|keV|eV|GJ|MJ|kJ|J|mJ|GW|MW|kW|W|mW|"
    r"GHz|MHz|kHz|Hz|rad/s|rpm|"
    r"K|degC|°C|"
    r"kV|V|mV|kA|A|mA|uA|MOhm|kOhm|Ohm|Ω|mF|uF|nF|pF|F|mH|uH|H|T|"
    r"mol/L|mol|ms|s|m)\b"
)


def _infer_physical_type(unit: str, param_name: str | None = None) -> str:
    u = (unit or "").lower()
    p = (param_name or "").lower()
    if p.startswith("m") and u in ("kg", "g", "mg"):
        return "mass"
    if p.startswith("c") and ("s/m" in u or "kg/s" in u):
        return "damping"
    if p.startswith("k") and ("/m" in u or "n/mm" in u):
        return "stiffness"
    if p.startswith("f") and u in ("n", "kn", "mn"):
        return "force"
    if ("w" in p or "omega" in p) and "rad/s" in u:
        return "frequency"
    if u in ("kg", "g", "mg", "kg/m^3"):
        return "mass"
    if "s/m" in u or u == "kg/s":
        return "damping"
    if ("/m" in u or "n/mm" in u) and "s" not in u:
        return "stiffness"
    if u in ("n", "kn", "mn"):
        return "force"
    if u in ("rad/s", "hz", "khz", "mhz", "ghz", "rpm"):
        return "frequency"
    if u in ("m/s", "km/h", "km/s"):
        return "velocity"
    if u in ("m/s^2", "m/s2"):
        return "acceleration"
    if u in ("pa", "kpa", "mpa", "gpa", "bar", "atm"):
        return "pressure"
    if u in ("j", "kj", "mj", "ev"):
        return "energy"
    if u in ("w", "kw", "mw"):
        return "power"
    if u in ("s", "ms"):
        return "time"
    if u in ("m", "mm", "cm", "km", "nm", "um"):
        return "length"
    return "quantity"


_AMBIGUOUS_UNITS: frozenset[str] = frozenset(
    {"m", "s", "g", "h", "d", "t", "l", "L", "N", "J", "W", "V", "A", "C", "F", "H", "T", "K", "Pa"}
)

_PHYSICAL_CONTEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "m": (
        "length", "distance", "height", "depth", "width", "altitude", "radius", "diameter",
        "thickness", "wavelength", "displacement", "span", "long", "wide", "tall", "deep",
        "meter", "metre", "meters", "metres", "wire", "rope", "rod", "beam", "cable", "track",
        "travel", "travels", "traveled", "moves", "moved", "speed", "velocity", "acceleration",
        "drop", "drops", "fall", "falls", "perimeter", "circumference", "elevation",
    ),
    "s": (
        "time", "duration", "period", "interval", "second", "seconds", "sec", "elapsed",
        "after", "during", "wait", "waits", "takes", "clock", "speed", "velocity", "acceleration",
        "rate", "frequency", "travel", "travels", "traveled", "move", "moves", "moved", "motion",
        "run", "runs", "ran", "flight", "car", "particle",
    ),
    "g": (
        "mass", "weight", "gram", "grams", "weigh", "weighs", "weighed", "substance", "sample",
        "powder", "dose", "dosage", "dissolve", "dissolves", "dissolved", "solution", "solute",
        "solvent", "concentration", "salt", "water", "mixture", "compound", "acid", "base",
    ),
    "h": ("hour", "hours", "duration", "time", "period", "elapsed"),
    "d": ("day", "days", "duration", "time", "period", "elapsed"),
    "t": ("tonne", "tonnes", "tons", "mass", "weight", "payload", "load"),
    "l": ("liter", "litre", "liters", "litres", "volume", "capacity", "fluid", "liquid", "tank"),
    "L": ("liter", "litre", "liters", "litres", "volume", "capacity", "fluid", "liquid", "tank"),
    "N": ("force", "tension", "load", "newton", "newtons", "thrust", "friction", "weight"),
    "J": ("energy", "work", "heat", "joule", "joules"),
    "W": ("power", "watt", "watts"),
    "V": ("voltage", "volt", "volts", "potential"),
    "A": ("current", "ampere", "amperes", "amp", "amps"),
    "C": ("charge", "coulomb", "coulombs"),
    "F": ("capacitance", "farad", "farads"),
    "H": ("inductance", "henry", "henries"),
    "T": ("magnetic", "tesla", "teslas", "field"),
    "K": ("temperature", "kelvin"),
    "Pa": ("pressure", "stress", "pascal", "pascals"),
}


def extract_declared_variables(text: str) -> set[str]:
    """Identify variables explicitly declared in mathematical / algorithmic context in text."""
    if not text:
        return set()
    declared: set[str] = set()

    # Authoritative problem spec assumptions if available
    try:
        from ..axiom.problem import parse_problem
        spec = parse_problem(text)
        if spec.assumptions:
            for k in spec.assumptions:
                if len(k) == 1 and k.isalpha():
                    declared.add(k)
        if spec.variable and len(spec.variable) == 1 and spec.variable.isalpha():
            declared.add(spec.variable)
    except Exception:
        pass

    # 1. 'for every nonnegative integer m', 'for integer m', 'for any real x'
    for m in re.finditer(
        r"\bfor\s+(?:every|all|any|each|some)\s+(?:non[\s-]?negative|positive|negative|non-positive)?\s*"
        r"(?:integer|real|natural|rational|complex|scalar|vector|matrix)?s?\s+([a-zA-Z])\b",
        text,
        re.I,
    ):
        declared.add(m.group(1))

    # 2. 'nonnegative integer m', 'positive integer m', 'integer m', 'real x'
    for m in re.finditer(
        r"\b(?:non[\s-]?negative|positive|negative|non-positive)\s+(?:integers?|reals?|naturals?)\s+([a-zA-Z])\b",
        text,
        re.I,
    ):
        declared.add(m.group(1))
    for m in re.finditer(r"\b(?:integers?|naturals?)\s+([a-zA-Z])\b", text, re.I):
        declared.add(m.group(1))

    # 3. 'declare i a nonnegative integer', 'let m be a real number', 'assume s is positive'
    for m in re.finditer(
        r"\b(?:declare|let|assume|given|consider|suppose)\s+([a-zA-Z]{1,3})\s+"
        r"(?:to\s+be\s+|as\s+|be\s+|is\s+|in\s+)?(?:an?\s+)?"
        r"(?:non[\s-]?negative|positive|negative|integer|real|natural|rational|complex|parameter|"
        r"scalar|vector|variable|index|constant|generator|element|symbol|matrix|member|subspace|space)\b",
        text,
        re.I,
    ):
        declared.add(m.group(1))

    # 4. 'variable m', 'in variable m', 'in the variable m'
    for m in re.finditer(r"\b(?:in\s+(?:the\s+)?)?variable\s+([a-zA-Z])\b", text, re.I):
        declared.add(m.group(1))

    # 5. 'polynomial in m', 'inequality in m', 'equation in m'
    for m in re.finditer(r"\b(?:polynomial|inequality|equation|expression|function)s?\s+in\s+([a-zA-Z])\b", text, re.I):
        declared.add(m.group(1))

    # 6. 'solve ... for m', 'w.r.t. m'
    for m in re.finditer(r"\bsolve\s+(?:.*?\s+)?for\s+([a-zA-Z])\b", text, re.I):
        declared.add(m.group(1))
    for m in re.finditer(r"\b(?:with\s+respect\s+to|w\.r\.t\.?)\s+([a-zA-Z])\b", text, re.I):
        declared.add(m.group(1))

    # 7. Quantifiers / sets: \forall m, m \in R
    for m in re.finditer(r"(?:\\forall|\u2200)\s*([a-zA-Z])", text):
        declared.add(m.group(1))
    for m in re.finditer(
        r"\b([a-zA-Z])\s*(?:\\in|\u2208|in)\s*(?:\\mathbb\{[A-Za-z]+\}|[RZNCQ]|reals?|integers?)\b", text
    ):
        declared.add(m.group(1))

    # 8. Bounds: m >= 0, i >= 0
    for m in re.finditer(r"\b([a-zA-Z])\s*(?:>=|>|<=|<)\s*0\b", text):
        declared.add(m.group(1))

    # 9. Function parameters: a(i), b(i), f(m)
    for m in re.finditer(r"\b[a-zA-Z]\s*\(\s*([a-zA-Z])\s*\)", text):
        declared.add(m.group(1))

    return declared


def _is_algebraic_occurrence(text: str, start: int, end: int, unit: str) -> bool:
    """Check if the occurrence is part of an algebraic formula (operator adjacency)."""
    after = text[end : end + 15].strip()
    before = text[max(0, start - 15) : start].strip()
    if after and after[0] in "+-*/^=<>≤≥≠":
        return True
    if before and before[-1] in "+-*/^=<>≤≥≠(":
        return True
    if after and re.match(r"^(?:<=|>=|==|!=|\*\*|\\in|in\s+(?:\[|\{|\(|[A-Z]|reals?|integers?|domain))", after):
        return True
    return False


def _in_latex_math(text: str, pos: int) -> bool:
    """Whether `pos` lies inside $...$ math (an odd number of unescaped dollar signs before it)."""
    return len(re.findall(r"(?<!\\)\$", text[:pos])) % 2 == 1


def _has_physical_context(text: str, start: int, end: int, unit: str) -> bool:
    """Check if the text window around the match contains physical domain keywords for unit."""
    window = text[max(0, start - 50) : min(len(text), end + 50)].lower()
    keywords = _PHYSICAL_CONTEXT_KEYWORDS.get(unit, ())
    if any(re.search(rf"\b{re.escape(kw)}\b", window) for kw in keywords):
        return True
    if unit == "s" and re.search(r"\b(?:in|for|at|after|within)\s+\d+(?:\.\d+)?\s*s\b", window):
        return True
    if re.search(rf"\b\d+(?:\.\d+)?\s*{re.escape(unit.lower())}\s+of\s+[a-z]", window):
        return True
    return False


def find_offline_quantities(text: str, declared_variables: set[str] | None = None) -> list[dict[str, Any]]:
    """Extract explicit physical quantities (number + SI/engineering unit) from ``text``,
    distinguishing declared algebraic variables from physical measurements."""
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    declared = (
        set(declared_variables) if declared_variables is not None else extract_declared_variables(text or "")
    )
    for m in _QUANTITY_RE.finditer(text or ""):
        raw = m.group(0).strip()
        if raw in seen:
            continue
        seen.add(raw)
        param_name = m.group(1)
        try:
            val = float(m.group(2))
        except (ValueError, TypeError):
            val = None
        units = m.group(3)
        start, end = m.start(), m.end()
        phys_type = _infer_physical_type(units, param_name)

        if units in _AMBIGUOUS_UNITS and _in_latex_math(text or "", start):
            continue  # "$4m$" is four times the variable m; LaTeX writes a unit as "4\,\mathrm{m}"
        if units in _AMBIGUOUS_UNITS:
            is_declared =units in declared or units.lower() in {d.lower() for d in declared}
            is_alg = _is_algebraic_occurrence(text or "", start, end, units)
            has_phys = _has_physical_context(text or "", start, end, units)

            if is_declared:
                if is_alg or not has_phys:
                    # Declared algebraic variable (e.g. 5m in 5m+4>2m+1), not a physical quantity
                    continue
            else:
                if is_alg and not has_phys:
                    # Algebraic term without explicit quantifier declaration
                    continue
                if not has_phys and not is_alg:
                    # Truly ambiguous: retain ambiguous state
                    hits.append({
                        "canonical": raw,
                        "mention": raw,
                        "label": raw,
                        "span": (start, end),
                        "value": val,
                        "units": units,
                        "param_name": param_name,
                        "physical_type": "ambiguous",
                        "ambiguous": True,
                        "ambiguous_with": [f"variable {units}", f"{phys_type} ({units})"],
                    })
                    continue

        label = f"{param_name} = {val:g} {units}" if param_name and val is not None else raw
        hits.append({
            "canonical": label,
            "mention": raw,
            "label": label,
            "span": (start, end),
            "value": val,
            "units": units,
            "param_name": param_name,
            "physical_type": phys_type,
        })
    return hits


# ---------------------------------------------------------------------------
# Backward-compatible helpers kept so legacy callers / tests never fail on import
# ---------------------------------------------------------------------------
NON_GENE_ACRONYMS: frozenset[str] = frozenset(
    {
        "ODE", "PDE", "SDE", "DAE", "FEM", "FDM", "FVM", "CFD", "BEM", "FFT", "DFT", "SVD",
        "PCA", "RK4", "RK45", "BDF", "CFL", "SNR", "THD", "PWM", "PID", "LQR", "MPC", "KALMAN",
        "MOSFET", "CMOS", "BJT", "FPGA", "ASIC", "VHDL", "SPICE", "RLC", "RMS", "AC", "DC",
        "LASER", "MASER", "LED", "PVT", "EOS", "NPT", "NVT", "NVE", "CCSD", "HF", "MP2",
        "GGA", "PBE", "LDA", "DOS", "BAND", "FCC", "BCC", "HCP", "XRD", "SEM", "TEM", "AFM",
        "STM", "NMR", "IR", "UV", "VIS", "RAMAN", "codata", "NIST", "ISO", "IEEE", "ASME",
        "ASTM", "SIAM", "AMS", "APS", "AIP", "IOP", "ACM", "NASA", "CERN", "ITER",
        "HR", "CI", "OR", "RR", "OS", "PFS", "DFS", "EFS", "ORR", "CR", "PR", "SD", "PD",
        "RCT", "FDA", "EMA", "WHO", "NIH", "DNA", "RNA", "PCR", "ATP", "ADP", "GTP", "GDP",
        "BMI", "ECG", "EEG", "MRI", "CT", "PET", "ICU", "IV", "PO", "BID", "TID", "QD",
    }
)

ENGLISH_WORD_SYMBOLS: frozenset[str] = frozenset(
    {
        "SET", "MAP", "RING", "FIELD", "GROUP", "NORM", "RANK", "SPAN", "TRACE", "KERNEL",
        "IMAGE", "FLOW", "WAVE", "BEAM", "LOAD", "MASS", "FORCE", "WORK", "HEAT", "FLUX",
        "STEP", "RAMP", "POLE", "ZERO", "GAIN", "LOOP", "NODE", "MESH", "GRID", "CELL",
        "CAN", "WAS", "HAS", "HAD", "NOT", "FOR", "AND", "ARE", "ALL", "ANY", "OUT",
    }
)

# Deliberately empty: Tribos resolves no diseases. Kept only because tribos.agents.query_planner still imports it
# (with find_offline_diseases / coordinated_disease_terms below); delete all three once that import is gone.
DISEASE_HEAD_WORDS: frozenset[str] = frozenset()


def defined_acronyms(text: str) -> dict[str, str]:
    """Extract acronyms defined inline as ``Full Name (ACR)`` mapped to ``"concept"``."""
    out: dict[str, str] = {}
    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9\s\-]{3,60})\s*\(([A-Z][A-Z0-9\-]{1,10})\)", text or ""):
        out[m.group(2).strip().upper()] = "concept"
    return out


def lookup_stem_symbol(token: str) -> dict[str, Any] | None:
    """Look up a constant, material, or concept symbol in the offline STEM lexicon."""
    key = (token or "").strip().lower()
    if not key:
        return None
    for lexicon in (CONSTANT_LEXICON, CONCEPT_LEXICON, EQUATION_LEXICON, MATERIAL_LEXICON, SYSTEM_LEXICON):
        if key in lexicon:
            return dict(lexicon[key])
        for info in lexicon.values():
            if key == str(info.get("symbol", "")).lower() or key in [a.lower() for a in info.get("aliases", ())]:
                return dict(info)
    return None


_LEGACY_FAMILIES = {
    "RAS": ("HRAS", "KRAS", "NRAS"),
    "PI3K": ("PIK3CA", "PIK3CB"),
    "AKT": ("AKT1", "AKT2", "AKT3"),
    "RAF": ("ARAF", "BRAF", "CRAF"),
    "MEK": ("MAP2K1", "MAP2K2"),
    "ERK": ("MAPK1", "MAPK3"),
}

_LEGACY_SYMBOLS = {s: (s, "symbol") for fam in _LEGACY_FAMILIES.values() for s in fam}
_LEGACY_SYMBOLS.update({"EGFR": ("EGFR", "symbol"), "BRAF": ("BRAF", "symbol"), "TP53": ("TP53", "symbol")})


def lookup_symbol(token: str) -> tuple[str, str] | None:
    """Return ``(canonical_symbol, matched_on)`` if ``token`` matches a known legacy symbol, else None."""
    return _LEGACY_SYMBOLS.get((token or "").upper().strip())


def family_members(prefix: str) -> tuple[str, ...] | None:
    """Legacy family-ambiguity helper retained for backward compatibility."""
    return _LEGACY_FAMILIES.get((prefix or "").upper().strip())


def is_english_word_symbol(token: str) -> bool:
    return (token or "").upper() in ENGLISH_WORD_SYMBOLS


def is_gene_mention(text: str, start: int = 0, end: int = 0) -> bool:
    """Legacy predicate retained for backward compatibility."""
    token = text[start:end] if (end > start) else text
    return bool(family_members(token) or lookup_symbol(token))


def find_offline_diseases(text: str) -> list[tuple[str, str, tuple[int, int]]]:
    """Always empty, whatever ``text`` says: there is no disease lexicon in Tribos. A documented no-op kept for the
    remaining query_planner import (see DISEASE_HEAD_WORDS)."""
    del text
    return []


def coordinated_disease_terms(text: str) -> list[tuple[str, str, tuple[int, int]]]:
    """Always empty, whatever ``text`` says (no disease lexicon). A documented no-op kept for the remaining
    query_planner import (see DISEASE_HEAD_WORDS)."""
    del text
    return []

