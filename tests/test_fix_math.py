"""Regression tests for the MATH fixes: SEC-2/SUP-1 (one safe expression parser), BRK-6, LOG-12..LOG-16 and polish."""

from __future__ import annotations

import pytest
import sympy as sp

from tribos.axiom import engine as E
from tribos.axiom.safe_expr import normalize_math_text, parse_math, validate_code
from tribos.dynamis.engine import dynamis_optimize
from tribos.evals.scoring import parse_sympy_expr
from tribos.physis.units import check_dimensional_homogeneity, convert_units
from tribos.verify.latex_math import parse_latex
from tribos.verify.math_claims import audit_answer

# -- SEC-2 / SUP-1: the safe parser ----------------------------------------------------------------------------------

FW_DUNDER_CLASS = "＿＿ｃｌａｓｓ＿＿"  # "__class__" in full-width letters

ESCAPE_PAYLOADS = [
    "Integer(1)._" + FW_DUNDER_CLASS[1:],  # the reproduced bypass: "Integer(1)._＿ｃｌａｓｓ＿＿"
    "Integer(1)." + FW_DUNDER_CLASS,
    "Integer(1)." + FW_DUNDER_CLASS + ".__mro__",
    "Integer(1).__class__.__mro__[1].__subclasses__()",
    "x.__class__",
    "\U0001d5eb.＿＿class＿＿",  # mathematical sans-serif x, full-width underscores
    "\U0001d5f4\U0001d5f2\U0001d601\U0001d5ee\U0001d601\U0001d601\U0001d5ff(x, 'y')",  # "getattr" in math sans-serif
    "\U0001d5f2\U0001d603\U0001d5ee\U0001d5f9('1')",  # "eval"
    "ｉｍｐｏｒｔ",  # "import" in full-width
    "__import__('os').getcwd()",
    "getattr(Integer(1), 'real')",
    "(lambda: 1)()",
    "lambda: 1",
    "[c for c in (1, 2)]",
    "{1: 2}",
    "{1}",
    "f'{x}'",
    "x if y else z",
    "(1).real",  # attribute access the blacklist does not see
    "x.diff(x)",
    "x.subs(x, 1)",
    "Integer(1).func",
    "Integer(1).args[0]",
    "Ｉｎｔｅｇｅｒ(1).ｆｕｎｃ",  # "Integer(1).func", full-width
    "sin('x')",  # a string handed to SymPy would be sympified with builtins
    "Matrix('x')",
    "Function('f')('x')",
    "Symbol('x', real='y')",
    "Float('1; x')",
    "x̳",  # a combining mark that survives NFKC
    "‗class‗",
]


@pytest.mark.parametrize("payload", ESCAPE_PAYLOADS)
def test_escape_payloads_are_refused(payload):
    with pytest.raises(ValueError):
        E.safe_parse_expr(payload)


@pytest.mark.parametrize("payload", ["Integer(1)._" + FW_DUNDER_CLASS[1:], "(1).real", "x.diff(x)"])
def test_escape_payloads_are_refused_by_every_tool_route(payload):
    with pytest.raises(ValueError):
        E.axiom_simplify(payload)
    with pytest.raises(ValueError):
        dynamis_optimize(payload, ["x"])
    assert parse_sympy_expr(payload) is None  # eval scoring of model answers


def test_generated_code_is_validated_against_the_allowlist():
    env = dict(E._SAFE_LOCALS)
    for code in ("Integer(1).real", "Symbol('x').__class__", "(lambda: 1)()", "unknown_name", "_hidden",
                 "sin('x')", "Symbol('__x__')", "Integer(1)(2)"):
        with pytest.raises(ValueError):
            validate_code(code, env)
    validate_code("sin(Symbol('x'))**Integer(2)", env)


def test_normalisation_spells_greek_and_refuses_other_unicode():
    assert normalize_math_text("ω t + α") == "omega t + alpha"
    assert normalize_math_text("\U0001d5ee + ﬁ") == "a + fi"  # math sans-serif a, the "fi" ligature
    assert normalize_math_text("2 − x") == "2 - x"
    with pytest.raises(ValueError):
        normalize_math_text("x + 一")


