## Executive Summary

This report investigates the forced damped mass–spring system $m\ddot{x} + c\dot{x} + kx = F_0\cos(\omega t)$ with $m = 2$ kg, $c = 3$ N·s/m, $k = 50$ N/m, $F_0 = 10$ N, $\omega = 4$ rad/s, $x(0) = 0.1$ m, and $\dot{x}(0) = 0$. A closed-form solution was derived separating an exponentially decaying underdamped transient (decay rate $0.75$ s$^{-1}$, damped frequency $4.94343$ rad/s) from a steady-state harmonic response of amplitude $0.46225$ m lagging the force by $\phi = 0.588003$ rad ($33.690^\circ$). Fourth-order Runge–Kutta integration over 0–20 s reproduces the analytical solution with a finest-step maximum displacement error of $2.167\times10^{-7}$ m and observed convergence order $\approx 4.00$; the energy balance closes with a residual of $1.198\times10^{-6}$ J. Confidence: high — the closed form satisfies the ODE and initial conditions exactly under symbolic verification, and the numerical convergence is consistent with fourth-order accuracy.

## 1. Analytical solution

### Step 1 — Governing equation

The equation of motion, with the given values, is

$$2\ddot{x} + 3\dot{x} + 50x = 10\cos(4t), \qquad x(0) = 0.1,\ \dot{x}(0) = 0$$

Dividing by $m = 2$ kg:

$$\ddot{x} + \frac{3}{2}\dot{x} + 25x = 5\cos(4t)$$

### Step 2 — Transient (homogeneous) part

The characteristic equation is

$$r^2 + \frac{3}{2}r + 25 = 0$$

with roots

$$r = -\frac{3}{4} \pm i\,\frac{\sqrt{391}}{4}$$

so the transient solution is

$$x_h(t) = e^{-3t/4}\left[A\cos\left(\frac{\sqrt{391}}{4}t\right) + B\sin\left(\frac{\sqrt{391}}{4}t\right)\right]$$

### Step 3 — Steady-state (particular) part

Seeking a response at the forcing frequency,

$$x_p(t) = C\cos(4t) + D\sin(4t)$$

and substituting into the ODE gives the linear system

$$\begin{aligned}
18C + 12D &= 10\\
-12C + 18D &= 0
\end{aligned}$$

whose solution is

$$C = \frac{5}{13}, \qquad D = \frac{10}{39}$$

Hence

$$x_p(t) = \frac{5}{13}\cos(4t) + \frac{10}{39}\sin(4t) = X\cos(4t - \phi)$$

### Step 4 — Initial conditions

From $x(0) = 0.1$ m:

$$A + \frac{5}{13} = \frac{1}{10} \implies A = -\frac{37}{130} = -0.284615384615385$$

From $\dot{x}(0) = 0$:

$$-\frac{3}{4}A + \frac{\sqrt{391}}{4}B + \frac{40}{39} = 0 \implies B = -0.250656440625879$$

### Final result

$$\begin{aligned}
x(t) = {}& \Big(-0.250656440625879\sin\big(\tfrac{\sqrt{391}}{4}t\big) \\
&\quad - 0.284615384615385\cos\big(\tfrac{\sqrt{391}}{4}t\big)\Big)e^{-3t/4} \\
&\quad + \frac{10}{39}\sin(4t) + \frac{5}{13}\cos(4t)
\end{aligned}$$

The first parenthesized term is the transient, decaying as $e^{-3t/4}$; the last two terms are the steady-state response at the forcing frequency.

## 2. Characteristic parameters

| Quantity | Formula | Result |
|---|---|---|
| Natural frequency | $\omega_n = \sqrt{k/m}$ | $5$ rad/s |
| Damping ratio | $\zeta = c / (2\sqrt{mk})$ | $0.15$ |
| Damped natural frequency | $\omega_d = \omega_n\sqrt{1-\zeta^2}$ | $4.94343$ rad/s |
| Decay rate | $\sigma = c/(2m)$ | $0.75$ s$^{-1}$ |
| Time constant | $\tau = 2m/c$ | $1.33333$ s |
| Forcing frequency | $\omega$ | $4$ rad/s |
| Frequency ratio | $r = \omega/\omega_n$ | $0.8$ |
| Static deflection | $F_0/k$ | $0.2$ m |
| Steady-state amplitude | $X = F_0 / \sqrt{(k - m\omega^2)^2 + (c\omega)^2}$ | $0.46225$ m |
| Dynamic amplification | $X / (F_0/k)$ | $2.31125$ |
| Phase lag | $\phi = \operatorname{atan2}(c\omega, k - m\omega^2)$ | $0.588003$ rad ($33.690^\circ$) |
| Mean steady power | $P = c\omega^2 X^2 / 2$ | $5.12821$ W |

