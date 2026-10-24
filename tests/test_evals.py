"""The evaluation harness: case data, scorers, runner (with fakes), reports, gate and CLI. No network or keys."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tribos.evals import datasets, report, scoring
from tribos.evals.cli import main as cli_main
from tribos.evals.runner import Evaluator, RunConfig, load_results
from tribos.evals.schema import AnswerExpect, CaseResult, Check, EvalCase, RetrievalExpect

# ---------------------------------------------------------------------------------------------------------------
# Case data
# ---------------------------------------------------------------------------------------------------------------

def test_builtin_suites_load_and_cover_every_level():
    suites = {name: datasets.load_suite(name) for name in datasets.builtin_suites()}
    assert {"math", "physics", "engineering", "behavior", "golden"} <= set(suites)
    for domain in ("math", "physics", "engineering"):
        cases = suites[domain]
        assert len(cases) >= 12 and all(c.answer and c.reference for c in cases)
    assert len(suites["behavior"]) >= 15
    assert len(suites["golden"]) == 5
    all_ids = [c.id for cases in suites.values() for c in cases]
    assert len(all_ids) == len(set(all_ids))


def test_cases_reject_broken_patterns():
    with pytest.raises(ValueError, match="control character"):
        EvalCase(id="x", suite="s", query="q", answer={"must_mention": ["\x08evoke"]})
    with pytest.raises(ValueError, match="invalid regex"):
        EvalCase(id="x", suite="s", query="q", retrieval={"gold_title_patterns": ["(unclosed"]})


def test_sources_have_no_stray_control_characters():
    """A lost backslash turns a regex's \\b into a backspace, which silently never matches."""
    root = Path(__file__).resolve().parents[1]
    bad = [str(p.relative_to(root)) for d in ("tribos", "tests") for p in (root / d).rglob("*.py")
           if any(ch in p.read_text(encoding="utf-8", errors="ignore") for ch in ("\x08", "\x0b", "\x0c"))]
    assert not bad, bad


def test_select_filters_and_samples():
    cases = datasets.load_suite("math")
    assert [c.id for c in datasets.select(cases, ids=["math-gaussian"])] == ["math-gaussian-integral"]
    assert {c.category for c in datasets.select(cases, categories=["calculus"])} == {"calculus"}
    a = datasets.select(cases, limit=5, seed=3)
    assert len(a) == 5 and [c.id for c in a] == [c.id for c in datasets.select(cases, limit=5, seed=3)]


