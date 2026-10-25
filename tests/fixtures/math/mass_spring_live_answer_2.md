## Executive Summary

The system is a linear, viscously damped, harmonically forced mass–spring oscillator with $m = 2$ kg, $c = 3$ N·s/m, $k = 50$ N/m, driven by $F_0 = 10$ N at $\omega = 4$ rad/s, released from $x(0) = 0.1$ m with zero initial velocity. The verified closed-form solution combines an exponentially decaying underdamped transient ($\sigma = 0.75$ s⁻¹, $\omega_d = 4.94343$ rad/s) with a steady-state harmonic response at the forcing frequency ($X = 0.46225$ m, phase lag $\phi = 0.588003$ rad $= 33.690^\circ$). Independent fourth-order Runge–Kutta integration over 0–20 s agrees with the analytical solution to a finest-step maximum displacement error of $2.167\times10^{-7}$ m (observed order $\approx 4.00$), with zero symbolic residual and an energy-balance residual of $1.197\times10^{-6}$ J. Confidence: high — the closed form satisfies the ODE and initial conditions exactly, and the numerical convergence is fourth-order as expected for RK4.

## 1. Analytical solution

### Governing equation

Established background: the forced damped mass–spring oscillator obeys Newton's second law with a linear viscous damper and a harmonic external force,

$$m\ddot{x} + c\dot{x} + kx = F_0\cos(\omega t).$$

Substituting the given values and dividing by $m = 2$ kg,

$$2\ddot{x} + 3\dot{x} + 50x = 10\cos(4t)
\quad\Longrightarrow\quad
\ddot{x} + \frac{3}{2}\dot{x} + 25x = 5\cos(4t).$$

### Step 1 — Transient (homogeneous) part

The homogeneous equation $\ddot{x} + \frac{3}{2}\dot{x} + 25x = 0$ has characteristic equation

$$r^2 + \frac{3}{2}r + 25 = 0,$$

with roots

$$r = -\frac{3}{4} \pm i\,\frac{\sqrt{391}}{4}.$$

Hence the transient is an underdamped decaying oscillation,

$$x_{\rm tr}(t) = e^{-3t/4}\Bigl[A\cos\!\Bigl(\tfrac{\sqrt{391}}{4}t\Bigr) + B\sin\!\Bigl(\tfrac{\sqrt{391}}{4}t\Bigr)\Bigr].$$

### Step 2 — Steady-state (particular) part

Seek a response at the forcing frequency,

$$x_{\rm ss}(t) = C\cos(4t) + D\sin(4t),$$

with

$$\dot{x}_{\rm ss} = -4C\sin(4t) + 4D\cos(4t),\qquad
\ddot{x}_{\rm ss} = -16C\cos(4t) - 16D\sin(4t).$$

Substitution into the ODE and collection of the $\cos(4t)$ and $\sin(4t)$ terms gives

$$\begin{aligned}
18C + 12D &= 10,\\
-12C + 18D &= 0,
\end{aligned}
\qquad\Longrightarrow\qquad
C = \frac{5}{13},\quad D = \frac{10}{39}.$$

Thus

$$x_{\rm ss}(t) = \frac{5}{13}\cos(4t) + \frac{10}{39}\sin(4t)
= X\cos(4t - \phi),$$

with steady-state amplitude $X = 0.46225$ m and phase lag $\phi = 0.588003$ rad ($33.690^\circ$), as computed in Section 2.

### Step 3 — Initial conditions

Applying $x(0) = 0.1$ m and $\dot{x}(0) = 0$,

$$\begin{aligned}
A + \frac{5}{13} &= 0.1,\\
-\frac{3}{4}A + B\,\frac{\sqrt{391}}{4} + 4D &= 0,
\end{aligned}
\qquad\Longrightarrow\qquad
A = -0.284615384615385,\quad
B = -0.250656440625879.$$

### Result (verified closed form)

$$x(t) = \Bigl(-0.250656440625879\,\sin\!\bigl(\tfrac{\sqrt{391}}{4}t\bigr) - 0.284615384615385\,\cos\!\bigl(\tfrac{\sqrt{391}}{4}t\bigr)\Bigr)e^{-3t/4} + \frac{10}{39}\sin(4t) + \frac{5}{13}\cos(4t).$$

The first parenthesized term, multiplied by $e^{-3t/4}$, is the transient; the last two terms are the steady-state response. This is the answer produced by the verified mathematics agent (SymPy/mpmath; checks passed: ODE and initial conditions match, `checkodesol` residual zero, initial/boundary conditions hold).

## 2. Characteristic parameters

