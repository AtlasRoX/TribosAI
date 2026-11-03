"""Unit tests for Archivon (tribos.archivon & tribos.extensions.archivon)."""

from __future__ import annotations

import httpx
import pytest

from tribos.archivon import (
    ArchivonClients,
    ArchivonEngine,
    CrossrefIntegrityClient,
    build_arxiv_search_query,
    extract_literature_ids,
    extract_typed_literature_ids,
    grade_article,
    normalize_doi,
    normalize_literature_id,
    parse_arxiv_atom,
    reconstruct_openalex_abstract,
    split_arxiv_version,
    strip_literature_ids,
    summarize_grades,
    summary_phrases,
)
from tribos.tools.registry import ToolRegistry, register_default_tools

SAMPLE_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <updated>2023-08-02T00:41:18Z</updated>
    <title>Attention Is All You Need</title>
    <summary>We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <arxiv:primary_category term="cs.CL"/>
    <category term="cs.CL"/>
    <category term="cs.LG"/>
    <arxiv:doi>10.48550/arXiv.1706.03762</arxiv:doi>
    <link title="pdf" href="http://arxiv.org/pdf/1706.03762v7" rel="related" type="application/pdf"/>
  </entry>
</feed>
"""


def test_identifiers_extraction_and_normalization() -> None:
    text = (
        "Compare arXiv:1706.03762v5 and hep-th/9905111v2 with DOI 10.1103/PhysRevLett.116.061102, "
        "Zbl 1456.35001, MR2123456, and bibcode 2016PhRvL.116f1102A."
    )
    ids = extract_literature_ids(text)
    assert "arXiv:1706.03762" in ids
    assert "arXiv:hep-th/9905111" in ids
    assert "10.1103/physrevlett.116.061102" in ids
    assert "Zbl 1456.35001" in ids
    assert "MR2123456" in ids
    assert "2016PhRvL.116f1102A" in ids

    typed = extract_typed_literature_ids(text)
    assert typed["arxiv"] == ["1706.03762", "hep-th/9905111"]
    assert typed["doi"] == ["10.1103/physrevlett.116.061102"]
    assert typed["zbl"] == ["1456.35001"]
    assert typed["mr"] == ["MR2123456"]

    assert split_arxiv_version("arXiv:2301.12345v3") == ("2301.12345", "v3")
    assert normalize_doi("https://doi.org/10.1038/Nature12373.") == "10.1038/nature12373"
    assert normalize_literature_id("W2741809807") == ("openalex", "W2741809807")

    stripped = strip_literature_ids("Analyze arXiv:1706.03762v5 convergence rate")
    assert "1706.03762" not in stripped
    assert "convergence rate" in stripped


def test_arxiv_query_builder_and_atom_parser() -> None:
    q = build_arxiv_search_query("Navier-Stokes global regularity", categories=["math.AP", "math-ph"])
    assert "all:" in q
    assert "cat:math.AP" in q
    assert "cat:math-ph" in q

    entries = parse_arxiv_atom(SAMPLE_ARXIV_ATOM)
    assert len(entries) == 1
    art = entries[0]
    assert art["arxiv_id"] == "1706.03762"
    assert art["arxiv_version"] == "v7"
    assert art["year"] == "2017"
    assert art["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert art["primary_category"] == "cs.CL"
    assert art["categories"] == ["cs.CL", "cs.LG"]
    assert art["pdf_url"] == "http://arxiv.org/pdf/1706.03762v7"


def test_reconstruct_openalex_abstract() -> None:
    inv = {"We": [0], "prove": [1], "a": [2, 5], "global": [3], "theorem": [4], "bound.": [6]}
    reconstructed = reconstruct_openalex_abstract(inv)
    assert reconstructed == "We prove a global theorem a bound."
    assert reconstruct_openalex_abstract(None) == ""


def test_grading_stem_study_types() -> None:
    thm = grade_article(
        {
            "title": "Theorem and Proof of Global Regularity for Nonlinear PDEs",
            "abstract": "We prove Theorem 1.1 establishing global existence and uniqueness.",
            "doi": "10.4007/annals.2024.199.1.1",
            "zbl_id": "1520.35012",
            "msc": ["35Q30", "76D05"],
            "venue": "Annals of Mathematics",
            "source": "zbmath",
        }
    )
    assert thm.study_type == "theorem_proof"
    assert thm.confidence == "high"
    assert not thm.is_preprint

    exp = grade_article(
        {
            "title": "Experimental Observation of Gravitational Waves from a Binary Black Hole Merger",
            "abstract": "We report experimental measurements from the LIGO detectors.",
            "doi": "10.1103/physrevlett.116.061102",
            "venue": "Physical Review Letters",
            "source": "crossref",
        }
    )
    assert exp.study_type == "experimental_measurement"

    sim = grade_article(
        {
            "title": "Direct Numerical Simulation of Isotropic Turbulence at High Reynolds Number",
            "abstract": "We perform finite-element and Monte Carlo numerical simulations on a 4096^3 grid.",
            "doi": "10.1017/jfm.2023.100",
            "venue": "Journal of Fluid Mechanics",
            "source": "openalex",
        }
    )
    assert sim.study_type == "numerical_simulation"

    prep = grade_article(
        {
            "title": "A Note on Spectral Bounds",
            "abstract": "We discuss spectral properties.",
            "arxiv_id": "2401.00001",
            "categories": ["math.SP"],
            "source": "arxiv",
        }
    )
    assert prep.is_preprint
    assert prep.study_type == "preprint"

    summary = summarize_grades([thm, exp, sim, prep])
    assert summary["total"] == 4
    phrases = summary_phrases(summary)
    assert any("proof" in p for p in phrases)


@pytest.mark.asyncio
async def test_archivon_engine_search_deduplication_and_integrity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "export.arxiv.org" in url:
            return httpx.Response(200, text=SAMPLE_ARXIV_ATOM)
        if "api.semanticscholar.org/graph/v1/paper/search" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "paperId": "s2_transformer",
                            "title": "Attention Is All You Need",
                            "abstract": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
                            "year": 2017,
                            "venue": "NeurIPS",
                            "citationCount": 95000,
                            "influentialCitationCount": 14000,
                            "externalIds": {"ArXiv": "1706.03762", "DOI": "10.5555/3295222.3295349"},
                            "authors": [{"name": "Ashish Vaswani"}],
                            "publicationTypes": ["Conference"],
                        },
                        {
                            # On the question's subject: an off-topic retraction is not reported at all (a retracted
                            # breast-cancer paper matched by "classify" and "task" is no warning the reader needs).
                            "paperId": "s2_retracted",
                            "title": "Retracted Transformer Attention Approximation Claim",
                            "abstract": "A transformer attention approximation claim.",
                            "year": 2023,
                            "venue": "Nature",
                            "citationCount": 100,
                            "externalIds": {"DOI": "10.1038/s41586-023-99999-x"},
                            "authors": [{"name": "R. Author"}],
                        },
                    ]
                },
            )
        if "api.openalex.org/works" in url:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W2963403868",
                            "doi": "https://doi.org/10.5555/3295222.3295349",
                            "title": "Attention Is All You Need",
                            "publication_year": 2017,
                            "cited_by_count": 96000,
                            "type": "proceedings-article",
                            "ids": {"arxiv": "https://arxiv.org/abs/1706.03762"},
                            "abstract_inverted_index": {
                                "Transformer": [0],
                                "attention": [1],
                                "architecture.": [2],
                            },
                        }
                    ]
                },
            )
        if "api.zbmath.org" in url:
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "id": 7500123,
                            "zbl_id": "1480.68123",
                            "title": {"title": "Theorem and Proof of Transformer Approximation Capacity"},
                            "year": "2022",
                            "contributors": {"authors": [{"name": "Smith, J."}]},
                            "msc": [{"code": "68T07", "text": "Artificial neural networks"}],
                            "editorial_contributions": [
                                {"text": "We prove a universal approximation theorem for attention networks."}
                            ],
                        }
                    ]
                },
            )
        if "api.crossref.org/works" in url:
            # Integrity check or Crossref search
            if "filter=" in url:
                return httpx.Response(
                    200,
                    json={
                        "message": {
                            "items": [
                                {
                                    "DOI": "10.1038/s41586-023-99999-x",
                                    "title": ["Retracted Superconductivity Claim"],
                                    "update-to": [
                                        {
                                            "type": "retraction",
                                            "DOI": "10.1038/s41586-023-99999-x",
                                            "label": "Retraction",
                                            "updated": {"date-parts": [[2023, 11, 7]]},
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                )
            return httpx.Response(200, json={"message": {"items": []}})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)
    clients = ArchivonClients(transport=transport)
    integrity_client = CrossrefIntegrityClient(transport=transport)
    engine = ArchivonEngine(clients=clients, integrity_client=integrity_client)

    res = await engine.literature_search("Transformer attention approximation", max_results=10)
    assert res["total_found"] == 2
    assert len(res["excluded_articles"]) == 1
    assert res["excluded_articles"][0]["excluded_reason"] == "retracted"
    assert "1706.03762" in res["canonical_ids"]["arxiv_ids"]
    assert "1480.68123" in res["canonical_ids"]["zbl_ids"]
    #ADS was not configured so it should be reported in skipped_sources
    assert "ads" in res["provenance"]["skipped_sources"]


@pytest.mark.asyncio
async def test_archivon_ads_when_token_configured_and_registry_tools() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.adsabs.harvard.edu" in url:
            assert request.headers.get("Authorization") == "Bearer test-ads-token"
            return httpx.Response(
                200,
                json={
                    "response": {
                        "docs": [
                            {
                                "bibcode": "2016PhRvL.116f1102A",
                                "title": ["Observation of Gravitational Waves from a Binary Black Hole Merger"],
                                "abstract": "LIGO experimental detection of gravitational waves.",
                                "author": ["Abbott, B. P."],
                                "year": "2016",
                                "doi": ["10.1103/PhysRevLett.116.061102"],
                                "pub": "Physical Review Letters",
                                "citation_count": 12000,
                                "doctype": "article",
                            }
                        ]
                    }
                },
            )
        if "api.semanticscholar.org/ recommendations" in url or "recommendations/v1/papers" in url:
            return httpx.Response(
                200,
                json={
                    "recommendedPapers": [
                        {
                            "paperId": "s2_rec_1",
                            "title": "GW151226: Observation of Gravitational Waves",
                            "year": 2016,
                            "venue": "PRL",
                            "citationCount": 4000,
                            "externalIds": {"DOI": "10.1103/PhysRevLett.116.241103"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"message": {"items": []}})

    transport = httpx.MockTransport(handler)
    clients = ArchivonClients(ads_api_token="test-ads-token", transport=transport)
    engine = ArchivonEngine(
        clients=clients,
        integrity_client=CrossrefIntegrityClient(transport=transport),
    )

    ads_res = await engine.literature_search("gravitational waves", sources=["ads"])
    assert ads_res["total_found"] == 1
    assert ads_res["passages"][0]["bibcode"] == "2016PhRvL.116f1102A"

    rec_res = await engine.recommend_papers(["10.1103/PhysRevLett.116.061102"], limit=5)
    assert rec_res["count"] == 1
    assert rec_res["recommendations"][0]["paper_id"] == "s2_rec_1"

    reg = ToolRegistry()
    register_default_tools(reg)
    assert reg.get_entry("archivon_literature_search") is not None
    assert reg.get_entry("archivon_paper_details") is not None
    assert reg.get_entry("archivon_recommend") is not None