def test_external_loaders_read_cached_files(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBOS_EVAL_CACHE", str(tmp_path))
    (tmp_path / "math500_rows.json").write_text(json.dumps([
        {"unique_id": "test/algebra/1.json", "problem": "Solve x+1=3.", "solution": "x=2", "answer": "2", "subject": "Algebra", "level": 1}
    ]))
    (tmp_path / "gsm8k_rows.json").write_text(json.dumps([
        {"question": "2 + 3?", "answer": "Adding gives 5.\n#### 5"}
    ]))
    (tmp_path / "theoremqa_rows.json").write_text(json.dumps([
        {"id": "t1", "Question": "What is det(I_2)?", "Answer": 1.0, "Answer_type": "float", "field": "math"}
    ]))
    (tmp_path / "scibench_rows.json").write_text(json.dumps([
        {"problemid": "s1", "problem_text": "Find speed.", "answer_number": "9.81", "unit": "m/s", "source": "fund"}
    ]))
    (tmp_path / "phybench_rows.json").write_text(json.dumps([
        {"id": "p1", "content": "Oscillator frequency?", "answer": "sqrt(k/m)", "category": "mechanics"}
    ]))
    (tmp_path / "engdesign_rows.json").write_text(json.dumps([
        {"id": "e1", "question": "Design a cantilever beam.", "required_terms": ["bending"], "domain": "structural"}
    ]))
    (tmp_path / "ugphysics_rows.json").write_text(json.dumps([
        {"id": "u1", "problem": "Escape velocity?", "answer": "sqrt(2*G*M/R)", "subject": "Classical Mechanics"}
    ]))
    (tmp_path / "gpqa_rows.json").write_text(json.dumps([
        {"Record ID": "g1", "Question": "Which operator?", "Correct Answer": "Hamiltonian",
         "Incorrect Answer 1": "Lagrangian", "Incorrect Answer 2": "Jacobian", "Incorrect Answer 3": "Hessian",
         "Subdomain": "Quantum Mechanics"}
    ]))

    m500 = datasets.load_suite("math500")[0]
    assert m500.answer.answer_type == "symbolic" and m500.answer.symbolic_answer == "2"

    gsm = datasets.load_suite("gsm8k")[0]
    assert gsm.answer.answer_type == "numeric" and gsm.answer.numeric_answer == 5.0

    tqa = datasets.load_suite("theoremqa")[0]
    assert tqa.answer.answer_type == "numeric" and tqa.answer.numeric_answer == 1.0

    sci = datasets.load_suite("scibench")[0]
    assert sci.answer.numeric_answer == 9.81 and "m/s" in sci.query

    phy = datasets.load_suite("phybench")[0]
    assert phy.answer.symbolic_answer == "sqrt(k/m)"

    eng = datasets.load_suite("engdesign")[0]
    assert eng.answer.required_terms == ["bending"]

    with pytest.raises(ValueError, match="allow-noncommercial"):
        datasets.load_suite("ugphysics")
    ug = datasets.load_suite("ugphysics", allow_noncommercial=True)[0]
    assert ug.answer.symbolic_answer == "sqrt(2*G*M/R)"

    gpqa = datasets.load_suite("gpqa")[0]
    assert gpqa.answer.label == "Hamiltonian" and len(gpqa.answer.options) == 4


# ---------------------------------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------------------------------

def test_retrieval_scores_rank_recall_and_title_patterns():
    exp = RetrievalExpect(gold_pmids=["2", "9"], k=3)
    checks, m = scoring.retrieval_scores(exp, ["1", "2", "2", "3", "9"])
    assert checks[0].passed and m["first_gold_rank"] == 2 and m["rr"] == 0.5 and m["recall"] == 0.5  # 9 is rank 4 > k
    checks, m = scoring.retrieval_scores(RetrievalExpect(gold_pmids=["7"], gold_title_patterns=[r"\boscillator\b"]),
                                         ["1", "2"], titles=["Other", "Revisiting the damped oscillator"])
    assert checks[0].passed and m["first_gold_rank"] == 2 and m["recall"] == 0.0
    checks, m = scoring.retrieval_scores(RetrievalExpect(gold_arxiv_ids=["1807.09547"], k=5),
                                         pmids=["", ""], dois=["", ""], titles=["A", "B"],
                                         arxiv_ids=["2101.00001", "arXiv:1807.09547v2"])
    assert checks[0].passed and m["first_gold_rank"] == 2 and m["recall"] == 1.0
    checks, _ = scoring.retrieval_scores(RetrievalExpect(gold_pmids=["7"], required=False), ["1"])
    assert not checks[0].passed and not checks[0].required
    assert scoring.retrieval_scores(RetrievalExpect(), ["1"]) == ([], {"retrieved": 1})


def test_numeric_and_symbolic_equivalence_scoring():
    assert scoring.extract_boxed(r"Therefore the result is \boxed{\frac{\pi^2}{6}}.") == r"\frac{\pi^2}{6}"
    assert scoring.symbolic_equivalent("(x + 1)**2", "x**2 + 2*x + 1")
    assert scoring.symbolic_equivalent(r"\frac{\pi^2}{6}", "pi**2/6")
    assert scoring.symbolic_equivalent(r"\sqrt{\frac{2 G M}{R}}", "sqrt(2*G*M/R)")
    assert not scoring.symbolic_equivalent("x**2 + 1", "x**2 + 2")

    exp_num = AnswerExpect(answer_type="numeric", numeric_answer=159.155, numeric_rel_tol=0.01)
    checks, m = scoring.answer_checks(exp_num, {"response": r"The cutoff frequency is \boxed{159.2} Hz."})
    assert any(c.name == "answer.numeric" and c.passed for c in checks) and m["numeric_correct"] is True

    exp_sym = AnswerExpect(answer_type="symbolic", symbolic_answer="P*L**3/(3*E*I)")
    checks, m = scoring.answer_checks(exp_sym, {"response": r"Tip deflection is \boxed{\frac{P L^3}{3 E I}}."})
    assert any(c.name == "answer.symbolic" and c.passed for c in checks) and m["symbolic_correct"] is True


def test_abstention_and_refusal():
    assert scoring.abstained("No peer-reviewed evidence was found for ZX999.")
    assert scoring.abstained("ZX999 appears to be hypothetical.")
    assert not scoring.abstained("The Euler-Bernoulli buckling load is pi^2 E I / L^2.")
    assert scoring.opens_with_refusal("No relevant evidence was retrieved. Nothing more can be said.")
    assert not scoring.opens_with_refusal("Use the Routh-Hurwitz array. Evidence limitations: no experimental dataset was attached.")


def test_answer_checks():
    exp = AnswerExpect(must_mention=["omega_0", "zeta"], must_not_mention=[r"perpetual motion"], agents_include=["Archivon"],
                       agents_exclude=["Dynamis"], framework="authoritative-react-compiler", cite_gold=True, min_citations=1)
    obs = {"response": "Damped frequency depends on omega_0 and zeta (arXiv:1807.09547).", "agents": ["Archivon"], "verified": True,
           "framework": "authoritative-react-compiler", "citation_keys": ["arXiv:1807.09547"]}
    checks, m = scoring.answer_checks(exp, obs, ["1807.09547"])
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]
    assert m["gold_cited"] and m["unresolved_citations"] == 0
    bad = {**obs, "response": "This creates perpetual motion (arXiv:1111.11111).", "agents": ["Dynamis"], "verified": False}
    failed = {c.name for c in scoring.answer_checks(exp, bad, ["1807.09547"])[0] if not c.passed}
    assert {"answer.mentions", "answer.avoids", "answer.agent_ran", "answer.agent_skipped", "answer.verified", "answer.cites_gold"} <= failed


