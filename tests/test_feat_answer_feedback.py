"""Answer ratings: POST /api/feedback records one JSON line per rating; the latest rating of a message wins."""

from __future__ import annotations

import json


def _client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.backend import main as backend_main

    monkeypatch.setenv("TRIBOS_FEEDBACK_DIR", str(tmp_path))
    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice")
    return TestClient(backend_main.app)


def test_a_rating_is_recorded_with_its_run_and_a_hashed_user(monkeypatch, tmp_path):
    from app.backend.routers.feedback import latest_ratings

    headers = {"Authorization": "Bearer alice-token"}
    with _client(monkeypatch, tmp_path) as api:
        body = {"rating": "up", "run_id": "run_1", "message_id": "m1", "question": "2+2?", "framework": "auto"}
        assert api.post("/api/feedback", json=body, headers=headers).json() == {"ok": True, "rating": "up"}
        assert api.post("/api/feedback", json={**body, "rating": "down"}, headers=headers).status_code == 200

    rows = [json.loads(line) for line in (tmp_path / "feedback.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[0]["run_id"] == "run_1" and rows[0]["framework"] == "auto"
    assert rows[0]["user"] != "alice" and len(rows[0]["user"]) == 16
    assert latest_ratings(tmp_path / "feedback.jsonl")["m1"]["rating"] == "down"


def test_an_unknown_rating_is_rejected(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as api:
        res = api.post("/api/feedback", json={"rating": "great"}, headers={"Authorization": "Bearer alice-token"})
        assert res.status_code == 422
    assert not (tmp_path / "feedback.jsonl").exists()


def test_the_backend_root_is_a_status_page_not_a_404(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as api:
        res = api.get("/")
        assert res.status_code == 200 and "Tribos backend is running" in res.text
        assert 'href="http://localhost:3000"' in res.text and "/api/health" in res.text
        monkeypatch.setenv("TRIBOS_WEB_URL", "javascript:alert(1)")  # never a script URL in the link
        assert 'href="http://localhost:3000"' in api.get("/").text