The steady-state amplitude and phase follow from $X = \sqrt{C^2 + D^2} = 0.46225$ m and $\phi = \operatorname{atan2}(D, C) = 0.588003$ rad.

## 3. Numerical simulation and independent comparison

The first-order system $\dot{x} = v$, $\dot{v} = (F_0\cos(\omega t) - cv - kx)/m$ was integrated with the classical fourth-order Runge–Kutta method with fixed step over $t \in [0, 20]$ s. The RK4 verification in Section 3 shows that the symbolic solution has zero residual, both initial conditions hold ($x(0) = 0.1$ m; $\dot{x}(0) = 6.661\times10^{-16}$ m/s $\approx 0$), and the finest step $h = 0.0125$ s (1600 steps) gives a maximum absolute displacement error of $2.167\times10^{-7}$ m with observed order $4.005$. The full convergence, sample-point, and energy tables are in the numerical verification card below.

### Numerical verification card

**Convergence (RK4 vs. analytical solution)**

| Step $h$ (s) | Steps | $\max|x - x_{\text{exact}}|$ (m) | $\max|v - v_{\text{exact}}|$ (m/s) | Observed order |
|---|---|---|---|---|
| 0.1 | 200 | $9.069\times10^{-4}$ | $4.5268\times10^{-3}$ | — |
| 0.05 | 400 | $5.600\times10^{-5}$ | $2.760\times10^{-4}$ | 4.018 |
| 0.025 | 800 | $3.479\times10^{-6}$ | $1.704\times10^{-5}$ | 4.009 |
| 0.0125 | 1600 | $2.167\times10^{-7}$ | $1.060\times10^{-6}$ | 4.005 |

**Sample-point comparison**

| $t$ (s) | Analytical $x$ (m) | Numerical $x$ (m) | Abs. error (m) |
|---|---|---|---|
| 0 | 0.1 | 0.1 | $3.608\times10^{-16}$ |
| 1 | -0.360984 | -0.360984 | $5.647\times10^{-9}$ |
| 2 | 0.2795 | 0.2795 | $1.791\times10^{-7}$ |
| 5 | 0.387299 | 0.3873 | $1.564\times10^{-7}$ |
| 10 | -0.0654637 | -0.0654636 | $2.649\times10^{-8}$ |
| 20 | -0.2973 | -0.2973 | $1.270\times10^{-7}$ |

**Energy balance**

| Quantity | Value |
|---|---|
| $E(0) = \tfrac12 m\dot{x}(0)^2 + \tfrac12 k x(0)^2$ | 0.25 J |
| $E(20)$ | 4.21429 J |
| Work input $W_{\text{in}} = \int_0^{20} F_0\cos(4t)\,\dot{x}\,dt$ | 104.175 J |
| Dissipated work $W_{\text{d}} = \int_0^{20} c\dot{x}^2\,dt$ | 100.21 J |
| Residual $E(20) - E(0) - (W_{\text{in}} - W_{\text{d}})$ | $1.198\times10^{-6}$ J |

The closed-form expression was independently verified symbolically: the ODE residual is zero and both initial conditions hold. The reported benchmark precision (98% over $n=43$ held-out problems) applies to the mathematics agent's final answer expression only, not to this whole answer or to values derived here.

## 4. Energy balance

The mechanical energy is

$$E(t) = \frac{1}{2}m\dot{x}^2 + \frac{1}{2}kx^2$$

Multiplying the equation of motion by $\dot{x}$ gives the instantaneous balance

$$\frac{dE}{dt} = F_0\cos(\omega t)\dot{x} - c\dot{x}^2$$

where $F_0\cos(\omega t)\dot{x}$ is the power delivered by the external force and $-c\dot{x}^2$ is the power dissipated by the damper. Integrating over 0–20 s:

$$E(20) - E(0) = W_{\text{in}} - W_{\text{d}}$$

