## Executive Summary

The system is a forced, damped mass–spring oscillator with $m=2\,\mathrm{kg}$, $c=3\,\mathrm{N\,s/m}$, $k=50\,\mathrm{N/m}$, driven by $F_0\cos(\omega t)$ with $F_0=10\,\mathrm{N}$ and $\omega=4\,\mathrm{rad/s}$, released from $x(0)=0.1\,\mathrm{m}$ at rest. The exact analytical solution is

$$x(t)=\left(-0.250656440625879\sin\!\left(\frac{\sqrt{391}\,t}{4}\right)-0.284615384615385\cos\!\left(\frac{\sqrt{391}\,t}{4}\right)\right)e^{-3t/4}+\frac{10\sin(4t)}{39}+\frac{5\cos(4t)}{13}\quad\mathrm{m}.$$

The system is underdamped with natural frequency $\omega_n=5\,\mathrm{rad/s}$, damping ratio $\zeta=0.15$, damped natural frequency $\omega_d=4.94343\,\mathrm{rad/s}$, steady-state amplitude $X=0.46225\,\mathrm{m}$, and phase lag $\phi=0.588003\,\mathrm{rad}$ ($33.690^\circ$). RK4 simulation over $0$–$20\,\mathrm{s}$ agrees with the analytical solution to a maximum absolute error of $2.167\times10^{-7}\,\mathrm{m}$ at $h=0.0125\,\mathrm{s}$ with observed order $4.005$; the energy-balance residual is $1.197\times10^{-6}\,\mathrm{J}$. Confidence: high — the analytical expression was verified against the ODE and initial conditions, and the numerical results were independently reproduced in the sandbox.

---

## 1. Analytical solution

### 1.1 Governing equation and established background

The forced damped mass–spring system follows from Newton's second law:

$$m\frac{\mathrm{d}^2x}{\mathrm{d}t^2}+c\frac{\mathrm{d}x}{\mathrm{d}t}+kx=F_0\cos(\omega t),$$

with $m=2\,\mathrm{kg}$, $c=3\,\mathrm{N\,s/m}$, $k=50\,\mathrm{N/m}$, $F_0=10\,\mathrm{N}$, $\omega=4\,\mathrm{rad/s}$, $x(0)=0.1\,\mathrm{m}$, and $x'(0)=0$. This is the standard linear second-order ODE for a damped harmonic oscillator with harmonic forcing (established background; see, e.g., the mass–spring–damper equation summarized in the MATLAB documentation result and the LibreTexts/OpenStax damped-oscillations passage in the evidence).

### 1.2 Transient (homogeneous) part

The homogeneous equation is

$$2\ddot{x}+3\dot{x}+50x=0.$$

The characteristic equation is

$$2r^2+3r+50=0,$$

whose roots are

$$r=\frac{-3\pm\sqrt{9-400}}{4}=-\frac{3}{4}\pm i\frac{\sqrt{391}}{4}.$$

Hence the transient solution is

$$x_h(t)=e^{-3t/4}\left[A\cos\!\left(\frac{\sqrt{391}}{4}t\right)+B\sin\!\left(\frac{\sqrt{391}}{4}t\right)\right].$$

### 1.3 Steady-state (particular) part

For harmonic forcing $F_0\cos(\omega t)$, the steady-state response has the form

$$x_p(t)=X\cos(\omega t-\phi),$$

where

$$X=\frac{F_0}{\sqrt{(k-m\omega^2)^2+(c\omega)^2}},\qquad
\phi=\operatorname{atan2}(c\omega,\;k-m\omega^2).$$

Substituting the values:

$$k-m\omega^2=50-2(16)=18\,\mathrm{N/m},\qquad c\omega=3(4)=12\,\mathrm{N\,s/m},$$

$$X=\frac{10}{\sqrt{18^2+12^2}}=\frac{10}{\sqrt{468}}=\frac{5}{3\sqrt{13}}\approx0.46225\,\mathrm{m},$$

$$\phi=\operatorname{atan2}(12,18)=\arctan\!\left(\frac{2}{3}\right)\approx0.588003\,\mathrm{rad}\;(33.690^\circ).$$

