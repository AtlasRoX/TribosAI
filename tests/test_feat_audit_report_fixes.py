"""Regression tests for the defects recorded in AUDIT_REPORT.md (AUDIT-001 ... AUDIT-024)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from tribos.harness.hitl import ArtifactHITLManager
from tribos.memory.semantic import CODATA_CONSTANTS, STANDARDS_CATALOG, find_material
from tribos.substrate import check_asme_compliance
from tribos.substrate.cad.inspector import GeometryInspector
from tribos.substrate.cae.review import CAEReviewer

CYL = "ASME_VIII_1_UG27_CYL"
SPH = "ASME_VIII_1_UG27_SPH"


def _vessel(**over: float) -> dict[str, float]:
    base = {"pressure_mpa": 1.0, "radius_mm": 1000.0, "allowable_stress_mpa": 138.0, "joint_efficiency": 1.0,
            "wall_thickness_mm": 10.0}
    return {**base, **over}


# AUDIT-001 / AUDIT-018: UG-27 ---------------------------------------------------------------------------------------
def test_ug27_sphere_is_evaluated_with_the_d_formula():
    t_req = 1.0 * 1000.0 / (2 * 138.0 - 0.2 * 1.0)
    ok = check_asme_compliance(_vessel(wall_thickness_mm=4.0), clause_id=SPH)
    assert ok["compliant"] is True and ok["required_thickness_mm"] == pytest.approx(t_req, abs=1e-3)
    thin = check_asme_compliance(_vessel(pressure_mpa=50.0, allowable_stress_mpa=100.0, wall_thickness_mm=0.001),
                                 clause_id=SPH)
    assert thin["compliant"] is False


def test_ug27_cylinder_takes_the_governing_of_c1_and_c2():
    res = check_asme_compliance(_vessel(pressure_mpa=2.0, radius_mm=500.0, joint_efficiency=0.85,
                                        wall_thickness_mm=12.0), clause_id=CYL)
    t_c1 = 2.0 * 500.0 / (138.0 * 0.85 - 0.6 * 2.0)
    assert res["compliant"] is True and res["required_thickness_mm"] == pytest.approx(t_c1, abs=1e-3)


@pytest.mark.parametrize("params", [
    _vessel(pressure_mpa=60.0, radius_mm=100.0, wall_thickness_mm=200.0),  # P > 0.385 SE
    _vessel(radius_mm=10.0, wall_thickness_mm=8.0),  # t > R/2
])
def test_ug27_outside_applicability_is_never_compliant(params):
    res = check_asme_compliance(params, clause_id=CYL)
    assert res["compliant"] is None and res["status"] == "outside_applicability"


@pytest.mark.parametrize("params", [
    _vessel(pressure_mpa=-1.0), _vessel(joint_efficiency=1.5), _vessel(wall_thickness_mm=0.0),
    _vessel(radius_mm=float("nan")),
])
def test_ug27_invalid_inputs_are_not_evaluated(params):
    assert check_asme_compliance(params, clause_id=CYL)["compliant"] is None


def test_unknown_or_unimplemented_clause_is_never_compliant():
    assert check_asme_compliance(_vessel(), clause_id="API_650")["compliant"] is None
    for clause in STANDARDS_CATALOG.values():
        assert clause.evaluate_compliance({})["compliant"] is None


# AUDIT-002: geometry --------------------------------------------------------------------------------------------------
def _cube_stl(a: float) -> str:
    v = [(0, 0, 0), (a, 0, 0), (a, a, 0), (0, a, 0), (0, 0, a), (a, 0, a), (a, a, a), (0, a, a)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    out = ["solid cube"]
    for f in faces:
        out += ["facet normal 0 0 0", "outer loop", *(f"vertex {v[i][0]} {v[i][1]} {v[i][2]}" for i in f),
                "endloop", "endfacet"]
    return "\n".join(out + ["endsolid cube"])


def test_stl_cube_known_answers():
    g = GeometryInspector.inspect_stl_ascii(_cube_stl(10.0), density_kg_m3=1000.0)
    assert g.watertight is True
    assert g.volume_mm3 == pytest.approx(1000.0)
    assert g.surface_area_mm2 == pytest.approx(600.0)
    assert g.center_of_gravity_mm == pytest.approx((5.0, 5.0, 5.0))
    assert g.mass_kg == pytest.approx(1000.0 * 1e-9 * 1000.0)


def test_stl_single_triangle_area_and_no_invented_volume():
    tri = "facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet"
    g = GeometryInspector.inspect_stl_ascii(tri)
    assert g.surface_area_mm2 == pytest.approx(50.0)
    assert g.volume_mm3 is None and g.mass_kg is None


@pytest.mark.parametrize("content", ["", "/etc/passwd", "C:/models/part.stl"])
def test_stl_without_facets_is_an_error_not_a_default_part(content):
    with pytest.raises(ValueError):
        GeometryInspector.inspect_stl_ascii(content)


# AUDIT-003: CAE gates -------------------------------------------------------------------------------------------------
def test_cae_zero_inputs_are_not_verified():
    res = CAEReviewer.run_full_cae_audit(applied_load_n=0, reaction_force_n=1e9, coarse_stress_mpa=0,
                                         fine_stress_mpa=0, yield_strength_mpa=250, analytical_stress_mpa=0)
    assert res["cae_verified"] is False
    assert res["gates_not_evaluated"] >= 4
    assert "14" not in res["verdict"]


def test_cae_singularity_gate_needs_the_ratio():
    res = CAEReviewer.run_full_cae_audit(applied_load_n=1e4, reaction_force_n=1e4, coarse_stress_mpa=140,
                                         fine_stress_mpa=143, yield_strength_mpa=250, analytical_stress_mpa=141)
    assert res["cae_verified"] is False
    assert [g["passed"] for g in res["gates"]][3] is None


# AUDIT-010 / AUDIT-015 / AUDIT-022: materials and constants ---------------------------------------------------------
def test_material_properties_only_at_room_temperature():
    al = find_material("Aluminum 6061-T6")
    assert al is not None and al.yield_at_temp(20.0) == 276.0
    assert al.yield_at_temp(260.0) is None and al.e_at_temp(-40.0) is None


@pytest.mark.parametrize("query", ["a", "steel", "6061", "", "  "])
def test_material_lookup_never_guesses(query):
    assert find_material(query) is None


@pytest.mark.parametrize("query,name", [("AISI-4140", "AISI 4140"), ("ti64", "Ti-6Al-4V"), ("316L", "316L")])
def test_material_lookup_by_alias(query, name):
    mat = find_material(query)
    assert mat is not None and name in mat.name


def test_semantic_constants_match_codata_exact_values():
    assert CODATA_CONSTANTS["gas_constant"][0] == pytest.approx(8.31446261815324, rel=1e-15)
    assert CODATA_CONSTANTS["boltzmann_constant"][0] == 1.380649e-23


# AUDIT-017: HITL signature ----------------------------------------------------------------------------------------
def test_hitl_signature_is_keyed_and_tamper_evident(tmp_path):
    mgr = ArtifactHITLManager(db_path=tmp_path / "hitl.sqlite3")
    rev = mgr.sign_off_artifact("art_1", "proj_x", "alice", "approved", content_sha256="a" * 64)
    assert mgr.verify_signature(rev)
    rev.action = "rejected"
    assert not mgr.verify_signature(rev)
    (tmp_path / "other").mkdir()
    other = ArtifactHITLManager(db_path=tmp_path / "other" / "hitl.sqlite3")  # a different key
    assert not other.verify_signature(mgr.list_artifact_reviews("art_1")[0])


# AUDIT-004: harness authorization ---------------------------------------------------------------------------------
@pytest.fixture()
def two_users(monkeypatch):
    from app.backend.main import app

    tok_a, tok_b = "a" * 40, "b" * 40
    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", f"{tok_a}:alice_audit,{tok_b}:bob_audit")
    with TestClient(app, base_url="http://localhost") as client:
        yield client, {"Authorization": f"Bearer {tok_a}"}, {"Authorization": f"Bearer {tok_b}"}


def test_harness_routes_enforce_project_membership(two_users):
    client, alice, bob = two_users
    pid = client.post("/api/projects", json={"name": "Alice vessel"}, headers=alice).json()["id"]
    tid = client.post(f"/api/harness/projects/{pid}/threads", json={"title": "t"}, headers=alice).json()["thread_id"]
    client.post(f"/api/harness/threads/{tid}/turns", json={"role": "user", "content": "secret"}, headers=alice)
    rid = client.post(f"/api/harness/projects/{pid}/revisions", json={"content": "x"}, headers=alice).json()["revision_id"]

    assert client.get(f"/api/harness/projects/{pid}/threads", headers=bob).status_code == 404
    assert client.get(f"/api/harness/threads/{tid}/turns", headers=bob).status_code == 404
    assert client.post(f"/api/harness/threads/{tid}/turns", json={"role": "user", "content": "x"},
                       headers=bob).status_code == 404
    assert client.post(f"/api/harness/projects/{pid}/revisions", json={"content": "x"}, headers=bob).status_code == 404
    assert client.post("/api/harness/revisions/diff", json={"rev_id_a": rid, "rev_id_b": rid},
                       headers=bob).status_code == 404
    assert client.post("/api/harness/artifacts/art_z/signoff", json={"project_id": pid, "action": "approved"},
                       headers=bob).status_code == 404
    assert client.get(f"/api/harness/projects/{pid}/spend", headers=bob).status_code == 404
    assert client.get("/api/harness/runs/run_0123456789abcdef/cost", headers=bob).status_code == 404

    ok = client.post("/api/harness/artifacts/art_z/signoff", json={"project_id": pid, "action": "approved"},
                     headers=alice)
    assert ok.status_code == 200
    assert client.get("/api/harness/artifacts/art_z/reviews", headers=bob).json()["reviews"] == []
    mine = client.get("/api/harness/artifacts/art_z/reviews", headers=alice).json()["reviews"]
    assert mine and mine[0]["reviewer_id"] == "alice_audit" and mine[0]["signature_valid"] is True


def test_revision_author_is_the_authenticated_user(two_users):
    client, alice, _ = two_users
    pid = client.post("/api/projects", json={"name": "Authorship"}, headers=alice).json()["id"]
    client.post(f"/api/harness/projects/{pid}/revisions", json={"content": "x", "author": "certified_engineer"},
                headers=alice)
    revs = client.get(f"/api/harness/projects/{pid}/revisions", headers=alice).json()["revisions"]
    assert revs[0]["author"] == "alice_audit"


# AUDIT-005 / AUDIT-023: written-answer identity and inequality checks ------------------------------------------------
def _claim_statuses(answer: str, query: str = "") -> dict[str, str]:
    from tribos.verify.math_claims import audit_answer

    return {c.text: c.status for c in audit_answer(answer, query=query).claims}


@pytest.mark.parametrize("identity", [r"\sqrt{x^2} = x", r"\ln(x^2) = 2\ln(x)", r"|x| = x"])
def test_identities_false_for_negative_reals_are_not_passed(identity):
    statuses = _claim_statuses(f"For every real number $x$:\n\n$${identity}$$\n", "identities for real x")
    assert statuses and all(s != "passed" for s in statuses.values())


@pytest.mark.parametrize("identity", [r"\sqrt{x^2} = |x|", r"(x+1)^2 = x^2 + 2x + 1", r"e^{2x} = (e^{x})^2"])
def test_true_identities_still_pass(identity):
    statuses = _claim_statuses(f"For every real number $x$:\n\n$${identity}$$\n", "identities for real x")
    assert list(statuses.values()) == ["passed"]


# AUDIT-007: curve fit uncertainty -----------------------------------------------------------------------------------
def test_fit_zero_dof_has_no_standard_errors_and_is_not_verified():
    from tribos.dynamis.engine import dynamis_fit_parameters

    r = dynamis_fit_parameters(model_expr="a + b*x", independent_var="x", param_names=["a", "b"],
                               x_data=[0.0, 1.0], y_data=[1.0, 3.0])
    assert r["std_errors"] == {"a": None, "b": None} and r["verified"] is False


def test_fit_unidentifiable_and_poor_fits_are_not_verified():
    import numpy as np

    from tribos.dynamis.engine import dynamis_fit_parameters

    x = list(np.linspace(0, 5, 20))
    y = [2 * xi + 0.1 * (-1) ** i for i, xi in enumerate(x)]
    unident = dynamis_fit_parameters(model_expr="a*b*x", independent_var="x", param_names=["a", "b"], x_data=x, y_data=y)
    assert unident["verified"] is False and unident["issues"]
    poor = dynamis_fit_parameters(model_expr="a*x", independent_var="x", param_names=["a"], x_data=x,
                                  y_data=[float(np.sin(3 * xi)) for xi in x])
    assert poor["verified"] is False


def test_fit_linear_standard_errors_match_the_analytic_formula():
    import numpy as np

    from tribos.dynamis.engine import dynamis_fit_parameters

    x = np.linspace(0.0, 9.0, 10)
    y = 1.5 + 0.8 * x + np.array([0.1, -0.2, 0.05, 0.0, 0.15, -0.1, -0.05, 0.2, -0.15, 0.0])
    r = dynamis_fit_parameters(model_expr="a + b*x", independent_var="x", param_names=["a", "b"],
                               x_data=list(x), y_data=list(y))
    resid = y - (r["parameters"]["a"] + r["parameters"]["b"] * x)
    s2 = float(resid @ resid) / (len(x) - 2)
    sxx = float(((x - x.mean()) ** 2).sum())
    assert r["std_errors"]["b"] == pytest.approx((s2 / sxx) ** 0.5, rel=1e-6)
    assert r["std_errors"]["a"] == pytest.approx((s2 * (1 / len(x) + x.mean() ** 2 / sxx)) ** 0.5, rel=1e-6)
    assert r["verified"] is True and r["converged"] is True


def test_fit_with_measurement_sigma_reports_absolute_errors():
    from tribos.dynamis.engine import dynamis_fit_parameters

    r = dynamis_fit_parameters(model_expr="a + b*x", independent_var="x", param_names=["a", "b"],
                               x_data=[0.0, 1.0, 2.0, 3.0], y_data=[1.0, 3.1, 4.9, 7.0], y_sigma=[0.1] * 4)
    assert r["std_error_basis"].startswith("absolute")
    with pytest.raises(ValueError):
        dynamis_fit_parameters(model_expr="a + b*x", independent_var="x", param_names=["a", "b"],
                               x_data=[0.0, 1.0, 2.0], y_data=[1.0, 3.0, 5.0], y_sigma=[0.1, 0.0, 0.1])


# AUDIT-008: sandbox isolation is visible ----------------------------------------------------------------------------
def test_sandbox_reports_whether_execution_is_os_isolated():
    from tribos.agentic.sandbox.gateway import isolation_status

    status = isolation_status()
    assert set(status) == {"backend", "os_isolated", "refused_reason"}
    assert status["os_isolated"] is (status["backend"] == "container")


def test_sandbox_strict_mode_refuses_the_unisolated_fallback(monkeypatch):
    from tribos.agentic.sandbox import gateway

    monkeypatch.setenv("TRIBOS_SANDBOX_BACKEND", "auto")
    monkeypatch.setenv("TRIBOS_SANDBOX_STRICT_LIMITS", "1")
    monkeypatch.delenv("TRIBOS_SANDBOX_ALLOW_UNISOLATED", raising=False)
    monkeypatch.setattr("tribos.agentic.sandbox.container.container_available", lambda: (False, "no runtime"))
    backend, reason = gateway._select_backend("python")
    assert backend is None and "strict" in reason


# AUDIT-013: calibration is bound to the code it measured -------------------------------------------------------------
def test_calibration_of_other_code_is_not_shown():
    from tribos.axiom.agent import calibrated_code_sha256, calibrated_confidence

    cal = {"statuses": {"verified": {"n": 43, "confidence": 0.97, "lower_95": 0.9}}}
    assert calibrated_confidence("verified", cal={**cal, "code_sha256": "0" * 64}) is None
    assert calibrated_confidence("verified", cal={**cal, "code_sha256": calibrated_code_sha256()}) is not None


# AUDIT-014: undefined answers are not partially verified ------------------------------------------------------------
def test_nan_answer_is_unverified():
    import asyncio

    from tribos.axiom.agent import solve_problem_tool

    r = asyncio.run(solve_problem_tool("Compute the integral of 1/x from -1 to 1"))
    assert r["answer"]["text"] == "nan"
    assert r["status"] == "unverified"


# AUDIT-016: eager combinatorial evaluation is bounded ---------------------------------------------------------------
@pytest.mark.parametrize("expr", ["factorial(10**7)", "binomial(10**9, 3)", "gamma(123456)"])
def test_huge_combinatorial_arguments_are_refused(expr):
    from tribos.axiom.engine import safe_parse_expr

    with pytest.raises(ValueError):
        safe_parse_expr(expr)


def test_small_combinatorial_arguments_still_evaluate():
    from tribos.axiom.engine import safe_parse_expr

    assert int(safe_parse_expr("factorial(10)")) == 3628800


# AUDIT-025: no canned scientific report is appended to or substituted for an answer ---------------------------------
def test_truncation_repair_never_appends_canned_sections():
    from tribos.scientific.assembly import check_and_repair_truncation

    answer = "Two papers matched the query."
    assert check_and_repair_truncation(answer, {"literature": {"papers": []}}) == answer
    assert check_and_repair_truncation(answer, {"scientific_execution": {"kind": "composite_scientific"}}) == answer


def test_eight_part_answer_refuses_missing_results():
    from tribos.scientific.assembly import MissingScientificResult, assemble_eight_part_answer

    with pytest.raises(MissingScientificResult):
        assemble_eight_part_answer({})
