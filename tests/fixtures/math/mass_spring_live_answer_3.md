**Executive Summary.** The system is a linearly damped, harmonically forced mass–spring oscillator with $m = 2\ \mathrm{kg}$, $c = 3\ \mathrm{N\cdot s/m}$, $k = 50\ \mathrm{N/m}$, driven by $F_0 = 10\ \mathrm{N}$ at $\omega = 4\ \mathrm{rad/s}$, released from $x(0) = 0.1\ \mathrm{m}$ with zero initial velocity. The closed-form solution separates into an exponentially decaying underdamped transient and a sustained steady-state oscillation at the forcing frequency. Key results: natural frequency $5\ \mathrm{rad/s}$, damping ratio $0.15$ (underdamped), damped natural frequency $4.94343\ \mathrm{rad/s}$, steady-state amplitude $0.46225\ \mathrm{m}$, phase lag $0.588003\ \mathrm{rad}$ ($33.690^\circ$); RK4 integration over $0$–$20\ \mathrm{s}$ agrees with the analytical solution with a finest-step maximum displacement error of $2.167\mathrm{e}{-}07\ \mathrm{m}$ and observed order $4.005$, and the energy balance closes with a residual of $1.198\mathrm{e}{-}06\ \mathrm{J}$. Confidence: high — the analytic expression passed symbolic ODE and initial-condition checks, and all numerical values are taken directly from the verified computation.

## 1. Analytical solution

