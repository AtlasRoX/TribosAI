"""Real-execution test suite for scientific plotting styles (Section 9, 10, 11, 12).

Tests:
1. Multi-panel composition with pie, stacked horizontal bars, small multiples, and grouped bars.
2. Mathematical time-series curve with axes, units, and grid.
3. Named and custom dashed/dotted line styles.
4. Subplots exercising multiple markevery modes.
5. Unfilled markers.
6. A sigmoid with a mathematical legend, reference lines, and annotations.
7. The actual evaluated oscillator trajectory.
8. Heat-equation data displayed as a profile or heatmap.
9. An uncertainty plot using actual computed uncertainty.
"""

from __future__ import annotations

import base64

from tribos.agentic.sandbox.runner import run_code


def test_style_1_multipanel_composition():
    """1. Multi-panel composition with pie, stacked horizontal bars, small multiples, and grouped bars."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

fig = plt.figure(figsize=(10, 8))
gs = fig.add_gridspec(2, 2)

# Panel 1: Pie chart
ax1 = fig.add_subplot(gs[0, 0])
sizes = [35, 25, 20, 20]
labels = ['Alpha', 'Beta', 'Gamma', 'Delta']
ax1.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
ax1.set_title('Category Distribution')

# Panel 2: Stacked horizontal bars
ax2 = fig.add_subplot(gs[0, 1])
categories = ['Group A', 'Group B', 'Group C']
val1 = np.array([12, 18, 15])
val2 = np.array([8, 14, 10])
ax2.barh(categories, val1, label='Component 1', color='#4575b4')
ax2.barh(categories, val2, left=val1, label='Component 2', color='#d73027')
ax2.set_title('Stacked Component Breakdown')
ax2.legend()

# Panel 3: Small multiples
ax3 = fig.add_subplot(gs[1, 0])
x = np.linspace(0, 10, 50)
ax3.plot(x, np.sin(x), 'b-', label='Mode 1')
ax3.plot(x, np.sin(2*x), 'r--', label='Mode 2')
ax3.set_title('Small Multiples: Harmonic Modes')
ax3.legend()

# Panel 4: Grouped bars
ax4 = fig.add_subplot(gs[1, 1])
ind = np.arange(3)
width = 0.35
ax4.bar(ind - width/2, [20, 35, 30], width, label='Treatment', color='#2ca02c')
ax4.bar(ind + width/2, [25, 32, 34], width, label='Control', color='#1f77b4')
ax4.set_xticks(ind)
ax4.set_xticklabels(['Exp 1', 'Exp 2', 'Exp 3'])
ax4.set_title('Grouped Comparison')
ax4.legend()

plt.tight_layout()
result = {'panel_count': 4}
"""
    res = run_code(code)
    assert res["status"] == "ok", f"Execution failed: {res.get('error')}"
    assert len(res["figures"]) == 1
    fig = res["figures"][0]
    assert len(fig["axes"]) == 4
    assert fig["axes"][0]["title"] == "Category Distribution"
    assert fig["axes"][1]["title"] == "Stacked Component Breakdown"
    assert len(base64.b64decode(fig["png_base64"])) > 10000


def test_style_2_mathematical_timeseries():
    """2. Mathematical time-series curve with axes, units, and grid."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

t = np.linspace(0, 5, 250)  # seconds
y = np.exp(-0.8 * t) * np.cos(2 * np.pi * 1.5 * t)  # meters

fig, ax = plt.subplots(figsize=(7, 4))
ax.plot(t, y, 'b-', linewidth=1.8, label=r'$y(t) = e^{-0.8t} \\cos(3\\pi t)$')
ax.set_title('Transient Damped Oscillation')
ax.set_xlabel('Time t [s]')
ax.set_ylabel('Displacement y [m]')
ax.grid(True, linestyle=':', alpha=0.6)
ax.legend(loc='upper right')

result = {'final_y': float(y[-1])}
"""
    res = run_code(code)
    assert res["status"] == "ok"
    assert len(res["figures"]) == 1
    fig = res["figures"][0]
    assert fig["axes"][0]["xlabel"] == "Time t [s]"
    assert fig["axes"][0]["ylabel"] == "Displacement y [m]"


