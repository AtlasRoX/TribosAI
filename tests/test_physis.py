"""Unit tests for Physis (tribos.physis & tribos.extensions.physis)."""

from __future__ import annotations

import math

import httpx
import pytest

from tribos.physis import (
    BUILTIN_MATERIALS,
    PhysisClients,
    PhysisEngine,
    check_dimensional_homogeneity,
    convert_units,
    normalize_oeis_response,
    parse_nist_allascii,
    parse_nist_ascii_value,
    search_builtin_materials,
    search_constants,
)
from tribos.tools.registry import ToolRegistry, register_default_tools


def test_nist_constants_lookup_and_allascii_parser() -> None:
    c_res = search_constants("c")
    assert c_res["count"] >= 1
    top = c_res["constants"][0]
    assert top["name"] == "speed of light in vacuum"
    assert top["symbol"] == "c"
    assert top["value"] == 299792458.0
    assert top["uncertainty"] == 0.0
    assert top["source"] == "NIST CODATA 2022"

    h_res = search_constants("Planck constant")
    assert h_res["count"] >= 1
    assert math.isclose(h_res["constants"][0]["value"], 6.62607015e-34, rel_tol=1e-9)

    hbar_res = search_constants("hbar")
    assert hbar_res["constants"][0]["name"] == "reduced Planck constant"

    # NIST allascii parser
    assert math.isclose(parse_nist_ascii_value("6.644 657 3450 e-27"), 6.6446573450e-27, rel_tol=1e-12)
    assert parse_nist_ascii_value("299 792 458") == 299792458.0
    assert math.isclose(parse_nist_ascii_value("12.566 370 614... e-7"), 1.2566370614e-6, rel_tol=1e-10)
    assert parse_nist_ascii_value("(exact)") == 0.0

    sample_table = """
Fundamental Physical Constants --- Complete Listing
Quantity                                              Value                  Uncertainty           Unit
----------------------------------------------------------------------------------------------------------------------------
alpha particle mass                                   6.644 657 3450 e-27    0.000 000 0020 e-27   kg
speed of light in vacuum                              299 792 458            (exact)               m s^-1
"""
    parsed = parse_nist_allascii(sample_table)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "alpha particle mass"
    assert parsed[0]["unit"] == "kg"
    assert parsed[1]["uncertainty"] == 0.0


def test_units_conversion_and_dimensional_homogeneity() -> None:
    ev_to_j = convert_units(1.0, "eV", "J")
    assert ev_to_j["compatible"] is True
    assert math.isclose(ev_to_j["converted_value"], 1.602176634e-19, rel_tol=1e-7)

    gpa_to_pa = convert_units(200.0, "GPa", "Pa")
    assert gpa_to_pa["compatible"] is True
    assert math.isclose(gpa_to_pa["converted_value"], 2.0e11, rel_tol=1e-9)

    bad = convert_units(1.0, "meter", "second")
    assert bad["compatible"] is False
    assert "error" in bad

    eq_ok = check_dimensional_homogeneity("kg * m / s^2 = N")
    assert eq_ok["compatible"] is True
    assert eq_ok["equation_homogeneous"] is True

    eq_bad = convert_units(check_equation="kg * m / s = J")
    assert eq_bad["compatible"] is False
    assert eq_bad["equation_homogeneous"] is False


def test_oeis_bare_array_and_dict_normalization() -> None:
    bare_array = [
        {
            "number": 45,
            "name": "Fibonacci numbers: F(n) = F(n-1) + F(n-2) with F(0) = 0 and F(1) = 1.",
            "data": "0,1,1,2,3,5,8,13,21,34,55,89,144",
            "formula": ["F(n) = ((1+sqrt(5))^n - (1-sqrt(5))^n)/(2^n*sqrt(5))."],
            "comment": ["Also called Lamé's sequence."],
            "keyword": "nonn,core,nice,easy",
        }
    ]
    seqs = normalize_oeis_response(bare_array, limit=5)
    assert len(seqs) == 1
    assert seqs[0]["id"] == "A000045"
    assert seqs[0]["terms"][:7] == [0, 1, 1, 2, 3, 5, 8]

    wrapped = {"results": bare_array}
    seqs_wrapped = normalize_oeis_response(wrapped, limit=5)
    assert seqs_wrapped[0]["id"] == "A000045"