def test_label_heuristics_and_exact_answers():
    assert scoring.heuristic_yesno("Yes. The system is asymptotically stable.") == "yes"
    assert scoring.heuristic_yesno("**No** - it diverges.") == "no"
    assert scoring.heuristic_yesno("No retrieved evidence directly addresses this.") is None  # not a verdict
    assert scoring.heuristic_yesno("The evidence is mixed and inconclusive.") is None  # left to the model grader
    assert scoring.heuristic_yesno("Systems with X ...") is None
    opts = ["Hamiltonian", "Lagrangian", "Insufficient information to answer the question"]
    assert scoring.heuristic_choice("The generator of time translation is the Hamiltonian only.", opts) == "Hamiltonian"
    assert scoring.heuristic_choice("No evidence was found.", opts) == opts[2]
    checks, m = scoring.label_checks(AnswerExpect(label="yes"), "Yes")
    assert checks[0].passed and m["answered"]
    _, m = scoring.label_checks(AnswerExpect(label="A"), opts[2])
    assert not m["correct"] and not m["answered"]
    c, m = scoring.exact_checks(AnswerExpect(answer_type="list", exact=[["Euler", "Euler-Bernoulli"], ["Timoshenko"], ["Rayleigh"]]), "Timoshenko and Euler-Bernoulli")
    assert c[0].passed and m["list_recall"] == 0.667
    c, _ = scoring.exact_checks(AnswerExpect(answer_type="factoid", exact=[["Noether"]]), "It is Lagrange.")
    assert not c[0].passed


# ---------------------------------------------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------------------------------------------

def test_offline_plan_level_passes_every_builtin_case():
    """A routing regression test: every plan expectation that holds offline must pass."""
    cases = [c for name in ("math", "physics", "engineering", "behavior", "golden") for c in datasets.load_suite(name) if c.plan]
    results = asyncio.run(Evaluator(RunConfig(levels=["plan"])).run(cases))
    failures = [(r.case_id, [c.detail for c in r.checks if not c.passed]) for r in results if not r.passed and not r.skipped]
    assert not failures, failures


class _FakeMemory:
    def __init__(self) -> None:
        self.cleared: list[str] = []

    def clear_thread_memory(self, thread_id: str, user_id: Any = None) -> None:
        self.cleared.append(thread_id)


