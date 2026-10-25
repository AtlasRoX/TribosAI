"""tribos.sources.keys: one canonical spelling for every evidence key."""

from tribos.sources.keys import (
    normalize_evidence_key,
    passage_keys,
    passage_source_key,
    same_document,
)


def test_arxiv_forms_normalise_to_one_key():
    for raw in ("arXiv:2312.04511", "[ARXIV:2312.04511v2]", "https://arxiv.org/abs/2312.04511", "arxiv: 2312.04511"):
        assert normalize_evidence_key(raw) == "ARXIV:2312.04511", raw


def test_doi_is_lower_case_and_loses_its_resolver():
    assert normalize_evidence_key("doi:10.1103/PhysRev.47.777") == "DOI:10.1103/physrev.47.777"
    assert normalize_evidence_key("https://doi.org/10.1103/PhysRev.47.777") == "DOI:10.1103/physrev.47.777"


def test_zbmath_and_local_keys():
    assert normalize_evidence_key("Zbl:1234.5678") == "ZBL:1234.5678"
    assert normalize_evidence_key("zbmath:1234.5678") == "ZBL:1234.5678"
    assert normalize_evidence_key("passage:p3") == "passage:p3"
    assert normalize_evidence_key("tool:axiom_solve") == "tool:axiom_solve"
    assert normalize_evidence_key("not a key") == "not a key"


def test_passage_keys_and_source_key():
    p = {"arxiv_id": "2312.04511v1", "doi": "10.48550/ARXIV.2312.04511"}
    assert passage_keys(p) == ["ARXIV:2312.04511", "DOI:10.48550/arxiv.2312.04511"]
    assert passage_source_key(p) == "ARXIV:2312.04511"
    assert passage_source_key({}, fallback="passage:x") == "passage:x"
    assert passage_source_key({"paper_id": "2401.00001"}) == "ARXIV:2401.00001"


def test_same_document_matches_any_identifier():
    p = {"arxiv_id": "2312.04511", "doi": "10.1/x"}
    assert same_document(p, "DOI:10.1/X")
    assert same_document("arXiv:2312.04511v3", p)
    assert not same_document(p, "ARXIV:9999.00001")


def test_paper_id_ads_bibcode_and_mr_prefix():
    assert passage_keys({"paper_id": "649def34f8be52c8b66281af98ae884c09aef38b"}) == []
    assert passage_keys({"paper_id": "hep-th/9901001v2"}) == ["ARXIV:hep-th/9901001"]
    assert passage_keys({"ads_bibcode": "2019ApJ...882L..24M"}) == ["ADS:2019ApJ...882L..24M"]
    assert normalize_evidence_key("arXiv:math.AG/0601001v2") == "ARXIV:math.AG/0601001"
    assert normalize_evidence_key("MR:MR1234567") == normalize_evidence_key("MR:1234567") == "MR:1234567"
def test_zbl_prefix_inside_value():
    assert normalize_evidence_key("ZBL:Zbl 1234.56789") == "ZBL:1234.56789"