def test_style_3_named_and_custom_linestyles():
    """3. Named and custom dashed/dotted line styles."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 100)
fig, ax = plt.subplots(figsize=(7, 4))

ax.plot(x, x, linestyle='solid', label='solid')
ax.plot(x, x + 1, linestyle='dashed', label='dashed')
ax.plot(x, x + 2, linestyle='dashdot', label='dashdot')
ax.plot(x, x + 3, linestyle='dotted', label='dotted')
ax.plot(x, x + 4, linestyle=(0, (5, 5)), label='custom dash (5, 5)')
ax.plot(x, x + 5, linestyle=(0, (3, 1, 1, 1)), label='custom dash-dot-dot')

ax.set_title('Named and Custom Linestyles')
ax.legend()
result = {'lines': 6}
"""
    res = run_code(code)
    assert res["status"] == "ok"
    assert len(res["figures"]) == 1


def test_style_4_markevery_modes():
    """4. Subplots exercising several markevery modes."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 100)
y = np.sin(x)

fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(8, 6))

ax1.plot(x, y, '-o', markevery=10, label='int step 10')
ax1.set_title('markevery=10 (integer)')

ax2.plot(x, y, '-s', markevery=0.1, label='float 0.1')
ax2.set_title('markevery=0.1 (fraction)')

ax3.plot(x, y, '-^', markevery=(0, 15), label='tuple (start, step)')
ax3.set_title('markevery=(0, 15) (tuple)')

ax4.plot(x, y, '-d', markevery=[0, 20, 50, 80], label='list of indices')
ax4.set_title('markevery=[0, 20, 50, 80] (list)')

plt.tight_layout()
result = {'cases': 4}
"""
    res = run_code(code)
    assert res["status"] == "ok"
    assert len(res["figures"]) == 1
    assert len(res["figures"][0]["axes"]) == 4


def test_style_5_unfilled_markers():
    """5. Unfilled markers with edge formatting."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 5, 20)
fig, ax = plt.subplots(figsize=(6, 4))

ax.plot(x, x**1.5, marker='o', markerfacecolor='none', markeredgecolor='crimson',
        markeredgewidth=1.8, markersize=8, linestyle='-', color='crimson', label='Unfilled Circle')
ax.plot(x, x**1.2, marker='s', markerfacecolor='none', markeredgecolor='navy',
        markeredgewidth=1.8, markersize=8, linestyle='--', color='navy', label='Unfilled Square')

ax.set_title('Unfilled Markers with Edge Formatting')
ax.legend()
result = {'count': 2}
"""
    res = run_code(code)
    assert res["status"] == "ok"
    assert len(res["figures"]) == 1


def test_style_6_sigmoid_annotations_and_reference_lines():
    """6. A sigmoid with a mathematical legend, reference lines and annotations."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

z = np.linspace(-6, 6, 200)
sigma = 1.0 / (1.0 + np.exp(-z))

fig, ax = plt.subplots(figsize=(7, 4.5))
ax.plot(z, sigma, 'b-', linewidth=2.0, label=r'$\\sigma(z) = \\frac{1}{1 + e^{-z}}$')

# Reference lines
ax.axhline(0.0, color='black', linestyle='-', linewidth=0.8)
ax.axhline(1.0, color='gray', linestyle=':', linewidth=1.0)
ax.axhline(0.5, color='orange', linestyle='--', linewidth=1.0)
ax.axvline(0.0, color='gray', linestyle=':', linewidth=1.0)

# Annotation
ax.annotate(r'Inflection Point $(0, 0.5)$', xy=(0.0, 0.5), xytext=(1.2, 0.35),
            arrowprops=dict(facecolor='black', shrink=0.08, width=1, headwidth=6))

ax.set_title('Logistic Sigmoid Function')
ax.set_xlabel('Input z')
ax.set_ylabel(r'Activation $\\sigma(z)$')
ax.set_ylim(-0.05, 1.05)
ax.legend(loc='upper left', fontsize=11)
ax.grid(True, alpha=0.3)

result = {'inflection': 0.5}
"""
    res = run_code(code)
    assert res["status"] == "ok"
    assert len(res["figures"]) == 1
    fig = res["figures"][0]
    assert fig["axes"][0]["title"] == "Logistic Sigmoid Function"


