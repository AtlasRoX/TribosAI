# Tribos Scientific Capability Matrix

*Last updated: 28 October 2026*

This matrix defines the supported mathematical, numerical simulation, and engineering calculation capabilities of Tribos, their underlying engines, boundaries, and validation criteria.

---

## 1. Supported Workloads & Numerical Engines

| Domain | Method / Operation | Engine / Package | Supported Input Limits | Validation & Oracle |
| :--- | :--- | :--- | :--- | :--- |
| **Circuit Dynamics** | Ideal RC Charging Step Response | `tribos.engcalc.electrical` | $R > 0$, $C > 0$, $V_s \in \mathbb{R}$, $t \ge 0$. | Closed-form analytic solution $v_C(t) = V_s(1 - e^{-t/\tau})$, KVL balance residual $< 10^{-12}$. |
| **Structural Mechanics** | Rectangular Cantilever Tip Load | `tribos.engcalc.structural` | Linear elastic Euler-Bernoulli regime; $L, b, h, E > 0$, $P \in \mathbb{R}$. | Exact second moment $I = bh^3/12$, max deflection $\delta = PL^3/(3EI)$, moment $M = PL$, stress $\sigma = Mc/I$. |
| **ODE Simulation** | Fixed-Step Runge-Kutta 4 (RK4) | `tribos.dynamis.engine` | Stated scalar or system ODEs; fixed step $h > 0$, explicit steps $N \le 10^5$. | Grid step strictly verified ($N+1$ points matching $t_{\text{span}}$); underdamped harmonic oscillator verified against closed-form within $10^{-4}$. |
| **PDE Diffusion** | 1D Heat Equation (FTCS) | `tribos.dynamis.pde` | 1D bounded domain $[0, L]$, Dirichlet boundaries, diffusion $\alpha > 0$. Stability parameter $r = \frac{\alpha \Delta t}{\Delta x^2} \le 0.5$. | Stability gate enforces $r \le 0.5$ (unstable runs refused); boundary temperatures strictly checked at every time step and final field. |
| **Stochastic Integration** | Crude 1D Monte Carlo | `tribos.dynamis.monte_carlo` | Integrable 1D expressions; $N \le 10^7$ uniform samples. PRNG via NumPy PCG64. | Reproducible seed enforcement; sample variance $s^2 \ge 0$, non-negative standard error $SE = (b-a)s/\sqrt{N}$; reference error tracking. |
| **Exact Mathematics** | Symbolic Algebra, Calculus, Proofs | SymPy / `tribos.axiom` | Safe math strings parsed via `parse_math` / `safe_parse_expr`; domain restrictions $n \ge n_0$, modular congruences $n \equiv a \pmod m$. | Exact rational / integer arithmetic; domain scoping isolation (out-of-domain inputs marked undecided, never contradicted). |

---

## 2. Explicit Unsupported Boundaries & Limitations

Tribos honestly reports limitations and refuses to substitute toy approximations without notice:

1. **Arbitrary 3D CFD & Continuum Fluid Flow**:
   - Tribos does *not* include an arbitrary 3D Navier-Stokes Navier solver or fluid-structure grid generator.
   - Flow computations are limited to closed-form dimensionless numbers (e.g. Reynolds number) and explicit 1D analytical relations.
2. **Arbitrary 3D Finite Element Analysis (FEA)**:
   - Complex 3D CAD stress/strain meshes are not solved natively.
   - Structural analyses are limited to verified 1D beam, shaft, bolt, and thin-walled pressure vessel engineering formulations.
3. **Stiff High-Order Stated ODE Systems without Stability Tuning**:
   - Fixed-step RK4 will diverge on stiff ODE systems (e.g. Robertson kinetics); adaptive stiff solvers (e.g. Radau/BDF) must be explicitly requested.
4. **Universal Automated Theorem Proving**:
   - Open unsolved conjectures (e.g. Erdős–Straus, Riemann Hypothesis) cannot be proved universally; Tribos verifies stated instances, parametric families, and congruence classes without asserting global resolution.

---

## 3. Strict Contract Validation Invariants (`_contract_checks`)

Every executed simulation artifact returned to the user or orchestrator must pass deterministic contract checks:
- **ODE Reports**: Must include complete monotonic time grid array $t$, state trajectories matching grid length $N+1$, endpoint matching $t_{\text{span}}$, and initial state matching within floating-point tolerance.
- **Monte Carlo Reports**: Integrand expression equivalence verified via SymPy `safe_parse_expr()`, integration bounds matched, $SE \ge 0.0$, finite estimate, and valid sample variance.
- **Heat FTCS Reports**: Diffusivity, $\Delta x$, $\Delta t$, stability ratio $r \le 0.5$, grid points, and Dirichlet boundary constraints strictly checked at initial, intermediate, and final snapshots.
- **Engineering Calculators**: Input parameters match within tolerance, calculator ID matches, and output fields are non-empty and finite.
