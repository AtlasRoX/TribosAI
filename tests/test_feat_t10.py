"""T10: shared projects with members, roles, files, reviewed memory, history and activity, and their runs."""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from tribos.utils.memory.project_store import ACTIVITY_CAP, FactInput, ProjectStore

ALICE = {"Authorization": "Bearer alice-token"}
BOB = {"Authorization": "Bearer bob-token"}
CAROL = {"Authorization": "Bearer carol-token"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBOS_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("TRIBOS_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.delenv("TRIBOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("TRIBOS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRIBOS_API_TOKENS", "alice-token:alice,bob-token:bob,carol-token:carol")
    from tribos.datasets.store import reset_dataset_store

    reset_dataset_store()
    from app.backend.main import app

    with TestClient(app, base_url="http://localhost") as c:
        yield c
    reset_dataset_store()


def _project(client, **extra) -> dict:
    body = {"name": "Beam lab", "description": "cantilevers", "instructions": "Use SI units.", "icon": "🧪",
            "color": "#2563eb", **extra}
    res = client.post("/api/projects", json=body, headers=ALICE)
    assert res.status_code == 201, res.text
    return res.json()


# -- Schema migration ---------------------------------------------------------------------------------------------


def test_an_old_database_upgrades_in_place(tmp_path):
    db = tmp_path / "projects.db"
    now = time.time()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, "
                     "description TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL)")
        conn.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, user_id TEXT NOT NULL, "
                     "subject TEXT NOT NULL, subject_norm TEXT NOT NULL, relation TEXT NOT NULL, object TEXT NOT NULL, "
                     "object_norm TEXT NOT NULL, value TEXT, valid_from REAL NOT NULL, invalid_at REAL, recorded_at REAL "
                     "NOT NULL, last_accessed REAL, source_json TEXT NOT NULL DEFAULT '{}', confidence REAL NOT NULL "
                     "DEFAULT 0.7, verified INTEGER NOT NULL DEFAULT 0, tags_json TEXT NOT NULL DEFAULT '[]', "
                     "superseded_by TEXT, invalidation_reason TEXT)")
        conn.execute("INSERT INTO projects VALUES ('prj_old000000000001', 'alice', 'Old', '', ?, ?)", (now, now))
        for fid, verified in (("fct_00000000000000a1", 1), ("fct_00000000000000a2", 0)):
            conn.execute("INSERT INTO facts (id, project_id, user_id, subject, subject_norm, relation, object, "
                         "object_norm, valid_from, recorded_at, verified) VALUES (?, 'prj_old000000000001', 'alice', "
                         "?, ?, 'property', 'x', 'x', ?, ?, ?)", (fid, fid, fid, now, now, verified))
    store = ProjectStore(str(tmp_path))
    project = store.get_project("prj_old000000000001", "alice")
    assert project["role"] == "owner" and project["member_count"] == 1 and project["owner_id"] == "alice"
    assert project["instructions"] == "" and project["pending_review_count"] == 1
    statuses = {f["id"]: f["review_status"] for f in store.list_facts("prj_old000000000001", "alice")}
    assert statuses == {"fct_00000000000000a1": "approved", "fct_00000000000000a2": "pending"}
    ProjectStore(str(tmp_path))  # re-opening is idempotent
    assert store.list_members("prj_old000000000001", "alice") == [
        {"user_id": "alice", "role": "owner", "added_at": project["created_at"], "added_by": "alice"}]


def test_the_activity_log_is_capped(tmp_path):
    store = ProjectStore(str(tmp_path))
    pid = store.create_project("alice", "p")["id"]
    for i in range(ACTIVITY_CAP + 20):
        store.log_event(pid, "alice", "run.completed", "thread", f"t{i}")
    events = store.list_activity(pid, "alice", limit=500)
    assert events[0]["target_id"] == f"t{ACTIVITY_CAP + 19}"
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity WHERE project_id = ?", (pid,)).fetchone()[0] == ACTIVITY_CAP


# -- Projects and roles -------------------------------------------------------------------------------------------


def test_project_object_matches_the_contract(client):
    p = _project(client)
    assert set(p) >= {"id", "name", "description", "instructions", "icon", "color", "owner_id", "role", "member_count",
                      "fact_count", "invalid_fact_count", "pending_review_count", "file_count", "created_at",
                      "updated_at"}
    assert (p["owner_id"], p["role"], p["icon"], p["instructions"]) == ("alice", "owner", "🧪", "Use SI units.")
    listed = client.get("/api/projects", headers=ALICE).json()["projects"]
    assert [x["id"] for x in listed] == [p["id"]]