x, y = sp.symbols("x y")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sin(x)**2", sp.sin(x) ** 2),
        ("exp(-x)", sp.exp(-x)),
        ("Matrix([[1, 2], [x, 3]])", sp.Matrix([[1, 2], [x, 3]])),
        ("Piecewise((x, x > 0), (0, True))", sp.Piecewise((x, x > 0), (0, True))),
        ("Derivative(x**2, x)", sp.Derivative(x**2, x)),
        ("sqrt(8)", 2 * sp.sqrt(2)),
        ("factorial(5)", sp.Integer(120)),
        ("binomial(5, 2)", sp.Integer(10)),
        ("2x y", 2 * x * y),  # implicit multiplication
        ("x^2 + 1", x**2 + 1),
        ("alpha + omega*theta", sp.Symbol("alpha") + sp.Symbol("omega") * sp.Symbol("theta")),
        ("ω t", sp.Symbol("omega") * sp.Symbol("t")),
        ("λ + 1", sp.Symbol("lamda") + 1),
        ("Integral(x, (x, 0, 1))", sp.Integral(x, (x, 0, 1))),
        ("Eq(x, 2)", sp.Eq(x, 2)),
        ("Rational(1, 2) + 1.5e-3", sp.Rational(1, 2) + sp.Float("1.5e-3")),
        ("Max(x, 2)", sp.Max(x, 2)),
        ("_x + 1", sp.Symbol("_x") + 1),
    ],
)
def test_ordinary_math_still_parses(text, expected):
    assert E.safe_parse_expr(text) == expected


def test_assumptions_functions_and_local_names_still_parse():
    k = E.safe_parse_expr("Symbol('k', positive=True)")
    assert k.is_positive
    f = sp.Function("f")
    assert E.safe_parse_expr("f(x) + 1", local_dict={"f": f}) == f(x) + 1
    assert E.safe_parse_expr("x + 1", assumptions={"x": "real"}).free_symbols.pop().is_real
    assert parse_math("sin(x)") == sp.sin(x)
    assert parse_sympy_expr("x^2 + 2x + 1") == x**2 + 2 * x + 1


# -- BRK-6 -----------------------------------------------------------------------------------------------------------


def test_non_identity_latex_uses_neq_not_a_newline():
    res = E.axiom_verify_identity("sin(x)", "cos(x)")
    assert res["equivalent"] is False
    assert r"\neq" in res["latex"] and "\n" not in res["latex"]


# -- LOG-12 / LOG-13: LaTeX inverse trig and log bases ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tex", "expected"),
    [
        (r"\tan^{-1}(1)", sp.pi / 4),
        (r"\sin^{-1}(1)", sp.pi / 2),
        (r"\cos^{-1}(0)", sp.pi / 2),
        (r"\sec^{-1}(2)", sp.pi / 3),
        (r"\csc^{-1}(2)", sp.pi / 6),
        (r"\cot^{-1}(1)", sp.pi / 4),
        (r"\sin^{2}(x)", sp.sin(x) ** 2),
        (r"\sin^2 x", sp.sin(x) ** 2),
        (r"\log_{10} 1000", sp.Integer(3)),
        (r"\log_2 8", sp.Integer(3)),
        (r"\log_{2}(8)", sp.Integer(3)),
        (r"\ln(x)", sp.log(x)),
    ],
)
def test_latex_inverse_trig_and_log_bases(tex, expected):
    assert sp.simplify(parse_latex(tex) - expected) == 0


def _statuses(md: str) -> list[str]:
    return [c.status for c in audit_answer(md).claims]


@pytest.mark.parametrize(
    ("md", "status"),
    [
        (r"$\tan^{-1}(1)=\frac{\pi}{4}$", "passed"),
        (r"$\sin^{-1}(1) = \frac{\pi}{2}$", "passed"),
        (r"$\tan^{-1}(1) = 1$", "failed"),
        (r"$\log_{10} 1000 = 3$", "passed"),
        (r"$\log_2 8 = 3$", "passed"),
        (r"$\log_2 8 = 4$", "failed"),
        (r"$\log 1000 = 3$", "inconclusive"),  # true for base 10, false for base e: the base was never stated
        (r"$\log 1000 = 5$", "failed"),  # false under both conventions
        (r"$\ln 1000 = 3$", "failed"),  # \ln is always natural
    ],
)
def test_audit_inverse_trig_and_log_conventions(md, status):
    assert _statuses(md) == [status]


# -- LOG-14: single-equation dimensional check -----------------------------------------------------------------------