def test_style_7_actual_oscillator_trajectory():
    """7. The actual evaluated oscillator trajectory from classical RK4 arrays."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

m, c, k = 2.0, 0.6, 8.0
x0, v0 = 0.05, 0.0
h = 0.01
steps = 200

t = np.linspace(0, 2.0, steps + 1)
x = np.zeros(steps + 1)
v = np.zeros(steps + 1)
x[0], v[0] = x0, v0

for i in range(steps):
    xi, vi = x[i], v[i]
    k1_x = vi
    k1_v = (-c * vi - k * xi) / m
    
    k2_x = vi + 0.5 * h * k1_v
    k2_v = (-c * (vi + 0.5 * h * k1_v) - k * (xi + 0.5 * h * k1_x)) / m
    
    k3_x = vi + 0.5 * h * k2_v
    k3_v = (-c * (vi + 0.5 * h * k2_v) - k * (xi + 0.5 * h * k2_x)) / m
    
    k4_x = vi + h * k3_v
    k4_v = (-c * (vi + h * k3_v) - k * (xi + h * k3_x)) / m
    
    x[i+1] = xi + (h / 6.0) * (k1_x + 2*k2_x + 2*k3_x + k4_x)
    v[i+1] = vi + (h / 6.0) * (k1_v + 2*k2_v + 2*k3_v + k4_v)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
ax1.plot(t, x, 'b-', label='Displacement x(t)')
ax1.set_ylabel('x [m]')
ax1.set_title('Damped Oscillator RK4 Trajectory (m=2 kg, c=0.6 Ns/m, k=8 N/m)')
ax1.grid(True)
ax1.legend()

ax2.plot(t, v, 'r--', label='Velocity v(t)')
ax2.set_xlabel('Time t [s]')
ax2.set_ylabel('v [m/s]')
ax2.grid(True)
ax2.legend()

plt.tight_layout()
result = {'final_x': float(x[-1]), 'final_v': float(v[-1])}
"""
    res = run_code(code)
    assert res["status"] == "ok"
    assert len(res["figures"]) == 1
    fig = res["figures"][0]
    assert len(fig["axes"]) == 2
    assert -0.027 < res["result"]["final_x"] < -0.026


def test_style_8_heat_equation_heatmap_and_profile():
    """8. Heat-equation data displayed as a profile and heatmap."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

nodes = 11
steps = 8
u = np.full(nodes, 20.0)
u[0] = 80.0
u[-1] = 20.0
r = 0.2

history = [u.copy()]
for _ in range(steps):
    un = u.copy()
    for i in range(1, nodes - 1):
        un[i] = u[i] + r * (u[i+1] - 2*u[i] + u[i-1])
    un[0] = 80.0
    un[-1] = 20.0
    u = un
    history.append(u.copy())

H = np.array(history)  # (9, 11)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

# Profile
x_coords = np.linspace(0, 1, nodes)
for idx in [0, 2, 4, 8]:
    ax1.plot(x_coords, H[idx], marker='o', label=f'step {idx}')
ax1.set_title('1D Heat FTCS Temperature Profiles')
ax1.set_xlabel('Position x [m]')
ax1.set_ylabel('Temperature [°C]')
ax1.legend()
ax1.grid(True)

# Heatmap
im = ax2.imshow(H, aspect='auto', origin='lower', extent=[0, 1, 0, 200], cmap='inferno')
ax2.set_title('Spatiotemporal Thermal Diffusion')
ax2.set_xlabel('Position x [m]')
ax2.set_ylabel('Time t [s]')
fig.colorbar(im, ax=ax2, label='T [°C]')

plt.tight_layout()
result = {'T_final_mid': float(u[5])}
"""
    res = run_code(code)
    assert res["status"] == "ok"
    assert len(res["figures"]) == 1
    fig = res["figures"][0]
    assert len(fig["axes"]) >= 2


def test_style_9_uncertainty_plot():
    """9. Uncertainty plot with computed standard error and confidence bands."""
    code = """
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 30)
y_true = np.sin(x)
se = 0.15 + 0.05 * np.cos(x/2)**2  # heteroscedastic uncertainty

fig, ax = plt.subplots(figsize=(7, 4.5))
ax.errorbar(x, y_true, yerr=se, fmt='o', color='darkblue', ecolor='gray',
            elinewidth=1.2, capsize=3, label=r'Estimate $\\pm 1\\sigma$')
ax.fill_between(x, y_true - 2*se, y_true + 2*se, color='blue', alpha=0.15, label=r'$2\\sigma$ uncertainty band')

ax.set_title('Measurement Uncertainty with Heteroscedastic Error')
ax.set_xlabel('Parameter x')
ax.set_ylabel('Observed Response y')
ax.legend(loc='lower left')
ax.grid(True, alpha=0.3)

result = {'max_se': float(np.max(se))}
"""
    res = run_code(code)
    assert res["status"] == "ok"
    assert len(res["figures"]) == 1
    fig = res["figures"][0]
    assert fig["axes"][0]["title"] == "Measurement Uncertainty with Heteroscedastic Error"
