"""A quantity restated at another parameter value is not a contradiction; a bare restatement with a new value is."""

from __future__ import annotations

from tribos.verify.math_claims import audit_answer

QUESTION = "A damped oscillator obeys x'' + c x' + k x = 0 with x(0) = 1, x'(0) = 0, k = 4."
HEAD = r"""## Summary
The constrained minimum settling time is at $c^* = 2.0$ with $T \approx 4.04$.

### Settling time
Settling time $T(c)$ = last $t$ with $|x| > 0.02$.

"""


def _failed(answer: str) -> list[str]:
    return [c.text for c in audit_answer(answer, QUESTION).claims if c.status == "failed"]


def test_the_same_quantity_at_another_parameter_value_is_not_contradicted():
    answer = HEAD + r"By contrast $c = 0.4$ gives overshoot $\approx 0.729$ and $T \approx 19.19$, hence infeasible."
    assert not any("19.19" in t for t in _failed(answer))


def test_a_bare_restatement_with_a_different_value_is_still_caught():
    plain = r"""## Summary
The settling time is $T \approx 4.04$.

### Later
So the settling time is $T \approx 5.2$.
"""
    assert any("5.2" in t for t in _failed(plain))


MULTI_PART_Q = (r"Let f(x,y) = x^3 - 3x + y^2 on the domain -2 \leq x \leq 2. 3. Find the minimum of f subject to "
                "the constraint x + y = 1.")
PART_ONE = r"""### 1. Find all critical points of f in the domain
Critical points: a saddle at $x = -0.902087$, $y = 1.208524$ and a minimum at $x = 0.909$, $y = 0.614603$.

### 3. Find the minimum of f subject to the constraint x + y = 1
On $x + y = 1$, put $y = 1 - x$. Minimizing $g$ gives

$$x = 0.8150365866364419,$$

hence from the constraint

$$y = 1 - x = """


def test_a_symbol_reused_in_another_numbered_part_is_not_contradicted():
    answer = PART_ONE + "0.18496341336355815,$$\n\nso $x + y = 1$.\n"
    assert [c.text for c in audit_answer(answer, MULTI_PART_Q).claims if c.status == "failed"] == []


def test_a_quantity_restated_with_another_value_inside_one_part_is_still_caught():
    # x and y name points (never bound), but a quantity of the part restated with another value is a contradiction.
    answer = PART_ONE + "0.18496341336355815,$$\n\nThe multiplier is $m = 2.5$; so $m = 3.1$.\n"
    assert any("3.1" in c.text for c in audit_answer(answer, MULTI_PART_Q).claims if c.status == "failed")


def test_a_term_of_an_equation_is_not_a_given_value():
    from tribos.verify.result_record import given_values

    assert given_values("subject to the constraint x + y = 1") == {}
    assert {k: v["value"] for k, v in given_values("with m = 2 kg and k = 50 N/m").items()} == {"m": 2.0, "k": 50.0}


G_Q = "Let f(x,y) = x^3 - 3x + y^2 - 2y + sin(xy). 1. Plot f. 2. Find the minimum of f subject to x + y = 1."
G_ANSWER = r"""### 2. Find the minimum of f subject to x + y = 1
Put $y = 1 - x$. Then

$$g(x) = x^3 + x^2 - 3x - 1 + \sin(x(1-x)).$$

The right endpoint value is

$$g(2) \approx VALUE.$$
"""


def test_x_times_a_bracket_is_a_product_so_g_is_checked():
    claims = audit_answer(G_ANSWER.replace("VALUE", "4.090703"), G_Q).claims
    assert any(c.status == "passed" and "g(2)" in c.text for c in claims)  # x(1-x) read as x*(1-x), not a function x
    wrong = audit_answer(G_ANSWER.replace("VALUE", "3.5"), G_Q).claims
    assert any(c.status == "failed" and "g(2)" in c.text for c in wrong)