**Governing equation** (established background: forced damped mass–spring oscillator, $m\ddot{x} + c\dot{x} + kx = F(t)$ [MATLAB example](https://www.mathworks.com/help/symbolic/physics-damped-harmonic-oscillator.html)):

$$2\frac{\mathrm{d}^2 x}{\mathrm{d}t^2} + 3\frac{\mathrm{d}x}{\mathrm{d}t} + 50x = 10\cos(4t)$$

Dividing by $m = 2$:

$$\frac{\mathrm{d}^2 x}{\mathrm{d}t^2} + \frac{3}{2}\frac{\mathrm{d}x}{\mathrm{d}t} + 25x = 5\cos(4t)$$

### Step 1 — Transient (homogeneous) part

The characteristic equation is

$$r^2 + \frac{3}{2}r + 25 = 0$$

with roots

$$r = -\frac{3}{4} \pm i\,\frac{\sqrt{391}}{4}$$

so the transient is

$$x_h(t) = e^{-3t/4}\left[A\cos\left(\frac{\sqrt{391}}{4}t\right) + B\sin\left(\frac{\sqrt{391}}{4}t\right)\right]$$

### Step 2 — Steady-state (particular) part

Seek $x_p(t) = C\cos(4t) + D\sin(4t)$. Substitution into the ODE gives

$$\begin{aligned} 18C + 12D &= 10 \\ -12C + 18D &= 0 \end{aligned}$$

hence

$$C = \frac{5}{13}, \qquad D = \frac{10}{39}$$

and

$$x_p(t) = \frac{5}{13}\cos(4t) + \frac{10}{39}\sin(4t) = X\cos(4t - \phi)$$

with

$$X = \sqrt{C^2 + D^2} = 0.46225\ \mathrm{m}, \qquad \phi = \operatorname{atan2}(D, C) = 0.588003\ \mathrm{rad} = 33.690^\circ$$

### Step 3 — Initial conditions

From $x(0) = 0.1\ \mathrm{m}$:

$$A + \frac{5}{13} = 0.1 \quad\Rightarrow\quad A = -0.284615384615385$$

From $x'(0) = 0$:

$$-\frac{3}{4}A + \frac{\sqrt{391}}{4}B + 4D = 0 \quad\Rightarrow\quad B = -0.250656440625879$$

### Final solution

$$x(t) = \left(-0.250656440625879\sin\left(\frac{\sqrt{391}}{4}t\right) - 0.284615384615385\cos\left(\frac{\sqrt{391}}{4}t\right)\right)e^{-3t/4} + \frac{10}{39}\sin(4t) + \frac{5}{13}\cos(4t)$$

The first term is the transient (decaying with rate $0.75\ \mathrm{1/s}$); the last two terms are the steady-state response at the forcing frequency. The expression satisfies the ODE and the initial conditions ($x(0) = 0.1\ \mathrm{m}$ exactly; $x'(0) = 6.661\mathrm{e}{-}16 \approx 0$), as confirmed by symbolic checks (checkodesol passed; initial/boundary conditions hold). The mathematics agent's benchmark precision is $0.9778$ over $n=43$ held-out problems, and applies to its final answer expression only, not to this written explanation or to values derived here.

## 2. Characteristic parameters

| Quantity | Formula | Result | Unit |
|---|---|---|---|
| Natural frequency | $\omega_n = \sqrt{k/m}$ | 5 | rad/s |
| Damping ratio | $\zeta = c / (2\sqrt{mk})$ | 0.15 | — |
| Regime | $\zeta < 1$ | underdamped | — |
| Damped natural frequency | $\omega_d = \omega_n\sqrt{1-\zeta^2}$ | 4.94343 | rad/s |
| Decay rate | $\sigma = c/(2m)$ | 0.75 | 1/s |
| Time constant | $\tau = 2m/c$ | 1.33333 | s |
| Forcing amplitude | $F_0$ | 10 | N |
| Forcing frequency | $\omega$ | 4 | rad/s |
| Frequency ratio | $r = \omega/\omega_n$ | 0.8 | — |
| Static deflection | $F_0/k$ | 0.2 | m |
| Steady-state amplitude | $X = F_0 / \sqrt{(k - m\omega^2)^2 + (c\omega)^2}$ | 0.46225 | m |
| Dynamic amplification | $X / (F_0/k)$ | 2.31125 | — |
| Phase lag | $\phi = \operatorname{atan2}(c\omega, k - m\omega^2)$ | 0.588003 | rad ($33.690^\circ$) |
| Mean steady power | $P = c\omega^2 X^2 / 2$ | 5.12821 | W |

## 3. Numerical simulation and independent comparison

**Method.** The system was integrated as a first-order system in $(x, \dot{x})$ with the classical fourth-order Runge–Kutta method, fixed step, over $t \in [0, 20]\ \mathrm{s}$, against the analytical solution above.

The RK4 verification over $0$–$20\ \mathrm{s}$ shows the finest step ($h = 0.0125\ \mathrm{s}$, 1600 steps) gives a maximum absolute displacement error of $2.167\mathrm{e}{-}07\ \mathrm{m}$ (velocity error $1.060\mathrm{e}{-}06\ \mathrm{m/s}$) with an observed convergence order of $4.005$; the symbolic residual of the analytical solution is zero, and the initial conditions are satisfied ($x(0) = 0.1\ \mathrm{m}$ exactly; $x'(0) \approx 0$). The full convergence, time-sample, and energy tables are in the Numerical verification card below; they are not repeated here.

### Numerical verification card

**Convergence (RK4 vs. analytical solution)**

| $h$ (s) | Steps | $\max |x - x_{\text{exact}}|$ (m) | $\max |\dot{x} - \dot{x}_{\text{exact}}|$ (m/s) | Observed order |
|---|---|---|---|---|
| 0.1 | 200 | 9.069e-04 | 0.0045268 | nan |
| 0.05 | 400 | 5.600e-05 | 2.760e-04 | 4.018 |
| 0.025 | 800 | 3.479e-06 | 1.704e-05 | 4.009 |
| 0.0125 | 1600 | 2.167e-07 | 1.060e-06 | 4.005 |

**Selected time samples**

| $t$ (s) | Analytical $x$ (m) | Numerical $x$ (m) | Abs. error (m) |
|---|---|---|---|
| 0 | 0.1 | 0.1 | 3.608e-16 |
| 1 | -0.360984 | -0.360984 | 5.647e-09 |
| 2 | 0.2795 | 0.2795 | 1.791e-07 |
| 5 | 0.387299 | 0.3873 | 1.564e-07 |
| 10 | -0.0654637 | -0.0654636 | 2.649e-08 |
| 20 | -0.2973 | -0.2973 | 1.270e-07 |

**Energy balance**

| Quantity | Value | Unit |
|---|---|---|
| $E(0) = \tfrac12 m\dot{x}(0)^2 + \tfrac12 k x(0)^2$ | 0.25 | J |
| $E(20)$ | 4.21429 | J |
| Work input $W_{\text{in}} = \int_0^{20} F_0\cos(4t)\,\dot{x}\,\mathrm{d}t$ | 104.175 | J |
| Dissipated $W_{\text{d}} = \int_0^{20} c\,\dot{x}^2\,\mathrm{d}t$ | 100.21 | J |
| Balance residual $E(20) - E(0) - (W_{\text{in}} - W_{\text{d}})$ | 1.198e-06 | J |

## 4. Energy balance

The mechanical energy is

$$E(t) = \frac{1}{2}m\dot{x}^2 + \frac{1}{2}kx^2$$

Multiplying the equation of motion by $\dot{x}$ gives the balance law

$$\frac{\mathrm{d}E}{\mathrm{d}t} = F_0\cos(\omega t)\,\dot{x} - c\dot{x}^2$$

i.e. power input from the forcing minus power dissipated by the damper. Integrated over $0$–$20\ \mathrm{s}$:

$$E(20) - E(0) = W_{\text{in}} - W_{\text{d}}$$

with $E(0) = 0.25\ \mathrm{J}$, $E(20) = 4.21429\ \mathrm{J}$, $W_{\text{in}} = 104.175\ \mathrm{J}$, $W_{\text{d}} = 100.21\ \mathrm{J}$, and a balance residual of $1.198\mathrm{e}{-}06\ \mathrm{J}$, confirming closure to numerical precision. In steady state the mean input power equals the mean dissipation, $P = c\omega^2 X^2/2 = 5.12821\ \mathrm{W}$.

## 5. Physical interpretation

The damping ratio $\zeta = 0.15 < 1$ places the system in the underdamped regime, so the transient decays as $e^{-0.75t}$ with time constant $1.33333\ \mathrm{s}$ and oscillates at $4.94343\ \mathrm{rad/s}$, vanishing after a few seconds. The external forcing injects energy at $4\ \mathrm{rad/s}$; since the frequency ratio $r = 0.8$ lies below resonance ($r=1$), the response is amplified relative to the static deflection ($0.2\ \mathrm{m}$) by a dynamic amplification factor of $2.31125$, giving a steady-state amplitude of $0.46225\ \mathrm{m}$. The displacement lags the applied force by $0.588003\ \mathrm{rad}$ ($33.690^\circ$). Damping removes energy continuously at rate $c\dot{x}^2$, while the forcing replenishes it; after the transient dies out, input and dissipation balance in the mean. This is consistent with the standard description of lightly damped oscillations, where amplitude decays each cycle while frequency remains nearly constant [Physics LibreTexts/OpenStax](https://phys.libretexts.org/Bookshelves/University_Physics/University_Physics_(OpenStax)/Book%3A_University_Physics_I_-_Mechanics_Sound_Oscillations_and_Waves_(OpenStax)/15%3A_Oscillations/15.06%3A_Damped_Oscillations), and with experimental findings that damped oscillator energy asymptotically approaches equilibrium, with critical damping the fastest approach among damping cases [Lelas et al., 2023, peer-reviewed journal article, DOI:10.1119/5.0112573](https://doi.org/10.1119/5.0112573). The present model uses a massless spring; heavy-spring extensions are discussed in [Zhang et al., 2015, peer-reviewed journal article, DOI:10.1590/s1806-11173742058](https://doi.org/10.1590/s1806-11173742058) and its arXiv preprint [arXiv:1505.03815](https://arxiv.org/abs/1505.03815) (preprint).

## 6. Reproducibility

A standalone NumPy script reproducing the RK4 integration, the convergence and sample tables, and the energy balance is attached to this answer as a download; it is not pasted here. Per the attached computation, it printed convergence orders $\approx 4$ across the halving sequence and an energy balance residual of $1.197\mathrm{e}{-}06\ \mathrm{J}$.

## Evidence classification

| Category | What is established |
|---|---|
| Analytically derived | Closed-form $x(t)$ with transient and steady-state parts; $\omega_n = 5\ \mathrm{rad/s}$; $\zeta = 0.15$; $\omega_d = 4.94343\ \mathrm{rad/s}$; $\sigma = 0.75\ \mathrm{1/s}$; $\tau = 1.33333\ \mathrm{s}$; $X = 0.46225\ \mathrm{m}$; $\phi = 0.588003\ \mathrm{rad}$ ($33.690^\circ$); dynamic amplification $2.31125$; mean steady power $5.12821\ \mathrm{W}$ — verified by symbolic ODE and initial-condition checks (checkodesol passed; initial/boundary conditions hold). The agent's benchmark precision $0.9778$ ($n=43$) applies to its final answer expression only, not to this written explanation or derived values. |
| Numerically computed | RK4 errors and convergence orders for $h = 0.1$ to $0.0125\ \mathrm{s}$; six time samples; energy terms $E(0)$, $E(20)$, $W_{\text{in}}$, $W_{\text{d}}$, residual $1.198\mathrm{e}{-}06\ \mathrm{J}$. |
| Supported by references | Governing equation $m\ddot{x} + c\dot{x} + kx = F(t)$ [MATLAB example](https://www.mathworks.com/help/symbolic/physics-damped-harmonic-oscillator.html); decaying amplitude in light damping [Physics LibreTexts/OpenStax](https://phys.libretexts.org/Bookshelves/University_Physics/University_Physics_(OpenStax)/Book%3A_University_Physics_I_-_Mechanics_Sound_Oscillations_and_Waves_(OpenStax)/15%3A_Oscillations/15.06%3A_Damped_Oscillations); asymptotic approach to equilibrium and fastest critical damping [Lelas et al., 2023, peer-reviewed journal article, DOI:10.1119/5.0112573](https://doi.org/10.1119/5.0112573); heavy-spring context [Zhang et al., 2015, peer-reviewed journal article, DOI:10.1590/s1806-11173742058](https://doi.org/10.1590/s1806-11173742058) and arXiv preprint [arXiv:1505.03815](https://arxiv.org/abs/1505.03815). |
| Not independently verified | Interpretive statements on the effects of damping and forcing; the claim that the standalone script was executed and its printed reproduction output; literature-based contextual claims not re-derived here. |