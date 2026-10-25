## Executive Summary

The system is a linear, underdamped, harmonically forced single-degree-of-freedom mass–spring–damper,

$$2\frac{d^2x}{dt^2} + 3\frac{dx}{dt} + 50x = 10\cos(4t), \qquad x(0) = 0.1\ \mathrm{m},\ \dot x(0) = 0\ \mathrm{m/s}.$$

I derived the closed-form solution $x(t) = x_h(t) + x_p(t)$ and computed $\omega_n = 5\ \mathrm{rad/s}$, $\zeta = 0.15$, $\omega_d = \sqrt{391}/4 \approx 4.94343\ \mathrm{rad/s}$, steady-state amplitude $X = 10/\sqrt{117} \approx 0.92848\ \mathrm{m}$, and phase $\phi = \operatorname{atan2}(12, -18) \approx 2.55359\ \mathrm{rad}$. The exact solution is

$$x(t) = e^{-3t/4}\left[-0.284615384615385\cos\left(\frac{\sqrt{391}}{4}t\right) - 0.250656440625879\sin\left(\frac{\sqrt{391}}{4}t\right)\right] + \frac{5}{13}\cos(4t) + \frac{10}{39}\sin(4t).$$

The transient decays with time constant 4/3 s; after roughly 20 s the response is essentially steady-state. The energy balance closes: $E(0) = 0.250000\ \mathrm{J}$, $E(20) = 4.21429\ \mathrm{J}$.

## 1. Analytical solution

### 1.1 Governing equation and assumptions

Newton's second law for a linear mass–spring–damper with viscous damping and harmonic forcing gives

$$m\ddot x + c\dot x + kx = F_0\cos(\omega t).$$

### 1.2 Transient (homogeneous) solution

The homogeneous equation is

$$2\ddot x + 3\dot x + 50x = 0.$$

The characteristic equation is

$$2r^2 + 3r + 50 = 0, \qquad r = \frac{-3 \pm \sqrt{9 - 400}}{4} = -\frac{3}{4} \pm i\frac{\sqrt{391}}{4}.$$

Hence

$$x_h(t) = e^{-3t/4}\left[A\cos\left(\frac{\sqrt{391}}{4}t\right) + B\sin\left(\frac{\sqrt{391}}{4}t\right)\right].$$

### 1.3 Steady-state (particular) solution

Seek $x_p(t) = C\cos(4t) + D\sin(4t)$. Substitution into the ODE gives

$$(-32C + 12D + 50C)\cos(4t) + (-32D - 12C + 50D)\sin(4t) = 10\cos(4t),$$

so

$$18C + 12D = 10, \qquad -12C + 18D = 0.$$

Solving,

$$C = \frac{5}{13}, \qquad D = \frac{10}{39}.$$

Thus

$$x_p(t) = \frac{5}{13}\cos(4t) + \frac{10}{39}\sin(4t).$$

Equivalently, in amplitude–phase form,

$$x_p(t) = X\cos(4t - \phi), \qquad X = \frac{10}{\sqrt{(50 - 2\cdot 16)^2 + (3\cdot 4)^2}} = \frac{10}{\sqrt{117}} \approx 0.92848\ \mathrm{m},$$

$$\phi = \operatorname{atan2}(12, -18) \approx 2.55359\ \mathrm{rad}.$$

### 1.4 Initial conditions

At $t = 0$:

$$x(0) = A + \frac{5}{13} = 0.1 = \frac{1}{10} \quad\Longrightarrow\quad A = \frac{1}{10} - \frac{5}{13} = -\frac{37}{130} \approx -0.284615384615385\ \mathrm{m}.$$

Differentiating,

$$\dot x(t) = e^{-3t/4}\left[\left(-\frac{3}{4}A + \frac{\sqrt{391}}{4}B\right)\cos\left(\frac{\sqrt{391}}{4}t\right) + \left(-\frac{3}{4}B - \frac{\sqrt{391}}{4}A\right)\sin\left(\frac{\sqrt{391}}{4}t\right)\right] + \frac{20}{13}\cos(4t) - \frac{40}{39}\sin(4t).$$

At $t = 0$:

$$\dot x(0) = -\frac{3}{4}A + \frac{\sqrt{391}}{4}B + \frac{20}{13} = 0.$$

With $A = -37/130$,

$$B = \frac{4}{\sqrt{391}}\left(\frac{3}{4}A - \frac{20}{13}\right) \approx -0.250656440625879\ \mathrm{m}.$$

### 1.5 Final analytical solution

$$x(t) = e^{-3t/4}\left[-0.284615384615385\cos\left(\frac{\sqrt{391}}{4}t\right) - 0.250656440625879\sin\left(\frac{\sqrt{391}}{4}t\right)\right] + \frac{5}{13}\cos(4t) + \frac{10}{39}\sin(4t).$$

## 2. Characteristic parameters

| Quantity | Formula | Result | Units |
|---|---|---|---|
| Undamped natural frequency | $\omega_n = \sqrt{k/m}$ | 5.0 | rad/s |
| Damping ratio | $\zeta = c/(2\sqrt{mk})$ | 0.15 | — |
| Damped natural frequency | $\omega_d = \omega_n\sqrt{1-\zeta^2}$ | 4.94343 | rad/s |
| Steady-state amplitude | $X = F_0/\sqrt{(k-m\omega^2)^2+(c\omega)^2}$ | 0.92848 | m |
| Steady-state phase | $\phi = \operatorname{atan2}(c\omega,\,k-m\omega^2)$ | 2.55359 | rad |
| Transient decay rate | $\zeta\omega_n = c/(2m)$ | 0.75 | s$^{-1}$ |
| Transient time constant | $1/(\zeta\omega_n)$ | 1.33333 | s |

## 3. Numerical simulation and independent comparison

### 3.2 Step-size convergence

| Step size $h$ (s) | Steps | Max $\lvert x - x_{\text{exact}}\rvert$ (m) | Max $\lvert\dot x - \dot x_{\text{exact}}\rvert$ (m/s) | Observed order |
|---|---|---|---|---|
| 0.1 | 200 | $9.069\times 10^{-4}$ | $4.527\times 10^{-3}$ | — |
| 0.05 | 400 | $5.600\times 10^{-5}$ | $2.760\times 10^{-4}$ | 4.02 |
| 0.025 | 800 | $3.479\times 10^{-6}$ | $1.704\times 10^{-5}$ | 4.01 |
| 0.0125 | 1600 | $2.167\times 10^{-7}$ | $1.060\times 10^{-6}$ | 4.00 |

## 4. Energy balance

The mechanical energy is

$$E(t) = \frac{1}{2}m\dot x^2 + \frac{1}{2}kx^2.$$

| Quantity | Value | Units |
|---|---|---|
| $E(0)$ | 0.250000 | J |
| $E(20)$ | 4.21429 | J |
| Work input by forcing, $W_{\mathrm{in}} = \int_0^{20} F_0\cos(4t)\,\dot x\,dt$ | 104.175 | J |
| Energy dissipated by damping, $W_d = \int_0^{20} c\,\dot x^2\,dt$ | 100.210 | J |
| Balance residual $E(20) - E(0) - (W_{\mathrm{in}} - W_d)$ | $1.20\times 10^{-6}$ | J |

## 5. Physical interpretation

- **External forcing effect:** In steady state the oscillation settles to a constant amplitude $X \approx 0.928\ \mathrm{m}$ at the forcing frequency, phase-lagged by $\phi \approx 2.554\ \mathrm{rad}$ relative to the force.
