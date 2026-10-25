"""T6: the interactive simulation API (simulate, bifurcation, vector field)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

ROSSLER = {"rhs": {"x": "-y - z", "y": "x + a*y", "z": "b + z*(x - c)"}, "parameters": {"a": 0.2, "b": 0.2, "c": 2.5},
           "initial_state": {"x": 1.0, "y": 1.0, "z": 0.0}, "t_span": [0, 400]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TRIBOS_AUTH_MODE", "disabled")
    from app.backend.main import app
    from app.backend.routers import simulate as sim

    sim._rate._hits.clear()
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def test_simulate_returns_the_engine_shape_and_the_spec(client):
    r = client.post("/api/simulate", json={"rhs": {"x": "-k*x"}, "parameters": {"k": 2}, "initial_state": {"x": 1},
                                          "t_span": [0, 1], "num_points": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["spec"]["parameters"] == {"k": 2.0}
    final = body["summary"]["x"]["final"]
    assert final == pytest.approx(pytest.importorskip("math").exp(-2), rel=1e-3)


def test_old_messages_resolve_a_preset_by_name(client):
    r = client.post("/api/simulate", json={"model_name": "van_der_pol", "num_points": 100})
    assert r.status_code == 200, r.text
    assert r.json()["spec"]["model_name"] == "van_der_pol"
    assert client.post("/api/simulate", json={"model_name": "no_such_model"}).status_code == 422


def test_caps_and_unsafe_input_are_refused(client):
    assert client.post("/api/simulate", json={"model_name": "lorenz", "num_points": 5000}).status_code == 422
    assert client.post("/api/simulate/bifurcation", json={"spec": ROSSLER, "parameter": "c", "start": 2, "stop": 6,
                                                           "steps": 500}).status_code == 422
    assert client.post("/api/simulate/vector_field", json={"spec": {"model_name": "lotka_volterra"}, "x_var": "x",
                                                            "y_var": "y", "x_range": [0, 1], "y_range": [0, 1],
                                                            "n": 40}).status_code == 422
    bad = client.post("/api/simulate", json={"rhs": {"x": "__import__('os').system('x')"}, "initial_state": {"x": 1}})
    assert bad.status_code == 422
    assert client.post("/api/simulate", json={"model_name": "lorenz", "extra": 1}).status_code == 422


def test_rossler_bifurcation_shows_period_doubling(client):
    r = client.post("/api/simulate/bifurcation", json={"spec": ROSSLER, "parameter": "c", "start": 2.5, "stop": 5.0,
                                                        "steps": 6, "observable": "x", "transient_fraction": 0.6})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parameter"] == "c" and len(body["values"]) == 6
    counts = [len(p["maxima"]) for p in body["points"]]
    assert counts[0] == 1  # c = 2.5: a period-1 limit cycle
    assert max(counts[2:]) >= 2  # past the first period doubling (c ~ 2.83) the orbit has several maxima


def test_vector_field_shape(client):
    r = client.post("/api/simulate/vector_field", json={"spec": {"model_name": "lotka_volterra"}, "x_var": "x",
                                                         "y_var": "y", "x_range": [0.5, 2], "y_range": [0.5, 2], "n": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["u"]) == 5 and len(body["u"][0]) == 5 and body["max_magnitude"] > 0


def test_timeout_returns_504(client, monkeypatch):
    from tribos.dynamis import interactive

    def slow(**kwargs):
        time.sleep(1.5)
        return {}

    monkeypatch.setenv("TRIBOS_SIMULATE_TIMEOUT_S", "1")
    monkeypatch.setattr(interactive, "simulate", slow)
    r = client.post("/api/simulate", json={"model_name": "lorenz"})
    assert r.status_code == 504 and "longer than" in r.json()["detail"]


def test_rate_limit_returns_429(client, monkeypatch):
    from app.backend.routers import simulate as sim

    monkeypatch.setattr(sim, "_rate", sim.UserRateLimiter(2, 60.0))
    codes = [client.post("/api/simulate", json={"model_name": "harmonic_oscillator", "num_points": 10}).status_code
             for _ in range(3)]
    assert codes == [200, 200, 429]


def test_auth_is_required(monkeypatch):
    monkeypatch.setenv("TRIBOS_AUTH_MODE", "token")
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice")
    from app.backend.main import app

    with TestClient(app, base_url="http://localhost") as c:
        assert c.post("/api/simulate", json={"model_name": "lorenz"}).status_code == 401
        ok = c.post("/api/simulate", json={"model_name": "harmonic_oscillator", "num_points": 10},
                    headers={"Authorization": "Bearer alice-token"})
        assert ok.status_code == 200