Equivalently, in sine–cosine form,

$$x_p(t)=C\cos(4t)+D\sin(4t),$$

with

$$C=X\cos\phi=\frac{5}{13},\qquad D=X\sin\phi=\frac{10}{39}.$$

### 1.4 Initial conditions and final solution

Applying $x(0)=0.1$ and $x'(0)=0$ to $x=x_h+x_p$ fixes

$$A=-0.284615384615385,\qquad B=-0.250656440625879.$$

The complete analytical solution is therefore

$$x(t)=\left(-0.250656440625879\sin\!\left(\frac{\sqrt{391}\,t}{4}\right)-0.284615384615385\cos\!\left(\frac{\sqrt{391}\,t}{4}\right)\right)e^{-3t/4}+\frac{10\sin(4t)}{39}+\frac{5\cos(4t)}{13}\quad\mathrm{m}.$$

This expression was produced by the verified mathematics agent (SymPy/mpmath) and passed the checks: ODE and initial conditions match the problem; the solution satisfies the original ODE (`checkodesol`); initial/boundary conditions hold. The agent's verified answers were correct in 98% of held-out benchmark problems ($n=43$); that figure applies to the agent's final answer expression only, not to this whole answer or to values derived from it.

---

## 2. Characteristic parameters

| Quantity | Formula | Result | Unit |
|---|---|---|---|
| Natural frequency | $\omega_n=\sqrt{k/m}$ | 5 | rad/s |
| Damping ratio | $\zeta=c/(2\sqrt{mk})$ | 0.15 | — |
| Regime | $\zeta<1$ | underdamped | — |
| Damped natural frequency | $\omega_d=\omega_n\sqrt{1-\zeta^2}$ | 4.94343 | rad/s |
| Decay rate | $\sigma=c/(2m)$ | 0.75 | 1/s |
| Time constant | $\tau=1/\sigma=2m/c$ | 1.33333 | s |
| Forcing frequency | $\omega$ | 4 | rad/s |
| Frequency ratio | $r=\omega/\omega_n$ | 0.8 | — |
| Static deflection | $F_0/k$ | 0.2 | m |
| Steady-state amplitude | $X=F_0/\sqrt{(k-m\omega^2)^2+(c\omega)^2}$ | 0.46225 | m |
| Dynamic amplification | $X/(F_0/k)$ | 2.31125 | — |
| Phase lag | $\phi=\operatorname{atan2}(c\omega,\;k-m\omega^2)$ | 0.588003 | rad ($33.690^\circ$) |
| Mean steady power input | $P=c\omega^2X^2/2$ | 5.12821 | W |

All parameter values are taken exactly as computed in the evidence; no number was re-derived in this text.

---

## 3. Numerical simulation and independent comparison

The system was integrated over $0$–$20\,\mathrm{s}$ with the classical fourth-order Runge–Kutta (RK4) method at fixed step sizes $h=0.1,\,0.05,\,0.025,\,0.0125\,\mathrm{s}$, compared against the analytical solution above.

Key results from the independent RK4 verification:

- Finest-step ($h=0.0125\,\mathrm{s}$, 1600 steps) maximum absolute error in displacement: $2.167\times10^{-7}\,\mathrm{m}$; maximum velocity error: $1.060\times10^{-6}\,\mathrm{m/s}$.
- Observed order of convergence across the step-size refinement: $4.005$ (consistent with the theoretical fourth order of RK4).
- Symbolic residual of the analytical solution substituted into the ODE: exactly $0$; maximum absolute residual: $0$.
- Initial conditions: analytical $x(0)=0.1\,\mathrm{m}$ matches the stated value; analytical $x'(0)=6.661\times10^{-16}\approx0\,\mathrm{m/s}$ matches the stated rest condition.

Sample comparisons (analytical vs. numerical at $h=0.0125\,\mathrm{s}$):

