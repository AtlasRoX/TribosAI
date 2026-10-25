"""Regression tests for the LIT fixes: Archivon error reporting and wiring, STEM citations, memory, project facts."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

import httpx
import pytest

from tribos.agents.citations import build_citation_map
from tribos.archivon.clients import ArchivonClients, SourceError
from tribos.archivon.engine import ArchivonEngine
from tribos.extensions import archivon as ext
from tribos.tools import reliability
from tribos.tools.registry import ErrorType, ToolResult
from tribos.utils.memory.project_store import FactInput, ProjectStore
from tribos.utils.memory.research_memory import (
    SUBJECT_KEYS,
    MemoryType,
    ResearchMemoryEngine,
    VerificationStatus,
    _clean_subject,
    computed_result_class,
)

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
 <entry><id>http://arxiv.org/abs/2312.04511v2</id><title>Lyapunov exponents of the Lorenz attractor</title>
  <summary>We compute Lyapunov exponents of the Lorenz attractor with high accuracy.</summary>
  <published>2023-12-07T00:00:00Z</published><author><name>A. Author</name></author></entry>
 <entry><id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need for the Lorenz attractor</title>
  <summary>Transformer attention for the Lorenz attractor Lyapunov exponents.</summary>
  <published>2017-06-12T00:00:00Z</published><author><name>A. Vaswani</name></author></entry>
</feed>"""


class _FailingClients:
    """Every source raises, as an outage does."""

    def __getattr__(self, name: str) -> Any:
        async def fail(*_a: Any, **_k: Any) -> Any:
            raise SourceError(name, "transport_error", f"{name} ConnectError: unreachable")
        return fail


def _engine(clients: Any) -> ArchivonEngine:
    engine = ArchivonEngine.__new__(ArchivonEngine)
    engine.clients = clients
    engine.check_integrity = False
    return engine


