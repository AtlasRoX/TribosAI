"""Certified critical points: interval branch-and-bound with the Krawczyk test proves the list complete."""

from __future__ import annotations

import sympy as sp

from tribos.axiom.certified_critical import certify_critical_points, extract_problem

NEW = (r"Plot the exact function: \[ f(x,y)=\frac{x^4+2y^2}{9} +\frac{(x-1)(y-2)}{3} +\sin(x+y-3) \] over the "
       r"domain: \[ -2\leq x\leq3,\qquad -1\leq y\leq4 \] Find all critical points.")
OLD = (r"Plot \[ f(x,y)=\frac{x^4+2y^2}{6}+\frac{(x-2)(y-5)}{2}+\sin(x+y-7) \] on the domain "
       r"\( -3\leq x\leq 3,\ 0\leq y\leq 6 \) and investigate all critical points.")


def test_the_one_interior_minimum_is_found_and_the_list_proved_complete():
    expr, xy, bounds = extract_problem(NEW)
    assert bounds == [(-2.0, 3.0), (-1.0, 4.0)]
    r = certify_critical_points(expr, xy, bounds)
    assert r["status"] == "complete" and len(r["points"]) == 1
    p = r["points"][0]
    assert abs(p["point"][0] - 1.18670) < 1e-4 and abs(p["point"][1] - 0.12461) < 1e-4
    assert abs(p["value"] - (-0.885966)) < 1e-5 and p["classification"] == "local minimum"


def test_no_critical_points_is_proved_not_just_unfound():
    r = certify_critical_points(*extract_problem(OLD))
    assert r["status"] == "complete" and r["points"] == []


def test_saddles_and_several_points():
    x, y = sp.symbols("x y")
    r = certify_critical_points(x**3 - 3 * x + y**2, (x, y), [(-2, 2), (-1, 1)])
    kinds = sorted((round(p["point"][0], 6), p["classification"]) for p in r["points"])
    assert r["status"] == "complete" and kinds == [(-1.0, "saddle point"), (1.0, "local minimum")]


def test_an_unsupported_function_is_not_certified():
    x, y = sp.symbols("x y")
    assert certify_critical_points(sp.gamma(x) + y**2, (x, y), [(1, 2), (-1, 1)])["status"] == "unsupported"


def test_the_proof_files_rerun_the_certification_without_tribos(tmp_path):
    import json
    import subprocess
    import sys

    from tribos.axiom.certified_critical import certificate_files

    expr, xy, bounds = extract_problem(NEW)
    result = {**certify_critical_points(expr, xy, bounds), "function": str(expr)}
    files = certificate_files(NEW, result)
    assert [k for k, _n, _d in files] == ["py", "json"]
    script = tmp_path / files[0][1]
    script.write_bytes(files[0][2])
    out = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, cwd=tmp_path, timeout=120)
    assert out.returncode == 0 and "status: complete" in out.stdout and "local minimum" in out.stdout
    assert json.loads(files[1][2])["points"][0]["classification"] == "local minimum"