| Quantity | Formula | Result |
|---|---|---|
| Natural frequency | $\omega_n = \sqrt{k/m}$ | 5 rad/s |
| Damping ratio | $\zeta = c / (2\sqrt{mk})$ | 0.15 |
| Regime | $\zeta < 1$ underdamped | underdamped |
| Damped natural frequency | $\omega_d = \omega_n\sqrt{1-\zeta^2}$ | 4.94343 rad/s |
| Decay rate | $\sigma = c/(2m)$ | 0.75 s⁻¹ |
| Time constant | $\tau = 2m/c$ | 1.33333 s |
| Forcing amplitude | $F_0$ | 10 N |
| Forcing frequency | $\omega$ | 4 rad/s |
| Frequency ratio | $r = \omega/\omega_n$ | 0.8 |
| Static deflection | $F_0/k$ | 0.2 m |
| Steady-state amplitude | $X = F_0 / \sqrt{(k - m\omega^2)^2 + (c\omega)^2}$ | 0.46225 m |
| Dynamic amplification | $X / (F_0/k)$ | 2.31125 |
| Phase lag | $\phi = \operatorname{atan2}(c\omega,\ k - m\omega^2)$ | 0.588003 rad (33.690°) |
| Mean steady power | $P = c\omega^2 X^2 / 2$ | 5.12821 W |

All values are stated exactly as computed; the regime is underdamped because $\zeta = 0.15 < 1$.

---

## 3. Numerical simulation and independent comparison

### Method

The second-order ODE was rewritten as a first-order system in $(x, v = \dot{x})$ and integrated over 0–20 s with the classical fourth-order Runge–Kutta method at fixed step, using the analytical solution above as the reference. The RK4 verification in Section 3 shows that the finest step, $h = 0.0125$ s (1600 steps), gives a maximum displacement error of $2.167\times10^{-7}$ m, an observed order of convergence of approximately 4.00, and a symbolic residual of 0.

### Numerical verification card

Convergence study:

| $h$ (s) | steps | max $\lvert x - x_{\rm exact}\rvert$ (m) | max $\lvert v - v_{\rm exact}\rvert$ (m/s) | observed order |
|---|---|---|---|---|
| 0.1 | 200 | $9.069\times10^{-4}$ | $4.5268\times10^{-3}$ | — |
| 0.05 | 400 | $5.600\times10^{-5}$ | $2.760\times10^{-4}$ | 4.018 |
| 0.025 | 800 | $3.479\times10^{-6}$ | $1.704\times10^{-5}$ | 4.009 |
| 0.0125 | 1600 | $2.167\times10^{-7}$ | $1.060\times10^{-6}$ | 4.005 |

Selected sample-point comparison:

| $t$ (s) | analytical $x$ (m) | numerical $x$ (m) | abs error (m) |
|---|---|---|---|
| 0 | 0.1 | 0.1 | $3.608\times10^{-16}$ |
| 1 | -0.360984 | -0.360984 | $5.647\times10^{-9}$ |
| 2 | 0.2795 | 0.2795 | $1.791\times10^{-7}$ |
| 5 | 0.387299 | 0.3873 | $1.564\times10^{-7}$ |
| 10 | -0.0654637 | -0.0654636 | $2.649\times10^{-8}$ |
| 20 | -0.2973 | -0.2973 | $1.270\times10^{-7}$ |

Residual check: the symbolic residual of the closed-form solution against the ODE is 0, and the maximum absolute residual over the integration window is 0. Initial conditions are satisfied: $x(0) = 0.1$ m (analytical 0.1) and $\dot{x}(0) = 0$ (analytical $6.661\times10^{-16}$, i.e. zero to machine precision). Units are consistent throughout: displacement in m, velocity in m/s, time in s.

---

## 4. Energy balance

### Balance equation

With mechanical energy $E = \tfrac12 m\dot{x}^2 + \tfrac12 k x^2$, multiplying the equation of motion by $\dot{x}$ gives

$$\frac{\mathrm d}{\mathrm dt}\Bigl[\tfrac12 m\dot{x}^2 + \tfrac12 k x^2\Bigr] = F_0\cos(\omega t)\,\dot{x} - c\,\dot{x}^2.$$

The first term on the right is the power injected by the external force and the second is the power dissipated by the damper. Integrated over $0 \le t \le T = 20$ s,

$$E(T) - E(0) = W_{\rm in} - W_{\rm d}.$$

### Computed balance

| Quantity | Value |
|---|---|
| $E(0)$ | 0.250000 J |
| $E(20)$ | 4.214286 J |
| $W_{\rm in}$ | 104.174612 J |
| $W_{\rm d}$ | 100.210327 J |
| Residual $E(20) - E(0) - (W_{\rm in} - W_{\rm d})$ | $1.197\times10^{-6}$ J |

The residual of $1.197\times10^{-6}$ J is small relative to the energy terms, consistent with numerical quadrature/integration error, and indicates that the work done by the forcing is partitioned between the change in stored mechanical energy and the energy dissipated by damping.

---

## 5. Physical interpretation

