"""Ideal first-order RC step response, evaluated with the caller's component values and time."""

from __future__ import annotations

import math
from typing import Any

from .core import Calculator, Check, Outcome, Param, Reference, Result


def rc_charge(v: dict[str, Any]) -> Outcome:
    resistance, capacitance, source, initial, t = (
        v[k] for k in ("resistance", "capacitance", "source_voltage", "initial_voltage", "time")
    )
    if t < 0:
        raise ValueError("The RC response is defined for time >= 0 after the switch closes.")
    tau = resistance * capacitance
    current_0 = (source - initial) / resistance
    current = current_0 * math.exp(-t / tau)
    capacitor = initial + (source - initial) * -math.expm1(-t / tau)
    resistor = current * resistance
    residual = source - capacitor - resistor
    return Outcome(
        results=[
            Result("time_constant", "Time constant", tau, "s"),
            Result("capacitor_voltage", "Capacitor voltage", capacitor, "V"),
            Result("initial_current", "Current at t=0+", current_0, "A", "mA"),
            Result("current", "Current at the requested time", current, "A", "mA"),
            Result("resistor_voltage", "Resistor voltage", resistor, "V"),
            Result("kvl_residual", "KVL residual", residual, "V"),
        ],
        validity=[
            Check("kvl", abs(residual) <= 1e-12 * max(1, abs(source)), "V_source - V_C - R I = 0")
        ],
        formulas=[
            "tau = R C",
            "V_C(t) = V_s + (V_0 - V_s) exp(-t/tau)",
            "I(t) = (V_s - V_0) exp(-t/tau)/R",
            "V_s = V_C + R I",
        ],
    )


CALCULATORS = (
    Calculator(
        id="rc_charge",
        title="RC step response",
        summary="First-order ideal series RC response after a voltage step.",
        reference=Reference(
            "Kirchhoff's voltage law and capacitor constitutive equation", "R C dV_C/dt + V_C = V_s"
        ),
        params=(
            Param("resistance", "ohm", "Series resistance R."),
            Param("capacitance", "F", "Capacitance C."),
            Param("source_voltage", "V", "Applied ideal voltage V_s.", positive=False),
            Param("initial_voltage", "V", "Initial capacitor voltage V_0.", positive=False),
            Param("time", "s", "Time after the switch closes.", positive=False),
        ),
        compute=rc_charge,
        assumptions=("Ideal constant voltage source, resistor and capacitor; t >= 0.",),
        keywords=("RC", "capacitor", "charging", "transient"),
    ),
)
