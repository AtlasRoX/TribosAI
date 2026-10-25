"""Tests for SageMath integration engine and tools."""

import pytest

from tribos.axiom.sagemath import find_sagemath_command, is_sagemath_available, run_sagemath_code
from tribos.extensions import register_extension_tools
from tribos.tools.registry import ToolRegistry


def test_sagemath_discovery_and_execution():
    cmd = find_sagemath_command(force_recheck=True)
    if not is_sagemath_available():
        pytest.skip(f"SageMath is not installed or accessible on this system (cmd={cmd}).")
    assert cmd is not None
    res = run_sagemath_code("var('x'); print('TEST_OUTPUT:', diff(x^3, x))")
    assert res["status"] == "ok"
    assert "TEST_OUTPUT: 3*x^2" in res["stdout"]
    assert res["canonical_id"].startswith("comp:sagemath:")


def test_sagemath_tools_registered():
    registry = ToolRegistry()
    register_extension_tools(registry)
    assert registry.get_entry("axiom_sagemath") is not None
    assert registry.get_entry("calcula_run_sagemath") is not None


def test_sagemath_plot_harvesting():
    if not is_sagemath_available():
        pytest.skip("SageMath is not installed or accessible on this system.")
    code = (
        "from sage.all import *; "
        "x = var('x'); "
        "p = plot(sin(x), (x, 0, 2*pi)); "
        "print('PLOTTED')"
    )
    res = run_sagemath_code(code, timeout_s=45)
    assert res["status"] == "ok"
    assert "PLOTTED" in res["stdout"]
    assert "figures" in res
    assert len(res["figures"]) >= 1
    fig = res["figures"][0]
    assert fig["name"] in ("p.png", "figure_1.png")
    assert len(fig["png_base64"]) > 500