@pytest.mark.asyncio
async def test_physis_clients_mock_transport_and_fallbacks() -> None:
    assert len(BUILTIN_MATERIALS) == 25
    si_matches = search_builtin_materials(formula="Si")
    assert any(m["material_id"] == "mp-149" for m in si_matches)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oeis.org/search" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 108,
                        "name": "Catalan numbers: C(n) = binomial(2n,n)/(n+1).",
                        "data": "1,1,2,5,14,42,132,429",
                        "formula": ["C(n) = (2n)! / ((n+1)!n!)"],
                    }
                ],
            )
        if "api.materialsproject.org/materials/summary" in url:
            assert request.headers.get("X-API-KEY") == "test-mp-key"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "material_id": "mp-149",
                            "formula_pretty": "Si",
                            "band_gap": 1.12,
                            "density": 2.33,
                            "is_stable": True,
                            "symmetry": {"crystal_system": "Cubic", "symbol": "Fd-3m"},
                        }
                    ]
                },
            )
        if "wolframalpha.com/api/v1/llm-api" in url:
            return httpx.Response(200, text="Result: pi^2 / 6 ≈ 1.64493")
        if "en.wikipedia.org/w/rest.php/v1/search/page" in url:
            return httpx.Response(
                200,
                json={
                    "pages": [
                        {
                            "key": "Noether's_theorem",
                            "title": "Noether's theorem",
                            "description": "Theorem linking differentiable symmetries and conservation laws",
                            "excerpt": "Every differentiable symmetry of the action of a physical system has a corresponding conservation law.",
                        }
                    ]
                },
            )
        if "en.wikipedia.org/api/rest_v1/page/summary" in url:
            return httpx.Response(
                200,
                json={
                    "title": "Noether's theorem",
                    "description": "Theorem linking symmetries and conservation laws",
                    "extract": "Noether's theorem states that every differentiable symmetry of the action of a physical system with conservative forces has a corresponding conservation law.",
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Noether%27s_theorem"}},
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    # 1. Unconfigured keys -> fallback / skipped
    offline_clients = PhysisClients(mp_api_key="", wolfram_appid="", transport=transport)
    offline_engine = PhysisEngine(clients=offline_clients)

    mat_offline = await offline_engine.lookup_materials(formula="GaN")
    assert mat_offline["source"] == "builtin_reference"
    assert mat_offline["materials"][0]["material_id"] == "mp-804"
    assert "TRIBOS_MP_API_KEY not set" in mat_offline["note"]

    wolf_skipped = await offline_engine.query_wolfram("integrate sin(x)/x from 0 to infinity")
    assert wolf_skipped["skipped"] is True
    assert "TRIBOS_WOLFRAM_APPID" in wolf_skipped["skipped_reason"]

    # 2. Configured keys -> live mock transport
    live_clients = PhysisClients(
        mp_api_key="test-mp-key",
        wolfram_appid="test-wolf-id",
        transport=transport,
    )
    live_engine = PhysisEngine(clients=live_clients)

    oeis_res = await live_engine.lookup_oeis("1, 1, 2, 5, 14, 42")
    assert oeis_res["canonical_id"] == "A000108"
    assert oeis_res["sequences"][0]["terms"][:6] == [1, 1, 2, 5, 14, 42]

    mat_live = await live_engine.lookup_materials(formula="Si")
    assert mat_live["source"] == "materials_project"
    assert mat_live["materials"][0]["material_id"] == "mp-149"

    wolf_live = await live_engine.query_wolfram("sum 1/n^2 from n=1 to infinity")
    assert wolf_live["skipped"] is False
    assert "1.64493" in wolf_live["result"]

    wiki_res = await live_engine.lookup_encyclopedia("Noether's theorem")
    assert wiki_res["count"] == 1
    assert "conservation law" in wiki_res["entries"][0]["extract"]


@pytest.mark.asyncio
async def test_physis_tools_in_registry() -> None:
    reg = ToolRegistry()
    register_default_tools(reg)

    c_res = await reg.execute("physis_constants", {"query": "Boltzmann constant"})
    assert c_res.success is True
    assert c_res.data["constants"][0]["symbol"] == "k_B"

    u_res = await reg.execute("physis_units", {"value": 1.0, "from_unit": "atm", "to_unit": "Pa"})
    assert u_res.success is True
    assert math.isclose(u_res.data["converted_value"], 101325.0, rel_tol=1e-6)