def test_roles_403_and_non_members_404(client):
    pid = _project(client)["id"]
    # A non-member never learns the project exists.
    for method, path, body in (("get", "", None), ("patch", "", {"name": "x"}), ("delete", "", None),
                               ("get", "/members", None), ("get", "/memory", None), ("get", "/activity", None),
                               ("get", "/files", None)):
        res = client.request(method.upper(), f"/api/projects/{pid}{path}", json=body, headers=BOB)
        assert res.status_code == 404, (method, path, res.status_code)
    assert client.post(f"/api/projects/{pid}/members", json={"user_id": "bob", "role": "viewer"}, headers=ALICE).status_code == 201
    shared = client.get("/api/projects", headers=BOB).json()["projects"]
    assert shared[0]["role"] == "viewer" and shared[0]["owner_id"] == "alice"
    # A viewer reads but cannot write.
    assert client.get(f"/api/projects/{pid}", headers=BOB).status_code == 200
    assert client.patch(f"/api/projects/{pid}", json={"name": "x"}, headers=BOB).status_code == 403
    assert client.post(f"/api/projects/{pid}/memory", json={"subject": "a", "relation": "b", "object": "c"},
                       headers=BOB).status_code == 403
    assert client.delete(f"/api/projects/{pid}", headers=BOB).status_code == 403
    # An editor writes settings, but members and deletion stay the owner's.
    assert client.patch(f"/api/projects/{pid}/members/bob", json={"role": "editor"}, headers=ALICE).status_code == 200
    assert client.patch(f"/api/projects/{pid}", json={"instructions": "Cite Roark."}, headers=BOB).json()["instructions"] == "Cite Roark."
    assert client.post(f"/api/projects/{pid}/members", json={"user_id": "carol", "role": "viewer"}, headers=BOB).status_code == 403
    assert client.delete(f"/api/projects/{pid}", headers=BOB).status_code == 403
    assert client.delete(f"/api/projects/{pid}", headers=ALICE).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=BOB).status_code == 404


def test_members_add_change_leave_and_owner_rules(client):
    pid = _project(client)["id"]
    url = f"/api/projects/{pid}/members"
    assert client.post(url, json={"user_id": "bob", "role": "editor"}, headers=ALICE).status_code == 201
    assert client.post(url, json={"user_id": "bob", "role": "viewer"}, headers=ALICE).status_code == 409
    assert client.post(url, json={"user_id": "carol", "role": "owner"}, headers=ALICE).status_code == 422
    assert client.post(url, json={"user_id": "carol", "role": "viewer"}, headers=ALICE).status_code == 201
    members = client.get(url, headers=CAROL).json()["members"]
    assert [(m["user_id"], m["role"]) for m in members] == [("alice", "owner"), ("bob", "editor"), ("carol", "viewer")]
    assert members[1]["added_by"] == "alice"
    assert client.delete(f"{url}/bob", headers=CAROL).status_code == 403  # only the owner removes others
    assert client.delete(f"{url}/carol", headers=CAROL).status_code == 200  # anyone may leave
    assert client.delete(f"{url}/alice", headers=ALICE).status_code == 409  # the owner cannot leave
    assert client.patch(f"{url}/alice", json={"role": "viewer"}, headers=ALICE).status_code == 409
    assert client.delete(f"{url}/nobody", headers=ALICE).status_code == 404
    assert client.get(f"/api/projects/{pid}", headers=CAROL).status_code == 404


# -- Files --------------------------------------------------------------------------------------------------------


def _upload(user: str, text: str = "t,x\n0,1\n1,2\n") -> str:
    from tribos.datasets.models import DatasetProvenanceIn
    from tribos.datasets.store import get_dataset_store

    record = asyncio.run(get_dataset_store().create_from_stream(user, [text.encode()], "m.csv", DatasetProvenanceIn()))
    return record.id


def test_files_must_be_the_callers_own(client):
    pid = _project(client)["id"]
    client.post(f"/api/projects/{pid}/members", json={"user_id": "bob", "role": "viewer"}, headers=ALICE)
    mine, theirs = _upload("alice"), _upload("bob")
    assert client.post(f"/api/projects/{pid}/files", json={"dataset_id": theirs}, headers=ALICE).status_code == 404
    res = client.post(f"/api/projects/{pid}/files", json={"dataset_id": mine}, headers=ALICE)
    assert res.status_code == 201 and res.json()["name"] == "m.csv" and res.json()["kind"] == "table"
    assert client.post(f"/api/projects/{pid}/files", json={"dataset_id": theirs}, headers=BOB).status_code == 403
    files = client.get(f"/api/projects/{pid}/files", headers=BOB).json()["files"]
    assert [f["dataset_id"] for f in files] == [mine] and files[0]["added_by"] == "alice"
    assert client.get(f"/api/projects/{pid}", headers=ALICE).json()["file_count"] == 1
    assert client.delete(f"/api/projects/{pid}/files/{mine}", headers=BOB).status_code == 403
    assert client.delete(f"/api/projects/{pid}/files/{mine}", headers=ALICE).status_code == 200


# -- Memory review, history, activity -----------------------------------------------------------------------------