The damping ratio $\zeta = 0.15$ places the system firmly in the underdamped regime, so the homogeneous transient decays as $e^{-0.75t}$ with time constant $\tau = 1.33333$ s and oscillates at $\omega_d = 4.94343$ rad/s; after several time constants the motion is dominated by the steady-state response. The forcing frequency $\omega = 4$ rad/s lies below the natural frequency $\omega_n = 5$ rad/s ($r = 0.8$), and the dynamic amplification is 2.31125, so the steady-state amplitude $X = 0.46225$ m exceeds the static deflection $F_0/k = 0.2$ m. The displacement lags the applied force by $\phi = 0.588003$ rad ($33.690^\circ$). In steady state the damper dissipates mean power $P = 5.12821$ W, which is balanced on average by the power injected by the harmonic force; without the external forcing the transient would decay to zero and the oscillator would rest at equilibrium. These qualitative statements follow from the computed parameters; the damped-oscillator framework and its asymptotic approach to equilibrium are consistent with the peer-reviewed literature on damped harmonic vibration [Lelas et al., 2023](https://doi.org/10.1119/5.0112573) and on forced/damped vibration of spring–mass oscillators [Zhang et al., 2025](https://doi.org/10.1590/s1806-11173742058), while the Runge–Kutta numerical approach follows established simulation practice for damped oscillators [Aluri et al., 2023](https://doi.org/10.21275/sr23706201903). The complex-mapping treatment of underdamped oscillations is presented in a preprint [Sharma et al., 2026](https://arxiv.org/abs/2605.31456). Standard textbook presentations of the mass–spring–damper equation and damped oscillations are available from [UT Austin](https://web.ma.utexas.edu/users/jmeth/DEFall19/Oscillators.html), [Physics LibreTexts/OpenStax](https://phys.libretexts.org/Bookshelves/University_Physics/University_Physics_(OpenStax)/Book%3A_University_Physics_I_-_Mechanics_Sound_Oscillations_and_Waves_(OpenStax)/15%3A_Oscillations/15.06%3A_Damped_Oscillations), and [MathWorks](https://www.mathworks.com/help/symbolic/physics-damped-harmonic-oscillator.html).

---

## 6. Ranked hypotheses (in-silico, untested)

All four ranked hypotheses are in-silico model predictions and are untested: no simulation was run for them (experiments_run = 0), so no baseline or perturbed endpoints and no relative response/effect size are available.

- **H1** (rank 1): reducing the damping coefficient $c$ by a factor of 0.1 is predicted to increase the steady-state displacement amplitude — untested.
- **H2** (rank 2): elevating the forcing amplitude $F_0$ by a factor of 10 is predicted to increase the steady-state displacement amplitude — untested.
- **H3** (rank 3): doubling the stiffness $k$ is predicted to decrease the steady-state displacement amplitude — untested.
- **H4** (rank 4): halving the mass $m$ is predicted to increase the steady-state displacement amplitude — untested.

---

## 7. Reproducibility

A standalone NumPy script implementing the RK4 integration, the analytical reference solution, the convergence study, the sample-point comparison, and the energy-balance check was executed in the sandbox and reproduced the reported numbers (finest-step max error $2.167\times10^{-7}$ m, observed order $\approx 4.00$, energy residual $1.197\times10^{-6}$ J). The script is attached to this answer as a download and is not pasted here, per instructions.

---

## Evidence limitations

The computation assumes the ideal linear viscous damping model with constant, exactly known $m$, $c$, $k$, $F_0$, and $\omega$ (massless spring, no parameter uncertainty). No empirical parameter values were provided, so none are estimated from tables. The cited literature provides context for the damped/forced oscillator model and numerical solution methods but is not required for the numerical result; the preprint [Sharma et al., 2026](https://arxiv.org/abs/2605.31456) is explicitly a preprint. The physical interpretation in Section 5 is a qualitative inference from the computed parameters, not an independent measurement.

---

## Evidence classification

| Category | What is established |
|---|---|
| Analytically derived | Closed-form $x(t)$ with transient and steady-state components; characteristic parameters $\omega_n$, $\zeta$, $\omega_d$, $\sigma$, $\tau$, $X$, $\phi$, $P$; exact satisfaction of the ODE (residual 0) and initial conditions. |
| Numerically computed | RK4 time course over 0–20 s; convergence table; sample-point comparisons; energy-balance terms $E(0)$, $E(20)$, $W_{\rm in}$, $W_{\rm d}$ and residual. |
| Supported by references | Standard linear viscous forced damped oscillator model (textbook); peer-reviewed journal articles on damped/forced oscillator vibration and equilibrium approach; numerical simulation of damped oscillators with Runge–Kutta; preprint on underdamped oscillator complex mapping. |
| Not independently verified | Ranked hypotheses H1–H4 (untested in-silico predictions, no endpoints); qualitative physical interpretation statements. |