---
name: numerical-verification
description: Simulations, ODE/PDE solutions and other numerical results.
triggers:
  - \bsimulat\w*|\bintegrat\w*\b|\bnumerical\w*
  - \b(?:ODE|PDE|finite[- ]element|finite[- ]difference|runge[- ]kutta|time[- ]step\w*)\b
  - \bconverg\w*
---
1. State the model exactly as solved: equations, parameters with units, initial and boundary conditions, time span.
2. Give the method and its settings (scheme or solver, step or tolerance, mesh) and how the result was checked: a second method, refinement with the observed order, a conserved quantity, an exact solution.
3. Report values with the precision the checks support, not more; give errors as numbers.
4. Say what the numerics do not show (behaviour beyond the simulated time, other parameters, proofs of existence or blow-up).