def test_review_history_and_activity(client):
    from tribos.utils.memory.project_store import get_project_store

    pid = _project(client)["id"]
    client.post(f"/api/projects/{pid}/members", json={"user_id": "bob", "role": "editor"}, headers=ALICE)
    store = get_project_store()
    # Facts written by a run start pending.
    ops = store.upsert_facts(pid, "alice", [FactInput("beam", "property", "tip deflection", value="3.05 mm"),
                                            FactInput("beam", "material", "S355")])["ops"]
    run_fact = ops[0]["fact_id"]
    pending = client.get(f"/api/projects/{pid}/memory?review_status=pending", headers=BOB).json()["facts"]
    assert {f["id"] for f in pending} == {o["fact_id"] for o in ops}
    assert client.get(f"/api/projects/{pid}", headers=ALICE).json()["pending_review_count"] == 2
    # A fact added by hand starts approved.
    added = client.post(f"/api/projects/{pid}/memory", json={"subject": "beam", "relation": "length", "object": "2 m",
                                                              "note": "from the drawing"}, headers=BOB).json()
    assert added["review_status"] == "approved" and added["reviewed_by"] == "bob" and added["review_note"] == "from the drawing"
    # Approve one, reject the other: the rejected fact is invalidated and never recalled.
    approve = client.post(f"/api/projects/{pid}/memory/{run_fact}/review", json={"decision": "approve", "note": "ok"},
                          headers=BOB).json()
    assert approve["review_status"] == "approved" and approve["reviewed_by"] == "bob"
    rejected = client.post(f"/api/projects/{pid}/memory/{ops[1]['fact_id']}/review",
                           json={"decision": "reject", "note": "wrong grade"}, headers=ALICE).json()
    assert rejected["review_status"] == "rejected" and rejected["invalid_at"] is not None
    recalled = store.recall(pid, "alice", "beam material S355", entities=["beam"])
    assert ops[1]["fact_id"] not in {f["id"] for f in recalled}
    assert [f["id"] for f in client.get(f"/api/projects/{pid}/memory?review_status=rejected",
                                        headers=ALICE).json()["facts"]] == [ops[1]["fact_id"]]
    # Editing makes a new version; the history lists both, oldest first.
    edited = client.patch(f"/api/projects/{pid}/memory/{run_fact}", json={"value": "3.10 mm"}, headers=ALICE).json()
    history = client.get(f"/api/projects/{pid}/memory/{edited['id']}/history", headers=BOB).json()["versions"]
    assert [v["id"] for v in history] == [run_fact, edited["id"]] and history[0]["superseded_by"] == edited["id"]
    assert client.get(f"/api/projects/{pid}/memory/{run_fact}/history", headers=BOB).json()["versions"] == history
    actions = [e["action"] for e in client.get(f"/api/projects/{pid}/activity?limit=50", headers=BOB).json()["events"]]
    assert actions[:5] == ["fact.edited", "fact.rejected", "fact.approved", "fact.added", "fact.added"]
    assert "project.created" in actions and "member.added" in actions
    event = client.get(f"/api/projects/{pid}/activity", headers=BOB).json()["events"][0]
    assert set(event) == {"id", "at", "actor", "action", "target_type", "target_id", "summary"}


# -- Runs ---------------------------------------------------------------------------------------------------------


def test_runs_get_the_instructions_and_the_project_files(monkeypatch, tmp_path):
    from tests.agentic_fakes import collect_events, make_agentic_orchestrator
    from tribos.agentic import config as agent_config
    from tribos.datasets.store import reset_dataset_store
    from tribos.utils.memory.project_store import get_project_store

    monkeypatch.setenv("TRIBOS_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("TRIBOS_UPLOAD_ROOT", str(tmp_path / "uploads"))
    reset_dataset_store()
    store = get_project_store()
    pid = store.create_project("bob", "Beam lab", instructions="Always answer in SI units and cite Roark.")["id"]
    store.add_member(pid, "bob", "alice", "editor")
    shared = _upload("bob")
    store.add_file(pid, "bob", shared, "m.csv", "table", 12)
    orch, _calls, llm = make_agentic_orchestrator(monkeypatch, tmp_path)
    res, _ = asyncio.run(collect_events(orch, query="What is the deflection of my beam?", thread_id="t10",
                                        user_id="alice", framework=agent_config.AGENTIC, project_id=pid))
    prompts = " ".join(system + user for phase, system, user in llm.calls if phase == "synthesis")
    assert "project_instructions" in prompts and "cite Roark" in prompts  # escaped inside <prior_memory>
    attachments = [a["id"] for a in (res.query_context or {}).get("attachments") or []]
    assert shared in attachments  # bob's file reaches alice's run through membership
    assert store.list_activity(pid, "bob")[0]["action"] == "run.completed"
    # A stranger's run gets neither the instructions nor the files.
    res2, _ = asyncio.run(collect_events(orch, query="What is the deflection of my beam?", thread_id="t11",
                                         user_id="carol", framework=agent_config.AGENTIC, project_id=pid))
    assert shared not in [a["id"] for a in (res2.query_context or {}).get("attachments") or []]
    reset_dataset_store()