def test_brk1_brk2_recommend_runs_and_errors_are_upstream(monkeypatch):
    calls: list[Any] = []

    class _Engine:
        async def recommend_papers(self, seed_identifiers: Any, limit: int = 5) -> dict[str, Any]:
            calls.append(seed_identifiers)
            return {"count": 0, "recommendations": [], "canonical_ids": {}, "limitations": []}

        async def literature_search(self, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("boom")

    monkeypatch.setattr(ext, "get_archivon_engine", lambda: _Engine())
    res = asyncio.run(ext.execute_archivon_recommend(paper_ids=["arXiv:2312.04511", "10.1103/x"], limit=3))
    assert res.success and calls == [["arXiv:2312.04511", "10.1103/x"]]
    bad = asyncio.run(ext.execute_archivon_literature_search(query="q"))
    assert not bad.success and bad.error_type == ErrorType.UPSTREAM_API_ERROR


def test_recommend_merges_every_seed_and_drops_the_seeds():
    class _Clients:
        async def recommend_semantic_scholar(self, ident: str, limit: int = 5):
            n = ident.rsplit(".", 1)[-1]
            return [{"title": f"Related paper number {n} on chaotic flows", "doi": f"10.1/r{n}", "paperId": n},
                    {"title": "Shared related paper on chaotic flows", "doi": "10.1/shared"},
                    {"title": "The seed itself about chaotic flows", "doi": "10.1103/seed.1"}], None

    out = asyncio.run(_engine(_Clients()).recommend_papers(["10.1103/seed.1", "10.1103/seed.2"], limit=10))
    dois = [r["doi"] for r in out["recommendations"]]
    assert {"10.1/r1", "10.1/r2", "10.1/shared"} <= set(dois) and dois.count("10.1/shared") == 1
    assert "10.1103/seed.1" not in dois and out["seed_identifiers"] == ["10.1103/seed.1", "10.1103/seed.2"]


def test_log6_total_outage_is_a_failure_not_an_empty_success(monkeypatch):
    data = asyncio.run(_engine(_FailingClients()).literature_search("Lorenz attractor", sources=["arxiv", "crossref"]))
    assert data["all_sources_failed"] and data["partial"] and set(data["sources_failed"]) == {"arxiv", "crossref"}
    assert data["retrieval"]["sources_queried"] == []
    assert {s["status"] for s in data["source_status"]} == {"error"}
    assert data["source_status"][0]["error_type"] == "transport_error"

    monkeypatch.setattr(ext, "get_archivon_engine", lambda: _engine(_FailingClients()))
    res = asyncio.run(ext.execute_archivon_literature_search(query="Lorenz attractor", sources=["arxiv"]))
    assert not res.success and res.error_type == ErrorType.UPSTREAM_API_ERROR and "ConnectError" in res.error
    assert reliability._outcome(res) == "failure"


def test_log6_one_failed_source_is_partial_and_never_cached():
    class _Clients(_FailingClients):
        async def search_crossref(self, *_a: Any, **_k: Any):
            return [{"title": "Lorenz attractor Lyapunov exponents computed", "doi": "10.1/ok", "source": "crossref",
                     "summary": "Lorenz attractor Lyapunov exponents"}]

    data = asyncio.run(_engine(_Clients()).literature_search("Lorenz attractor", sources=["arxiv", "crossref"]))
    assert data["partial"] and not data["all_sources_failed"] and data["sources_failed"] == ["arxiv"]
    assert data["retrieval"]["sources_queried"] == ["crossref"]
    assert reliability._looks_partial(data)
    ok = ToolResult(success=True, tool_name="archivon_literature_search", data=data)
    assert reliability._outcome(ok) == "success"
    all_failed = ToolResult(success=True, tool_name="x", data={"source_status": [{"status": "error"}]})
    assert reliability._outcome(all_failed) == "failure"


def test_client_http_errors_raise_source_errors():
    transport = httpx.MockTransport(lambda r: httpx.Response(429, json={}))
    with pytest.raises(SourceError) as exc:
        asyncio.run(ArchivonClients(transport=transport).search_openalex("x"))
    assert exc.value.error_type == "rate_limited"


def test_log8_planned_arguments_reach_the_engine(monkeypatch):
    seen: dict[str, Any] = {}

    class _Engine:
        async def literature_search(self, **kw: Any) -> dict[str, Any]:
            seen.update(kw)
            return {"ranked_passages": [], "canonical_ids": {}, "provenance": {}}

    monkeypatch.setattr(ext, "get_archivon_engine", lambda: _Engine())
    inp = ext.ArchivonLiteratureSearchInput(query="q", pinned_ids=["arXiv:2312.04511"], keywords=["lyapunov"],
                                            year_from=2010, search_queries=[{"query": "Lorenz chaos"}], max_articles=4)
    asyncio.run(ext.execute_archivon_literature_search(**inp.model_dump()))
    assert seen["pinned_ids"] == ["arXiv:2312.04511"] and seen["keywords"] == ["lyapunov"]
    assert seen["year_from"] == 2010 and seen["search_queries"] == [{"query": "Lorenz chaos"}]
    assert seen["max_results"] == 4


def test_log8_extra_queries_run_and_only_run_queries_are_reported():
    queries: list[tuple[str, str]] = []

    class _Clients:
        async def search_arxiv(self, q: str, **_k: Any):
            queries.append(("arxiv", q))
            return []

        async def search_openalex(self, q: str, **_k: Any):
            queries.append(("openalex", q))
            return []

    planned = [{"query": "Lorenz attractor"}, {"query": 'TITLE_ABS:"lorenz"'}, {"query": "Lyapunov exponent chaos"},
               {"query": "strange attractor"}, {"query": "never run"}]
    data = asyncio.run(_engine(_Clients()).literature_search("Lorenz attractor", sources=["arxiv", "openalex"],
                                                              search_queries=planned))
    assert data["retrieval"]["queries"] == ["Lorenz attractor", "Lyapunov exponent chaos", "strange attractor"]
    assert ("arxiv", "Lyapunov exponent chaos") not in queries  # arXiv's rate limit: topical query only
    assert ("openalex", "strange attractor") in queries and not any(q == "never run" for _, q in queries)


def test_log9_pinned_arxiv_ids_are_fetched_in_one_request():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if "export.arxiv.org" in str(request.url):
            return httpx.Response(200, text=ARXIV_ATOM)
        return httpx.Response(200, json={"message": {"items": []}, "data": [], "results": []})

    engine = ArchivonEngine(clients=ArchivonClients(transport=httpx.MockTransport(handler)), check_integrity=False)
    data = asyncio.run(engine.literature_search("Lorenz attractor", sources=["crossref"],
                                                pinned_ids=["arXiv:2312.04511", "arXiv:1706.03762"]))
    id_list_calls = [u for u in requests if "id_list" in u]
    assert len(id_list_calls) == 1 and "2312.04511" in id_list_calls[0] and "1706.03762" in id_list_calls[0]
    assert {"2312.04511", "1706.03762"} <= set(data["canonical_ids"]["arxiv_ids"])


def test_log7_arxiv_citation_gets_an_entry():
    passage = {"passage_id": "arch_1", "arxiv_id": "2312.04511", "title": "Lyapunov exponents of the Lorenz attractor",
               "passage_text": "The largest Lyapunov exponent of the Lorenz attractor is about 0.9056.",
               "year": "2023", "authors": "A. Author", "source": "arxiv"}
    tools = {"archivon": ToolResult(success=True, tool_name="archivon_literature_search",
                                    data={"ranked_passages": [passage]})}
    answer = "The largest Lyapunov exponent of the Lorenz attractor is about 0.9056 (arXiv:2312.04511v2)."
    report = {"verified_identifiers": ["ARXIV:2312.04511"], "defects": [], "claim_support": []}
    cmap = build_citation_map(answer, tools, report)
    entry = cmap["entries"]["ARXIV:2312.04511"]
    assert entry["url"] == "https://arxiv.org/abs/2312.04511" and entry["type"] == "arxiv" and entry["passages"]
    assert cmap["aliases"].get("ARXIV:2312.04511v2") == "ARXIV:2312.04511"  # the renderer keeps the version


def test_log7_zbl_ads_and_mr_entries():
    passages = [
        {"passage_id": "a", "zbl_id": "1234.56789", "passage_text": "A fixed point theorem in metric spaces.", "title": "T"},
        {"passage_id": "b", "bibcode": "2016PhRvL.116f1102A", "passage_text": "Gravitational waves observed.", "title": "G"},
    ]
    tools = {"archivon": ToolResult(success=True, tool_name="x", data={"ranked_passages": passages})}
    answer = "A fixed point theorem (Zbl 1234.56789). Waves were observed (2016PhRvL.116f1102A)."
    cmap = build_citation_map(answer, tools, {"verified_identifiers": ["ZBL:1234.56789"], "defects": []})
    assert cmap["entries"]["ZBL:1234.56789"]["url"] == "https://zbmath.org/?q=an:1234.56789"
    ads = cmap["entries"]["ADS:2016PhRvL.116f1102A"]  # the key keeps the case-sensitive bibcode, like the web key
    assert ads["url"].endswith("/abs/2016PhRvL.116f1102A")


def test_log27_stem_subject_keys_are_kept():
    assert set(SUBJECT_KEYS) >= {"concept", "equation", "system", "material", "quantity", "constant", "gene"}
    assert _clean_subject({"system": "Lorenz system", "quantity": "t = 50 s", "bogus": "x"}) == {
        "system": "Lorenz system", "quantity": "t = 50 s"}


def test_log27_follow_up_subject_is_the_system(tmp_path):
    mem = ResearchMemoryEngine(storage_dir=str(tmp_path))
    mem.record_active_subject("u", "t", {"system": "lorenz"})
    assert mem.get_context_package("t", user_id="u").resolved_subject == "lorenz"


def test_log28_stem_entities_and_computed_results(tmp_path):
    ents = ResearchMemoryEngine.extract_entities("We simulated the Lorenz attractor using Planck constant values.")
    assert ents["systems"] and ents["constants"]
    assert computed_result_class("physis", {"canonical_id": "NIST:CODATA", "constants": [{"name": "h"}]}, False)[0] \
        == VerificationStatus.VERIFIED_EMPIRICAL
    assert computed_result_class("axiom", {"status": "verified"}, False)[0] == VerificationStatus.VERIFIED_EMPIRICAL
    assert computed_result_class("dynamis", {}, True)[0] == VerificationStatus.PROVISIONAL
    assert computed_result_class("archivon", {}, True) is None

    mem = ResearchMemoryEngine(storage_dir=str(tmp_path))
    sim = {"model_name": "lorenz", "summary": {"x": {"final": 1.0}}}
    mem.consolidate_turn_sync("t", "q", "r", {
        "physis": {"canonical_id": "NIST:CODATA", "constants": [{"name": "Planck constant", "value": 6.62607015e-34}]},
        "dynamis": sim, "vivarix": sim,  # the alias key is the same result object
    }, user_id="u")
    with mem._connect() as conn:
        rows = conn.execute("SELECT memory_type, content, verification_status FROM memory_nodes WHERE memory_type = ?",
                            (MemoryType.COMPUTED_RESULT.value,)).fetchall()
    assert len(rows) == 2 and not any("Literature" in r["content"] for r in rows)
    pkg = mem.get_context_package("t", user_id="u")
    assert any("CODATA" in a for a in pkg.computed_artifacts)  # recalled as verified
    assert not any("[Provisional Literature]" in h for h in pkg.active_hypotheses)


def test_log30_duplicates_are_merged_and_then_prevented(tmp_path):
    store = ProjectStore(str(tmp_path))
    pid = store.create_project("alice", "p")["id"]
    store.upsert_facts(pid, "alice", [FactInput("Si", "property", "band gap", value="1.12 eV")])
    # Simulate an old database: drop the index and write the duplicate a race used to produce.
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DROP INDEX uq_fact_current")
        conn.execute("INSERT INTO facts SELECT 'fct_0000000000000001', project_id, user_id, subject, subject_norm, "
                     "relation, object, object_norm, value, valid_from, invalid_at, recorded_at, last_accessed, "
                     "source_json, confidence, verified, tags_json, superseded_by, invalidation_reason FROM facts")
    store = ProjectStore(str(tmp_path))  # re-open: migration merges, then adds the index
    assert len(store.list_facts(pid, "alice")) == 1
    with sqlite3.connect(store.db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO facts SELECT 'fct_0000000000000002', project_id, user_id, subject, subject_norm, "
                     "relation, object, object_norm, value, valid_from, invalid_at, recorded_at, last_accessed, "
                     "source_json, confidence, verified, tags_json, superseded_by, invalidation_reason FROM facts "
                     "WHERE invalid_at IS NULL")
    # A changed value supersedes the old one under the unique index (invalidate first, then add).
    out = store.upsert_facts(pid, "alice", [FactInput("Si", "property", "band gap", value="1.11 eV")])
    assert out["invalidated"] == 1 and [f["value"] for f in store.list_facts(pid, "alice")] == ["1.11 eV"]


def test_edit_fact_verifying_drops_the_unverified_tag(tmp_path):
    store = ProjectStore(str(tmp_path))
    pid = store.create_project("alice", "p")["id"]
    fid = store.upsert_facts(pid, "alice", [FactInput("h", "physical_constant", "h", value="6.6e-34")])["ops"][0]["fact_id"]
    assert "unverified" in store.get_fact(pid, fid, "alice")["tags"]
    edited = store.edit_fact(pid, fid, "alice", verified=True)
    assert edited["verified"] and "unverified" not in edited["tags"]