def test_variables_are_not_read_as_units():
    with pytest.raises(ValueError, match="variables"):
        convert_units(check_equation="F = m*a")
    with pytest.raises(ValueError, match="variables"):
        check_dimensional_homogeneity("F = m*a")
    assert convert_units(check_equation="1 N = 1 kg*m/s^2")["equation_homogeneous"] is True
    assert convert_units(check_equation="1 J = 1 kg*m/s")["equation_homogeneous"] is False
    assert convert_units(check_equation="N = kg*m/s^2; F = m*a")["equation_homogeneous"] is True


# -- LOG-15: inequality constraints ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("constraint", "point"),
    [
        ({"type": "ineq", "expr": "x + y >= 1"}, (0.5, 0.5)),
        ({"expr": "x + y ≥ 1"}, (0.5, 0.5)),
        ({"expr": "1 <= x + y"}, (0.5, 0.5)),
        ({"expr": "x + y > 1"}, (0.5, 0.5)),
        ({"expr": "x + y == 4"}, (2.0, 2.0)),
        ({"type": "eq", "expr": "x + y = 4"}, (2.0, 2.0)),
    ],
)
def test_optimize_reads_relational_constraints(constraint, point):
    res = dynamis_optimize("x^2 + y^2", ["x", "y"], initial_guess={"x": 2.0, "y": 2.0}, constraints=[constraint])
    assert res["converged"] is True
    assert (res["optimal_point"]["x"], res["optimal_point"]["y"]) == pytest.approx(point, abs=1e-5)


def test_optimize_upper_bound_constraint():
    res = dynamis_optimize("(x - 3)^2", ["x"], constraints=[{"expr": "x <= 1"}])
    assert res["optimal_point"]["x"] == pytest.approx(1.0, abs=1e-5)


# -- LOG-16 ----------------------------------------------------------------------------------------------------------


def test_unevaluable_value_is_not_assumed_real():
    assert E._is_real_value(sp.Symbol("z")) is False  # complex() fails: unknown is not real
    assert E._is_real_value(sp.Symbol("r", real=True)) is True
    assert E._is_real_value(sp.Integer(2)) is True
    assert E._is_real_value(sp.I) is False
    res = E.axiom_solve("x^3 - 1", "x", domain="real")
    assert [str(s["x"]) for s in res["solutions"]] == ["1"]


# -- polish ----------------------------------------------------------------------------------------------------------


def test_units_all_lists_the_public_api():
    import tribos.physis.units as units

    for name in ("check_dimensional_homogeneity", "check_equation_set", "convert_units", "get_unit_registry"):
        assert name in units.__all__


def test_markdown_keeps_math_spans_literal():
    from tribos.export.markdown_blocks import parse_blocks, render_html, runs_text

    md = r"Here $a*b*c$ and $x_1 + y_1$, then $$\sum_i a_i * b_i$$ and *real emphasis*; costs $5 and $10."
    html = render_html(md)
    assert "$a*b*c$" in html and "$x_1 + y_1$" in html and r"$$\sum_i a_i * b_i$$" in html
    assert html.count("<em>") == 1 and "$5 and $10" in html
    assert r"$\{x\}$" in render_html(r"the set $\{x\}$")  # backslash escapes kept for the equation renderer
    runs = parse_blocks(md)[0].runs
    assert "$a*b*c$" in runs_text(runs)


def test_abstention_case_is_not_biomedical():
    from tribos.axiom.math_eval import BENCHMARK

    case = next(c for c in BENCHMARK if c.id == "no-03")
    assert "gene" not in case.question and "= 4" in case.question


def test_literal_power_towers_are_refused_before_evaluation():
    import time

    import pytest

    from tribos.axiom.engine import safe_parse_expr

    for payload in ("9^9^9^9", "9**9**9**9", "10**10**10", "2**(10**8)", "(-7)**10**9"):
        start = time.perf_counter()
        with pytest.raises(ValueError, match="too large"):
            safe_parse_expr(payload)
        assert time.perf_counter() - start < 2, payload
    # ordinary powers still evaluate exactly
    assert safe_parse_expr("2**100") == 2**100
    assert safe_parse_expr("9**9**2") == 9**81
    assert str(safe_parse_expr("x**10**3")) == "x**1000"
    assert safe_parse_expr("1**10**100") == 1
