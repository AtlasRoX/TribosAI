from __future__ import annotations

import pytest

from tribos.agents.entity_lexicon import (
    extract_declared_variables,
    find_offline_quantities,
)
from tribos.agents.evidence_need import _given_quantities, assess_evidence_need
from tribos.agents.query_planner import _offline_stem_entities
from tribos.physis.units import (
    check_dimensional_homogeneity,
    convert_units,
)
from tribos.verify.math_claims import _physical_question


def test_f11_s08_reproduction_declared_m_not_tagged_as_length():
    """F11 Reproduction: In S08 (run_9465302a2375466e), query declares m a nonnegative integer.
    5m and 2m must NOT be tagged as LENGTH quantities in quantity extractor, stem entities, or reader metadata."""
    q = (
        "Two independent domains: prove/disprove 5m+4>2m+1 for every nonnegative integer m, "
        "requiring any witness in-domain; solve same inequality over reals."
    )
    # 1. Declared variable recognized
    declared = extract_declared_variables(q)
    assert "m" in declared

    # 2. find_offline_quantities returns no bogus length quantities
    quants = find_offline_quantities(q)
    assert quants == [], f"Expected empty quantities, got: {quants}"

    # 3. _offline_stem_entities has no quantity of type length
    stem = _offline_stem_entities(q, [])
    length_entities = [e for e in stem if e.ids.get("physical_type") == "length" or e.type == "length"]
    assert length_entities == [], f"Expected no length entities, got: {length_entities}"

    # 4. _given_quantities is 0 and _physical_question is False
    assert _given_quantities(q) == 0
    assert not _physical_question(q)

    # 5. Evidence need is closed computation, not physical or empirical
    need = assess_evidence_need(q)
    assert need.kind == "closed_computation"
    assert need.skip_retrieval


def test_f11_spaced_multiplication_with_declared_variable():
    """Spaced multiplication or expressions with declared variable m must not be tagged as length."""
    q1 = "prove/disprove 5 m + 4 > 2 m + 1 for every nonnegative integer m"
    quants1 = find_offline_quantities(q1)
    assert quants1 == [], f"Expected empty quantities for spaced 5 m, got: {quants1}"

    q2 = "for every nonnegative integer m, evaluate 5*m + 4"
    quants2 = find_offline_quantities(q2)
    assert quants2 == [], f"Expected empty quantities for 5*m, got: {quants2}"


def test_f11_genuine_metre_measurements_retain_units_and_dimensions():
    """Genuine metre measurements must retain physical length category and values."""
    q1 = "A pendulum of length 2m with mass 5kg"
    quants1 = find_offline_quantities(q1)
    len_q = next((item for item in quants1 if item["units"] == "m"), None)
    mass_q = next((item for item in quants1 if item["units"] == "kg"), None)

    assert len_q is not None, f"Expected 2m to be extracted, got: {quants1}"
    assert len_q["value"] == 2.0
    assert len_q["physical_type"] == "length"
    assert not len_q.get("ambiguous", False)

    assert mass_q is not None
    assert mass_q["value"] == 5.0
    assert mass_q["physical_type"] == "mass"

    # Spaced measurement with physical context
    q2 = "A copper wire 5 m long has resistance 0.2 Ohm"
    quants2 = find_offline_quantities(q2)
    wire_len = next((item for item in quants2 if item["units"] == "m"), None)
    assert wire_len is not None
    assert wire_len["value"] == 5.0
    assert wire_len["physical_type"] == "length"

    # Motion measurement
    q3 = "A car moves 50m in 5s"
    quants3 = find_offline_quantities(q3)
    dist_q = next((item for item in quants3 if item["units"] == "m"), None)
    time_q = next((item for item in quants3 if item["units"] == "s"), None)
    assert dist_q is not None and dist_q["physical_type"] == "length"
    assert time_q is not None and time_q["physical_type"] == "time"