| $t$ (s) | Analytical $x$ (m) | Numerical $x$ (m) | Absolute error (m) |
|---|---|---|---|
| 0 | 0.1 | 0.1 | $3.608\times10^{-16}$ |
| 1 | $-0.360984$ | $-0.360984$ | $5.647\times10^{-9}$ |
| 2 | 0.2795 | 0.2795 | $1.791\times10^{-7}$ |
| 5 | 0.387299 | 0.3873 | $1.564\times10^{-7}$ |
| 10 | $-0.0654637$ | $-0.0654636$ | $2.649\times10^{-8}$ |
| 20 | $-0.2973$ | $-0.2973$ | $1.270\times10^{-7}$ |

The full convergence table (all four step sizes with observed orders) and the complete sample table are shown in the Numerical verification card under this answer; they are not repeated here. The RK4 verification in Section 3 confirms fourth-order convergence and sub-micron displacement agreement with the exact solution.

---

## 4. Energy balance

The mechanical energy is

$$E(t)=\frac12 m\dot{x}^2+\frac12 kx^2.$$

Over $0$–$20\,\mathrm{s}$:

- Initial energy: $E(0)=0.250000\,\mathrm{J}$
- Final energy: $E(20)=4.214286\,\mathrm{J}$
- Work done by the external force: $W_{\mathrm{in}}=104.174612\,\mathrm{J}$
- Energy dissipated by damping: $W_{\mathrm{d}}=100.210327\,\mathrm{J}$

The balance equation is

$$E(T)-E(0)=W_{\mathrm{in}}-W_{\mathrm{d}},$$

with computed residual

$$E(T)-E(0)-(W_{\mathrm{in}}-W_{\mathrm{d}})=1.197\times10^{-6}\,\mathrm{J},$$

which is at the level of numerical integration error. The mean steady-state power input is $P=5.12821\,\mathrm{W}$, equal to the mean power dissipated by the damper in steady state.

**Physical interpretation.** Damping removes mechanical energy at rate $c\dot{x}^2$ and causes the transient to decay with time constant $\tau=1.33333\,\mathrm{s}$; after roughly $5\tau\approx6.7\,\mathrm{s}$ the response is dominated by the steady-state oscillation at the forcing frequency $\omega=4\,\mathrm{rad/s}$, not the natural frequency. The external force continuously injects energy; in steady state the average power input exactly balances the average power dissipated by the damper, so the oscillation amplitude settles at the constant value $X=0.46225\,\mathrm{m}$ with a phase lag of $0.588003\,\mathrm{rad}$ ($33.690^\circ$) behind the force. Because the forcing frequency ($4\,\mathrm{rad/s}$) is below the natural frequency ($5\,\mathrm{rad/s}$) but the system is lightly damped ($\zeta=0.15$), the dynamic amplification is $2.31125$ times the static deflection.

## 5. Reproducibility

A standalone NumPy script implementing the RK4 integration, the analytical solution, the error comparison, the convergence study, and the energy balance was executed in the sandbox during this answer and printed the convergence and energy values quoted above. The script is attached to this answer as a download; it is not pasted here.

---

## 6. Evidence classification

| Category | What is established |
|---|---|
| Analytically derived | The closed-form solution $x(t)$ with transient and steady-state parts; characteristic parameters ($\omega_n$, $\zeta$, $\omega_d$, $X$, $\phi$, etc.); ODE residual exactly zero; initial conditions satisfied exactly. Verified by the mathematics agent (SymPy/mpmath; benchmark precision 98% on $n=43$ held-out problems, applying to the agent's final expression only). |
| Numerically computed | RK4 errors, observed orders of convergence, sample-point comparisons, energy-balance terms and residual — all reproduced in the sandbox. |
| Supported by references | The standard mass–spring–damper equation $m\ddot{x}+c\dot{x}+kx=F(t)$ and the damped-oscillator framework are documented in the retrieved web sources (MATLAB example, LibreTexts/OpenStax passage) and the literature list (damped harmonic oscillator chapters and articles). |
| Not independently verified | Physical interpretation statements (energy flow interpretation, settling-time estimate, dominance of steady-state response after $5\tau$) rest on reasoning from the computed parameters rather than on a separate tool computation; no additional experimental or CFD validation was performed. |

---

### Evidence limitations

No empirical material parameters were needed; all values are given in the problem statement. The literature retrieved concerns damped oscillators generally but none reports the specific parameter set used here, so the numerical results stand on the computation alone.