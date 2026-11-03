"""Provenance creation does not imply consent or a need to call unrelated external services."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.parametrize("search", [False, True])
def test_creating_a_run_recorder_does_not_start_unrequested_network_probes(monkeypatch, search):
    from tribos.provenance.run_manifest import RunRecorder
    import tribos.provenance.source_versions as source_versions

    async def forbidden_probe(*args, **kwargs):
        raise AssertionError("Recording a local computation must not query external source versions.")

    monkeypatch.setenv("TRIBOS_PROVENANCE_PROBES", "on")
    monkeypatch.setattr(source_versions, "get_source_versions", forbidden_probe)

    async def run():
        recorder = RunRecorder(query="local numerical calculation", thread_id="no-probe", model_name="none",
                               enable_web_search=search, user_id="offline", api_key_supplied=False)
        await asyncio.sleep(0)
        assert recorder._tasks == []
        assert recorder._source_versions == {}

    asyncio.run(run())