def test_f11_other_ambiguous_symbols_distinguish_variables_from_units():
    """Ambiguous unit tokens like s (seconds), g (grams), h (hours), N (newtons), Pa (pascals)
    must be distinguished when declared as variables."""
    # Variable s
    q_s = "Declare s a nonnegative integer; prove 5s+4>2s+1"
    assert "s" in extract_declared_variables(q_s)
    assert find_offline_quantities(q_s) == []

    # Variable g (e.g. generator of a cyclic group)
    q_g = "Let g be a generator of group G. Compute 3g + 2g"
    assert "g" in extract_declared_variables(q_g)
    assert find_offline_quantities(q_g) == []

    # Contrast genuine grams
    q_g_phys = "Dissolve 50 g of NaCl in 500 mL water"
    g_phys = find_offline_quantities(q_g_phys)
    mass_item = next((item for item in g_phys if item["units"] == "g"), None)
    assert mass_item is not None
    assert mass_item["physical_type"] == "mass"

    # Parameter Pa
    q_pa = "Let Pa be a parameter in 2Pa + 1 = 5"
    assert "Pa" in extract_declared_variables(q_pa)
    assert find_offline_quantities(q_pa) == []

    # Contrast genuine pascals
    q_pa_phys = "The chamber pressure is 1000 Pa"
    pa_phys = find_offline_quantities(q_pa_phys)
    pa_item = next((item for item in pa_phys if item["units"] == "Pa"), None)
    assert pa_item is not None
    assert pa_item["physical_type"] == "pressure"

    # Variable W
    q_w = "Let W be a subspace in 2W + 1"
    assert "W" in extract_declared_variables(q_w)
    assert find_offline_quantities(q_w) == []

    # Contrast genuine watts
    q_w_phys = "A motor delivers 500 W of power"
    w_phys = find_offline_quantities(q_w_phys)
    w_item = next((item for item in w_phys if item["units"] == "W"), None)
    assert w_item is not None
    assert w_item["physical_type"] == "power"

    # Variable N
    q_n = "For integer N > 0, sum 2N terms"
    assert "N" in extract_declared_variables(q_n)
    assert find_offline_quantities(q_n) == []

    # Contrast genuine Newtons
    q_n_phys = "Apply horizontal force of 20 N"
    n_phys = find_offline_quantities(q_n_phys)
    force_item = next((item for item in n_phys if item["units"] == "N"), None)
    assert force_item is not None
    assert force_item["physical_type"] == "force"


def test_f11_mixed_algebra_plus_physical_quantities():
    """Questions with both declared variables in algebraic expressions AND real physical quantities
    must accurately partition algebra from physical measurements."""
    q = (
        "Let s be a real parameter. If a particle of mass 2 kg travels 50 m in 10 s "
        "with acceleration a(s) = 4s + 1, find its velocity."
    )
    assert "s" in extract_declared_variables(q)
    quants = find_offline_quantities(q)

    # 4s must NOT be extracted as 4 seconds
    s_quants = [item for item in quants if item["units"] == "s"]
    assert len(s_quants) == 1
    assert s_quants[0]["value"] == 10.0
    assert s_quants[0]["physical_type"] == "time"

    # 2 kg must be extracted as mass
    kg_quants = [item for item in quants if item["units"] == "kg"]
    assert len(kg_quants) == 1
    assert kg_quants[0]["value"] == 2.0
    assert kg_quants[0]["physical_type"] == "mass"

    # 50 m must be extracted as length
    m_quants = [item for item in quants if item["units"] == "m"]
    assert len(m_quants) == 1
    assert m_quants[0]["value"] == 50.0
    assert m_quants[0]["physical_type"] == "length"


def test_f11_truly_ambiguous_state_retained():
    """Where context truly does not resolve whether a token is a variable or unit,
    an ambiguous state is retained rather than guessing."""
    q = "What is 5m?"
    quants = find_offline_quantities(q)
    assert len(quants) == 1
    hit = quants[0]
    assert hit["ambiguous"] is True
    assert hit["physical_type"] == "ambiguous"
    assert "variable m" in hit["ambiguous_with"]
    assert "length (m)" in hit["ambiguous_with"]

    # Also reflected in stem entities
    stem = _offline_stem_entities(q, [])
    assert len(stem) == 1
    entity = stem[0]
    assert entity.ids.get("physical_type") == "ambiguous"
    assert "variable m" in entity.ambiguous_with


def test_f11_dimensional_analysis_homogeneity_no_regression():
    """Dimensional analysis and unit conversion functions continue to operate without regression."""
    res_valid = check_dimensional_homogeneity("1 N = 1 kg*m/s^2")
    assert res_valid["equation_homogeneous"] is True
    assert res_valid["compatible"] is True

    res_invalid = check_dimensional_homogeneity("1 J = 1 kg*m/s")
    assert res_invalid["equation_homogeneous"] is False

    # Equation with variables is still refused by convert_units
    with pytest.raises(ValueError, match="variables"):
        convert_units(check_equation="F = m*a")

    with pytest.raises(ValueError, match="variables"):
        check_dimensional_homogeneity("F = m*a")
