"""AUDIT-101: a model-declared axiom must never yield "formally verified".

The formal checker once found axioms by a name allowlist in the source: `axiom choice : 2 + 2 = 5`, `@[simp] axiom`
and a namespaced `propext` all compiled and were certified. Now every axiom declaration is refused, and the kernel's
own record (`#print axioms`) must show only Lean's three standard axioms.
"""

from __future__ import annotations

import pytest

from tribos.verify.formal import runner

FALSE_BY_AXIOM = {
    "trusted-looking name": "axiom choice : (2:Nat) + 2 = 5\ntheorem bad : (2:Nat) + 2 = 5 := choice\n",
    "attribute before axiom": "@[simp] axiom helper : (2:Nat) + 2 = 5\ntheorem bad : (2:Nat) + 2 = 5 := helper\n",
    "namespaced propext": "namespace Foo\naxiom propext : (2:Nat) + 2 = 5\nend Foo\ntheorem bad : (2:Nat) + 2 = 5 := Foo.propext\n",
    "two commands on a line": "def x := 1 axiom sneaky : (2:Nat) + 2 = 5\ntheorem bad : (2:Nat) + 2 = 5 := sneaky\n",
}


@pytest.mark.parametrize("case", sorted(FALSE_BY_AXIOM))
def test_every_axiom_declaration_is_reported_whatever_its_name(case):
    assert any(u.startswith("axiom ") for u in runner.uses_unproved(FALSE_BY_AXIOM[case]))


def test_the_word_axioms_in_a_print_command_or_comment_is_not_a_declaration():
    assert runner.uses_unproved("-- this proof uses no axiom\ntheorem t : 1 = 1 := rfl\n#print axioms t\n") == []


def test_theorems_are_found_with_their_namespaces_and_examples_are_named_for_the_audit():
    code = ("namespace A.B\ntheorem t1 : 1 = 1 := rfl\nsection S\nlemma t2 : 2 = 2 := rfl\nend S\nend A.B\n"
            "theorem _root_.t3 : 3 = 3 := rfl\n@[simp] private theorem t4 : True := trivial\nexample : 4 = 4 := rfl\n")
    checked, audited = runner.with_axiom_audit(code)
    assert [n for n, _ in audited] == ["A.B.t1", "A.B.t2", "t3", "t4", "tribos_example_1"]
    lines = checked.splitlines()
    for name, line in audited:
        assert lines[line - 1] == f"#print axioms {name}"
    assert "theorem tribos_example_1 : 4 = 4 := rfl" in checked


def test_axiom_reports_count_only_after_the_nonce_marker_and_a_missing_report_is_none():
    audited = [("t", 10), ("u", 11)]
    out = "TRIBOS_AXIOM_AUDIT n1\n't' depends on axioms: [propext, Classical.choice]\n"
    assert runner.axiom_reports(out, audited, "n1") == {"t": ["propext", "Classical.choice"], "u": None}
    assert runner.axiom_reports("TRIBOS_AXIOM_AUDIT n1\n't' does not depend on any axioms\n", [("t", 10)], "n1") == {"t": []}
    # A report the model's own code printed before the marker (or without knowing the nonce) does not count.
    spoof = "'t' does not depend on any axioms\nTRIBOS_AXIOM_AUDIT other\n't' does not depend on any axioms\n"
    assert runner.axiom_reports(spoof, [("t", 10)], "n1") == {"t": None}


def test_exit_before_the_audit_leaves_the_proof_unaudited():
    checked, audited = runner.with_axiom_audit("#exit\ntheorem t : 1 = 1 := rfl\n", "n1")
    assert audited and runner.axiom_reports("", audited, "n1") == {"t": None}


def _real_lean() -> bool:
    return runner.find_lean() is not None and not str(runner.find_lean()["argv"][-1]).endswith(".py")


@pytest.mark.skipif(not _real_lean(), reason="no Lean installation configured")
@pytest.mark.parametrize("case", sorted(FALSE_BY_AXIOM))
def test_lean_never_verifies_a_false_theorem_proved_from_an_axiom(case):
    runner.clear_cache()
    result = runner.check_lean(FALSE_BY_AXIOM[case])
    assert result["status"] == "failed", result


@pytest.mark.skipif(not _real_lean(), reason="no Lean installation configured")
def test_lean_verifies_a_true_theorem_and_reports_its_standard_axioms():
    runner.clear_cache()
    result = runner.check_lean("theorem good : (2:Nat) + 2 = 4 := by decide\n"
                               "theorem uses_choice (p : Prop) : p ∨ ¬p := Classical.em p\n")
    assert result["status"] == "verified", result
    assert set(result["axioms"]["uses_choice"]) <= runner.STANDARD_AXIOMS and result["axioms"]["good"] is not None