class _FakeOrchestrator:
    def __init__(self, response: str) -> None:
        self.response, self.memory, self.calls = response, _FakeMemory(), []

    async def execute_inquiry(self, query: str, **kw: Any) -> Any:
        self.calls.append((query, kw))
        return SimpleNamespace(
            response=self.response, framework_used="authoritative-react-compiler", selected_agents=["Archivon"],
            verification_report={"passed": True, "verification_score": 1.0, "defects": []},
            citations={"entries": {"arXiv:1807.09547": {"title": "Damped Oscillator", "journal": "Am. J. Phys.", "year": "2019"}}},
            run_manifest={"tool_calls": [{"tool_name": "archivon_literature_search", "output_digest": {"arxiv_ids": ["1807.09547"]}}]},
            query_context={"scope": "research"},
        )


class _FakeGrader:
    """Answers the label extractor and the judge with fixed JSON."""

    def __init__(self, choice: str) -> None:
        self.choice = choice

    async def ainvoke(self, messages: Any) -> Any:
        if "fixed options" in messages[0].content:
            return SimpleNamespace(content=json.dumps({"choice": self.choice}))
        return SimpleNamespace(content='{"correctness": 5, "grounding": 4, "completeness": 4, "calibration": 4, "clarity": 5, "overall": 4.4, "rationale": "ok"}')


def test_answer_level_runs_setup_isolates_threads_and_grades():
    orch = _FakeOrchestrator("The answer: damped frequency omega_d = omega_0 * sqrt(1 - zeta^2) (arXiv:1807.09547).")
    case = EvalCase(id="c1", suite="s", query="Damped oscillator frequency?", setup=["earlier turn"],
                    retrieval={"gold_arxiv_ids": ["1807.09547"]}, reference="omega_d = omega_0 sqrt(1 - zeta^2).",
                    answer={"must_mention": ["omega_d"], "cite_gold": True, "label": "maybe", "options": ["yes", "no", "maybe"],
                            "answer_type": "yesno"})
    ev = Evaluator(RunConfig(levels=["answer"], judge=True, judge_min=4.0), orchestrator=orch,
                   llm_factory=lambda **kw: _FakeGrader("maybe"), run_id="t")
    [res] = asyncio.run(ev.run([case]))
    assert [q for q, _ in orch.calls] == ["earlier turn", "Damped oscillator frequency?"]
    assert orch.calls[1][1]["recall_memory"] is True and orch.memory.cleared == ["eval-t-c1"]
    assert res.passed, [c for c in res.checks if not c.passed]
    assert res.metrics["predicted"] == "maybe" and res.metrics["judge"]["overall"] == 4.4 and res.metrics["retrieval_hit"]


def test_rescore_applies_new_expectations_without_calling_the_system():
    orch = _FakeOrchestrator("omega_d rises (arXiv:1807.09547).")
    case = EvalCase(id="r1", suite="s", query="q", answer={"must_mention": ["omega_d"]})
    ev = Evaluator(RunConfig(levels=["answer"]), orchestrator=orch, llm_factory=lambda **kw: _FakeGrader("x"), run_id="r")
    [old] = asyncio.run(ev.run([case]))
    assert old.passed and len(orch.calls) == 1
    stricter = case.model_copy(update={"answer": AnswerExpect(must_mention=["omega_d", "quality factor"])})
    new = asyncio.run(ev.rescore(stricter, old))
    assert not new.passed and len(orch.calls) == 1  # re-scored from stored observations only
    retrieval = CaseResult(case_id="r2", suite="s", category="c", level="retrieval", query="q",
                           observed={"pmids": ["1", "2"], "dois": ["", ""], "titles": ["A", "Revisiting the damped oscillator"]})
    re_case = EvalCase(id="r2", suite="s", query="q", retrieval={"gold_pmids": ["9"], "gold_title_patterns": [r"\boscillator\b"]})
    assert asyncio.run(ev.rescore(re_case, retrieval)).passed


def test_failed_live_case_is_retried_and_marked_flaky():
    calls = {"n": 0}

    class Flaky(Evaluator):
        async def run_plan(self, case: EvalCase) -> CaseResult:
            calls["n"] += 1
            r = self._result(case, "plan")
            r.checks = [Check(name="plan.scope", passed=calls["n"] > 1)]
            return r

    case = EvalCase(id="f", suite="s", query="q", plan={"scope": "research"})
    [res] = asyncio.run(Flaky(RunConfig(levels=["plan"], live=True, retries=1)).run([case]))
    assert res.passed and res.metrics["flaky"] and res.metrics["attempts"] == 2
    calls["n"] = -5  # fails twice
    [res] = asyncio.run(Flaky(RunConfig(levels=["plan"], live=True, retries=1)).run([case]))
    assert not res.passed and not res.metrics["flaky"]