with $E(0) = 0.25$ J, $E(20) = 4.21429$ J, $W_{\text{in}} = 104.175$ J, and $W_{\text{d}} = 100.21$ J, leaving a balance residual of $1.198\times10^{-6}$ J, i.e. the energy equation closes to within numerical integration error. In steady state the mean input power equals the mean dissipated power, $P = c\omega^2 X^2/2 = 5.12821$ W.

## 5. Physical interpretation

The damping ratio $\zeta = 0.15 < 1$ places the system in the underdamped regime, so the transient oscillates at $\omega_d = 4.94343$ rad/s while its envelope decays with time constant $\tau = 1.33333$ s; after a few seconds the response is essentially the steady-state harmonic motion. Because the forcing frequency is $80\%$ of the natural frequency ($r = 0.8$), the steady-state amplitude $0.46225$ m is $2.31125$ times the static deflection $F_0/k = 0.2$ m, i.e. the system responds with dynamic amplification near resonance. The phase lag $\phi = 0.588003$ rad ($33.690^\circ$) means the displacement reaches its peak after the applied force, as expected for a damped oscillator driven below resonance. Damping continuously removes energy at rate $c\dot{x}^2$, while the external force injects energy at rate $F_0\cos(4t)\dot{x}$; in the long-time limit the two balance on average, so the oscillation settles to a constant-amplitude steady state rather than growing or decaying indefinitely.

## 6. Reproducibility

A standalone NumPy script implementing the RK4 integration, the analytical solution, the convergence study, the sample-point comparison, and the energy balance is attached to this answer as a download; it is not pasted here. Running it with steps $h = 0.1, 0.05, 0.025, 0.0125$ s reproduces the convergence orders ($4.018, 4.009, 4.005$), the maximum errors, and the energy terms reported above, including $E(0) = 0.250000$ J, $E(20) = 4.214286$ J, $W_{\text{in}} = 104.174612$ J, $W_{\text{d}} = 100.210327$ J, and residual $1.197\times10^{-6}$ J.

### References

- [The Physics of the Damped Harmonic Oscillator — MathWorks](https://www.mathworks.com/help/symbolic/physics-damped-harmonic-oscillator.html): governing equation $m\ddot{x} + c\dot{x} + kx = F(t)$.
- [15.6: Damped Oscillations — Physics LibreTexts (OpenStax)](https://phys.libretexts.org/Bookshelves/University_Physics/University_Physics_(OpenStax)/Book%3A_University_Physics_I_-_Mechanics_Sound_Oscillations_and_Waves_(OpenStax)/15%3A_Oscillations/15.06%3A_Damped_Oscillations): damped-oscillation behavior and amplitude decay.
- [Lelas et al., 2023, DOI:10.1119/5.0112573](https://doi.org/10.1119/5.0112573): damped harmonic oscillator energy approaches equilibrium asymptotically (peer-reviewed journal article).
- [Zhang et al., 2015, DOI:10.1590/s1806-11173742058](https://doi.org/10.1590/s1806-11173742058): forced oscillator with viscous resistance and applied force (peer-reviewed journal article).

## Evidence classification

| Category | What is established |
|---|---|
| Analytically derived | Closed-form displacement $x(t)$; transient coefficients $A = -0.284615384615385$ and $B = -0.250656440625879$; steady-state coefficients $C = 5/13$ and $D = 10/39$; amplitude $X = 0.46225$ m; phase $\phi = 0.588003$ rad ($33.690^\circ$); symbolic ODE residual zero; initial conditions satisfied exactly |
| Numerically computed | RK4 time course over 0–20 s; convergence orders $4.018, 4.009, 4.005$; sample-point errors; energy terms $E(0) = 0.25$ J, $E(20) = 4.21429$ J, $W_{\text{in}} = 104.175$ J, $W_{\text{d}} = 100.21$ J; balance residual $1.198\times10^{-6}$ J |
| Supported by references | Governing equation form $m\ddot{x} + c\dot{x} + kx = F(t)$ (MathWorks); damped-oscillation amplitude decay (Physics LibreTexts); asymptotic approach of damped-oscillator energy to equilibrium (Lelas et al., 2023); forced oscillator with viscous resistance and applied force (Zhang et al., 2015) |
| Not independently verified | Qualitative interpretation of energy flow and the physical meaning of the phase lag; behavior of the attached NumPy script outside the reported sandbox execution; literature context beyond the retrieved abstracts |