def test_errors_and_timeouts_become_results():
    class Broken(Evaluator):
        async def run_plan(self, case: EvalCase) -> CaseResult:
            raise RuntimeError("boom")

    case = EvalCase(id="e", suite="s", query="q", plan={"scope": "research"})
    [res] = asyncio.run(Broken(RunConfig(levels=["plan"])).run([case]))
    assert not res.passed and "boom" in res.error


# ---------------------------------------------------------------------------------------------------------------
# Reports, gate, compare, CLI
# ---------------------------------------------------------------------------------------------------------------

def _result(cid: str, level: str, passed: bool, **metrics: Any) -> CaseResult:
    r = CaseResult(case_id=cid, suite="s", category="cat", level=level, query="q", latency_s=1.0,
                   checks=[Check(name="x", passed=passed)], metrics=metrics)
    return r.finalize()


def test_summary_gate_and_compare(tmp_path: Path):
    base = [_result("a", "retrieval", True, hit=True, recall=1.0, rr=1.0), _result("b", "retrieval", True, hit=True, recall=0.5, rr=0.5)]
    new = [_result("a", "retrieval", True, hit=True, recall=1.0, rr=1.0), _result("b", "retrieval", False, hit=False, recall=0.0, rr=0.0)]
    s = report.summarize(new)
    assert s["levels"]["retrieval"]["pass_rate"] == 0.5 and s["levels"]["retrieval"]["retrieval"]["hit_rate"] == 0.5
    assert report.gate(s, report.parse_thresholds("retrieval.pass_rate=0.5, retrieval.hit_rate=0.5")) == []
    failures = report.gate(s, report.parse_thresholds("retrieval.hit_rate=0.9,answer.pass_rate=0.5"))
    assert len(failures) == 2 and "not measured" in failures[1]
    for name, rows in (("base", base), ("new", new)):
        d = tmp_path / name
        d.mkdir()
        (d / "results.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in rows))
        report.write_reports(d, {"run_id": name, "suites": ["s"], "n_cases": 2}, rows)
        assert (d / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    text = report.compare(tmp_path / "base", tmp_path / "new")
    assert "Regressions (1)" in text and "**b** (retrieval)" in text and "| retrieval | pass_rate | 100% | 50% | -0.500 |" in text


def test_results_file_keeps_the_last_result_per_case(tmp_path: Path):
    path = tmp_path / "results.jsonl"
    path.write_text(_result("a", "plan", False).model_dump_json() + "\n" + _result("a", "plan", True).model_dump_json() + "\n")
    [r] = load_results(path)
    assert r.passed


def test_cli_runs_a_suite_and_applies_the_gate(tmp_path: Path, capsys):
    suite = tmp_path / "mini.jsonl"
    suite.write_text(
        EvalCase(id="m1", suite="mini", query="thanks!", plan={"scope": "conversational", "offline": True}).model_dump_json() + "\n"
        + EvalCase(id="m2", suite="mini", query="Derive the Euler-Bernoulli beam deflection formula.",
                   plan={"scope": "conversational", "offline": True}).model_dump_json() + "\n"  # wrong on purpose
    )
    out = tmp_path / "runs"
    assert cli_main(["run", "--suite", str(suite), "--level", "plan", "--out", str(out), "--fail-under", "plan.pass_rate=0.5"]) == 0
    assert cli_main(["run", "--suite", str(suite), "--level", "plan", "--out", str(out), "--fail-under", "plan.pass_rate=1"]) == 1
    run_dir = sorted(out.iterdir())[-1]
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["levels"]["plan"]["passed"] == 1 and (run_dir / "report.md").exists()
    assert cli_main(["report", str(run_dir)]) == 0
    assert cli_main(["run", "--suite", "nope", "--out", str(out)]) == 2
    assert cli_main(["list"]) == 0 and "physics" in capsys.readouterr().out
