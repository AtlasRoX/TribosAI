"""Benchmark report (tribos/evals/benchmark_report.py): the statistics against published values, how each stored
result is scored (answer check only; gates, errors, timeouts, skips and label errors each handled on their own),
pairing across systems, and an end-to-end render from synthetic run directories."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

from tribos.evals import benchmark_report as br
from tribos.evals.benchmark_stats import (
    mcnemar_exact,
    paired_diff_ci,
    paired_summary,
    percentile,
    wilson,
)
from tribos.evals.scoring import GATES

# ---------------------------------------------------------------------------------------------------------------
# Synthetic results, in the shape the eval runner writes (CaseResult.model_dump_json)
# ---------------------------------------------------------------------------------------------------------------


def record(case_id: str, suite: str, *, correct: bool = True, kind: str = "numeric", error: str | None = None,
           skipped: str | None = None, verified: bool | None = None, latency: float = 10.0, gate_failures: tuple = (),
           final_source: str | None = "boxed", label_source: str | None = None, llm_calls: int | None = None,
           tokens: int | None = None, tool_calls: int | None = None, query: str | None = None,
           response: str | None = None, framework: str = "direct") -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"abstained": False, "verified": verified, "llm_calls": llm_calls, "tokens_est": tokens,
                               "tool_calls": tool_calls, "latency_s": latency}
    if error is None and skipped is None:
        if kind == "numeric":
            got = 42.0 if correct else 41.0
            checks.append({"name": "answer.numeric", "passed": correct, "required": True,
                           "detail": f"expected 42 (±max(0.001, 1.0%)), got {got:g}"})
            metrics.update(numeric_expected=42.0, numeric_predicted=got, numeric_correct=correct)
            if final_source:
                metrics["final_answer_source"] = final_source
                if final_source == "model":
                    metrics["final_answer"] = f"{got:g}"
        elif kind == "choice":
            checks.append({"name": "answer.label", "passed": correct, "required": True, "detail": ""})
            metrics.update(label="the right option", predicted="the right option" if correct else "a wrong option",
                           correct=correct, answered=True, label_source=label_source or "rule")
        for gate in GATES:
            checks.append({"name": gate, "passed": gate not in gate_failures, "required": True, "detail": ""})
    elif error is not None:
        checks.append({"name": "answer.no_crash", "passed": False, "required": True, "detail": error})
        metrics = {}
    passed = error is None and skipped is None and all(c["passed"] for c in checks if c["required"])
    text = response if response is not None else ("\\boxed{42}" if correct else "\\boxed{41}")
    return {"case_id": case_id, "suite": suite, "category": "test", "level": "answer", "query": query or f"Question {case_id}?",
            "passed": passed, "checks": checks, "metrics": metrics, "latency_s": latency, "error": error, "skipped": skipped,
            "observed": {"response": None if error else text, "verified": verified, "framework": framework}}


def write_run(path: Path, system: str, records: list[dict[str, Any]], *, suites: list[str], finished: bool = True,
              model: str = "test-model", n_cases: int | None = None) -> Path:
    path.mkdir(parents=True)
    meta: dict[str, Any] = {
        "run_id": f"run-{system}", "started_at": "2026-11-04T10:00:00", "suites": suites,
        "n_cases": n_cases if n_cases is not None else len(records),
        "config": {"levels": ["answer"], "timeout_s": 420.0, "concurrency": 2, "grade_with_model": True, "judge": False,
                   "repeat": 1, "system": system},
        "model": model, "system": system, "source_fingerprint": "fp0123456789abcd", "env": {"TRIBOS_LLM_MODEL": model},
        "python": "3.12.0", "platform": "test-platform",
    }
    if finished:
        meta["duration_s"] = 60.0
    (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


LABEL_ERRORS = {
    "_about": "notes, not a case",
    "gsm8k-454": {"question": "Marin and Nancy each eat 4 apples a day. How many apples do they eat in 30 days?",
                  "reference_answer": "150", "correct_answer": "240",
                  "evidence": "The reference computes 4 + 1 = 5 apples a day; two people eat 8 a day.", "found": "pilot"},
}


def gsm8k_scenario() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Tribos and direct records for one suite, covering every way a result can be scored."""
    s = "gsm8k"
    tribos = [
        record("gsm8k-1", s, correct=True, verified=True, latency=30, framework="react"),
        record("gsm8k-2", s, correct=True, verified=True, latency=40, final_source="model", framework="react"),
        record("gsm8k-3", s, correct=True, verified=False, latency=50, final_source="model", framework="react"),
        record("gsm8k-4", s, correct=False, verified=False, latency=20, framework="react"),
        record("gsm8k-5", s, correct=False, verified=True, latency=25, final_source=None, framework="react"),
        record("gsm8k-6", s, error="timed out after 420s", latency=420),
        # A right number with a citation outside the evidence: a gate failure, still a correct answer.
        record("gsm8k-7", s, correct=True, verified=False, gate_failures=("answer.citations_in_evidence",), framework="react"),
        record("gsm8k-8", s, skipped="no cassette"),
        record("gsm8k-9", s, correct=True, framework="react"),  # no direct counterpart
        record("gsm8k-11", s, kind="none", framework="react"),  # no correctness check
        record("gsm8k-454", s, correct=False, verified=True, framework="react"),  # a known label error
    ]
    direct = [
        record("gsm8k-1", s, correct=True, latency=10, llm_calls=1, tokens=900),
        record("gsm8k-2", s, correct=False, latency=10, llm_calls=1, tokens=900),
        record("gsm8k-3", s, correct=False, latency=10, llm_calls=1, tokens=900),
        record("gsm8k-4", s, correct=True, latency=10, llm_calls=1, tokens=900),
        record("gsm8k-5", s, correct=False, latency=10, llm_calls=1, tokens=900),
        record("gsm8k-6", s, correct=True, latency=10, llm_calls=1, tokens=900),
        record("gsm8k-7", s, error="RuntimeError: provider returned 500", latency=3),
        record("gsm8k-8", s, correct=True, latency=10, llm_calls=1, tokens=900),
        record("gsm8k-10", s, correct=True, latency=10, llm_calls=1, tokens=900),  # no Tribos counterpart
        record("gsm8k-11", s, correct=True, latency=10, llm_calls=1, tokens=900),
        record("gsm8k-454", s, correct=False, latency=10, llm_calls=1, tokens=900),
    ]
    return tribos, direct


# ---------------------------------------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("k", "n", "lo", "hi"), [
    (81, 263, 0.2553, 0.3662),  # Newcombe (1998), Statistics in Medicine 17:857, Table I
    (15, 148, 0.0624, 0.1605),
    (0, 20, 0.0, 0.1611),
    (1, 29, 0.0061, 0.1718),
    (5, 10, 0.2366, 0.7634),
    (10, 10, 0.7225, 1.0),
])
def test_wilson_interval_matches_published_values(k, n, lo, hi):
    got = wilson(k, n)
    assert got is not None
    assert got[0] == pytest.approx(lo, abs=6e-5)
    assert got[1] == pytest.approx(hi, abs=6e-5)


def test_wilson_edge_cases():
    assert wilson(0, 0) is None
    assert wilson(0, 7)[0] == 0.0 and wilson(7, 7)[1] == 1.0
    with pytest.raises(ValueError):
        wilson(5, 3)


@pytest.mark.parametrize(("b", "c", "p"), [
    (0, 5, 0.0625),  # 2 * (1/2)^5
    (1, 9, 22 / 1024),  # 2 * (1 + 10) / 2^10
    (2, 8, 112 / 1024),  # 2 * (1 + 10 + 45) / 2^10
    (10, 0, 2 / 1024),
    (5, 5, 1.0),
    (0, 0, 1.0),  # no discordant pairs: no evidence either way
    (3, 4, 1.0),
])
def test_exact_mcnemar_known_values(b, c, p):
    assert mcnemar_exact(b, c) == pytest.approx(p, rel=1e-12)
    assert mcnemar_exact(c, b) == pytest.approx(p, rel=1e-12)  # two-sided: symmetric


def test_exact_mcnemar_agrees_with_scipy_binomial_test():
    stats = pytest.importorskip("scipy.stats")
    for b, c in ((3, 12), (7, 19), (20, 31), (1, 1), (0, 9)):
        assert mcnemar_exact(b, c) == pytest.approx(stats.binomtest(min(b, c), b + c, 0.5).pvalue, rel=1e-9)


def test_percentile_is_linear_interpolation():
    np = pytest.importorskip("numpy")
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    vals = [3.2, 9.9, 1.0, 44.0, 7.5, 12.25, 5.0]
    for q in (0.0, 0.25, 0.5, 0.95, 1.0):
        assert percentile(vals, q) == pytest.approx(float(np.percentile(vals, q * 100)))
    assert percentile([], 0.5) is None


def test_paired_difference_interval_is_agresti_min():
    lo, hi = paired_diff_ci(40, 8, 2, 0)
    # Half a count added to each cell: p12 = 8.5/52, p21 = 2.5/52, Wald interval around their difference.
    p12, p21 = 8.5 / 52, 2.5 / 52
    se = math.sqrt((p12 + p21 - (p12 - p21) ** 2) / 52)
    assert lo == pytest.approx(p12 - p21 - 1.959963984540054 * se)
    assert hi == pytest.approx(p12 - p21 + 1.959963984540054 * se)
    s = paired_summary([(True, True)] * 40 + [(True, False)] * 8 + [(False, True)] * 2)
    assert (s["n"], s["only_first"], s["only_second"], s["difference"]) == (50, 8, 2, pytest.approx(0.12))
    assert s["mcnemar_p"] == pytest.approx(112 / 1024)
    assert paired_diff_ci(0, 0, 0, 0) is None
    lo, hi = paired_diff_ci(0, 30, 0, 0)
    assert -1.0 <= lo <= hi <= 1.0


# ---------------------------------------------------------------------------------------------------------------
# Scoring one stored result
# ---------------------------------------------------------------------------------------------------------------


def test_correctness_is_the_answer_check_not_the_gates():
    o = br.outcome_from_record(record("c", "gsm8k", correct=True, gate_failures=("answer.citations_in_evidence",)), "tribos")
    assert (o.status, o.correct, o.answer_type, o.passed) == ("ok", True, "numeric", False)
    assert o.decided_by == ["answer.numeric"] and o.gate_failures == ["answer.citations_in_evidence"]
    assert o.tolerance == "max(0.001, 1.0% of |expected|)"
    wrong = br.outcome_from_record(record("c", "gsm8k", correct=False), "direct")
    assert (wrong.correct, wrong.expected, wrong.predicted) == (False, "42", "41")


def test_errors_and_timeouts_are_incorrect_and_told_apart():
    t = br.outcome_from_record(record("c", "s", error="timed out after 420s"), "tribos")
    e = br.outcome_from_record(record("c", "s", error="RuntimeError: boom"), "tribos")
    assert (t.status, t.correct) == ("timeout", False)
    assert (e.status, e.correct) == ("error", False)
    assert e.gate_failures == ["answer.no_crash"]


def test_skipped_and_ungraded_results_are_left_out():
    s = br.outcome_from_record(record("c", "s", skipped="no cassette"), "tribos")
    u = br.outcome_from_record(record("c", "s", kind="none"), "tribos")
    assert (s.status, s.correct) == ("skipped", None)
    assert (u.status, u.correct, u.answer_type) == ("ungraded", None, None)


def test_answer_types_and_final_answer_sources():
    yesno = record("c", "s", kind="choice")
    yesno["metrics"]["label"] = "yes"
    assert br.outcome_from_record(yesno, "t").answer_type == "yesno"
    choice = br.outcome_from_record(record("c", "s", kind="choice", label_source="model"), "t")
    assert (choice.answer_type, choice.label_source, choice.final_answer_source) == ("choice", "model", None)
    assert br.outcome_from_record(record("c", "s", final_source="model"), "t").final_answer_source == "model"
    assert br.outcome_from_record(record("c", "s", final_source="model"), "t").final_answer == "42"
    assert br.outcome_from_record(record("c", "s", final_source=None), "t").final_answer_source == "unknown"
    assert br.outcome_from_record(record("c", "s", error="boom"), "t").final_answer_source is None


# ---------------------------------------------------------------------------------------------------------------
# Pairing and the summary
# ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def scenario_runs(tmp_path):
    tribos, direct = gsm8k_scenario()
    t = write_run(tmp_path / "pilot" / "tribos" / "20261104-100000_gsm8k_answer", "tribos", tribos, suites=["gsm8k"])
    d = write_run(tmp_path / "pilot" / "direct" / "20261104-090000_gsm8k_answer", "direct", direct, suites=["gsm8k"])
    le = tmp_path / "known_label_errors.json"
    le.write_text(json.dumps(LABEL_ERRORS), encoding="utf-8")
    return t, d, le


def _analyze(t: Path, d: Path, le: Path | None = None) -> dict[str, Any]:
    errors, _ = br.load_label_errors(le)
    return br.analyze({"tribos": [br.load_run(t, "tribos")], "direct": [br.load_run(d, "direct")]}, seed=1,
                      label_errors=errors, label_errors_path=le)


def test_pairing_counts_every_outcome(scenario_runs):
    t, d, le = scenario_runs
    s = _analyze(t, d, le)
    g = s["suites"]["gsm8k"]
    p = g["paired"]
    assert (p["n"], p["both_right"], p["only_tribos"], p["only_direct"], p["both_wrong"]) == (7, 1, 3, 2, 1)
    assert g["tribos"]["accuracy"]["k"] == 4 and g["direct"]["accuracy"]["k"] == 3
    assert p["mcnemar_p"] == pytest.approx(mcnemar_exact(3, 2))
    assert p["difference"] == pytest.approx(1 / 7)
    assert g["unpaired"] == {"tribos_only": ["gsm8k/gsm8k-9"], "direct_only": ["gsm8k/gsm8k-10"]}
    assert g["excluded_from_pairs"] == {"skipped": 1, "ungraded": 1, "label_errors": 1}
    ht, hd = g["health"]["tribos"], g["health"]["direct"]
    assert (ht["results"], ht["timeout"], ht["skipped"], ht["ungraded"], ht["excluded_label_errors"]) == (11, 1, 1, 1, 1)
    assert (hd["results"], hd["error"], hd["excluded_label_errors"]) == (11, 1, 1)
    # The gate failure is reported, on a correct answer, and did not cost the case its correctness.
    assert g["tribos"]["gate_failures"]["answer.citations_in_evidence"] == 1
    assert g["tribos"]["gate_failures_on_correct_answers"] == 1
    assert g["tribos"]["timeouts"] == 1 and g["direct"]["errors"] == 1


def test_verified_precision_and_final_answer_sources(scenario_runs):
    t, d, le = scenario_runs
    g = _analyze(t, d, le)["suites"]["gsm8k"]
    v = g["tribos"]["verified"]
    assert (v["coverage"]["k"], v["coverage"]["n"]) == (3, 7)
    assert (v["precision"]["k"], v["precision"]["n"]) == (2, 3)
    assert (v["other_accuracy"]["k"], v["other_accuracy"]["n"]) == (2, 4)
    assert g["direct"]["verified"] is None  # the direct baseline has no verifier
    fs = g["tribos"]["final_answer_source"]
    assert fs["n"] == 6 and (fs["boxed"]["k"], fs["model"]["k"], fs["unknown"]["k"], fs["heuristic"]["k"]) == (3, 2, 1, 0)
    assert g["direct"]["final_answer_source"]["boxed"]["k"] == 6


def test_known_label_errors_are_set_aside_for_both_systems(scenario_runs):
    t, d, le = scenario_runs
    with_le, without = _analyze(t, d, le), _analyze(t, d, None)
    assert with_le["suites"]["gsm8k"]["paired"]["n"] == 7
    assert without["suites"]["gsm8k"]["paired"]["n"] == 8  # the label error is an ordinary both-wrong pair otherwise
    issues = with_le["label_errors"]["excluded"]
    assert [i["case_id"] for i in issues] == ["gsm8k-454"]
    assert issues[0]["correct_answer"] == "240" and "4 + 1" in issues[0]["evidence"]
    assert issues[0]["answers"]["direct"]["graded_value"] == "41"
    assert with_le["label_errors"]["by_suite"] == {"gsm8k": 1}
    assert with_le["label_errors"]["entries_in_file"] == 1  # "_about" is a note
    assert all(ex["case_id"] != "gsm8k-454" for ex in with_le["examples"])


def test_examples_prefer_wrong_answers_and_withhold_gpqa(tmp_path):
    t_recs = [record(f"gsm8k-{i}", "gsm8k", correct=True) for i in range(3)] + \
             [record(f"gpqa-{i}", "gpqa", kind="choice", correct=True, query=f"SECRET GPQA QUESTION {i}") for i in range(3)]
    d_recs = [record("gsm8k-0", "gsm8k", error="timed out after 420s"), record("gsm8k-1", "gsm8k", correct=False),
              record("gsm8k-2", "gsm8k", correct=True)] + \
             [record(f"gpqa-{i}", "gpqa", kind="choice", correct=False) for i in range(3)]
    t = write_run(tmp_path / "t", "tribos", t_recs, suites=["gsm8k", "gpqa"])
    d = write_run(tmp_path / "d", "direct", d_recs, suites=["gsm8k", "gpqa"])
    s = _analyze(t, d)
    ids = [ex["case_id"] for ex in s["examples"]]
    assert ids[0] == "gsm8k-1"  # a wrong direct answer is a better example than a timeout
    assert not any(i.startswith("gpqa") for i in ids)
    assert s["examples_withheld_suites"] == ["gpqa"]
    page = br.render_html(s, embed_fonts=False)
    assert "SECRET GPQA QUESTION" not in page


def test_unfinished_and_mismatched_runs_are_flagged(tmp_path):
    t = write_run(tmp_path / "t", "direct", [record("gsm8k-1", "gsm8k")], suites=["gsm8k"], finished=False, n_cases=50)
    d = write_run(tmp_path / "d", "direct", [record("gsm8k-1", "gsm8k")], suites=["gsm8k"], model="other-model")
    s = br.analyze({"tribos": [br.load_run(t, "tribos")], "direct": [br.load_run(d, "direct")]})
    text = " ".join(s["warnings"])
    assert "system=direct" in text and "not finished" in text and "1 of 50" in text and "different models" in text


def test_reproduction_command_is_rebuilt_from_meta(scenario_runs):
    t, _, _ = scenario_runs
    cmd = br.run_command(br.load_run(t, "tribos"), seed=1)
    assert cmd.startswith("python -m tribos.evals run --suite gsm8k --level answer --limit 11 --seed 1 --system tribos")
    assert "--out" in cmd


def test_truncated_last_line_is_ignored(tmp_path):
    run = write_run(tmp_path / "r", "direct", [record("gsm8k-1", "gsm8k")], suites=["gsm8k"])
    with open(run / "results.jsonl", "a", encoding="utf-8") as f:
        f.write('{"case_id": "gsm8k-2", "suite": "gsm')
    loaded = br.load_run(run, "direct")
    assert len(loaded.outcomes) == 1 and loaded.bad_lines == 1


# ---------------------------------------------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------------------------------------------


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


def test_cli_renders_a_self_contained_report(scenario_runs, tmp_path):
    t, _, le = scenario_runs
    root = t.parents[1]
    out = tmp_path / "out"
    assert br.main([str(root), "--out", str(out), "--seed", "1", "--no-pdf", "--label-errors", str(le)]) == 0
    page = (out / "report.html").read_text(encoding="utf-8")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    o = summary["overall"]
    assert o["paired"]["n"] == 7 and summary["seed"] == 1 and summary["pdf"] == {"written": False, "reason": "--no-pdf"}
    # The headline numbers, as printed.
    for value in (br.fmt_pct(o["tribos"]["accuracy"]["rate"]), br.fmt_pct(o["direct"]["accuracy"]["rate"]),
                  br.fmt_pp(o["paired"]["difference"]), br.fmt_ci(o["tribos"]["accuracy"]["ci95"])):
        assert value in page
    assert "57.1%" in page and "42.9%" in page  # 4/7 and 3/7
    for section in ("Results by benchmark", "Where the systems disagree", "How far to trust a verified answer", "Time and cost",
                    "Run health", "How final answers were read", "Data issues", "Worked examples", "Methodology",
                    "Limitations", "Appendix: reproducibility"):
        assert section in page
    assert "gsm8k-454" in page and "4 + 1 = 5 apples" in page
    assert page.count("<svg") >= 4 and "aria-label=" in page
    # Self-contained: nothing is fetched when the page is viewed.
    assert not re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", page)
    assert "<link" not in page and "<script" not in page and "@import" not in page and "url(http" not in page
    assert "--system tribos" in page and "--system direct" in page and "--seed 1" in page
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "| GSM8K | 7 |" in md and "Known label errors set aside" in md


def test_cli_needs_both_systems(tmp_path):
    (tmp_path / "tribos").mkdir()
    write_run(tmp_path / "direct" / "r", "direct", [record("gsm8k-1", "gsm8k")], suites=["gsm8k"])
    assert br.main([str(tmp_path), "--out", str(tmp_path / "out"), "--no-pdf"]) == 2


@pytest.mark.slow
def test_pdf_is_printed_by_chromium_with_embedded_fonts(scenario_runs, tmp_path):
    t, d, le = scenario_runs
    out = tmp_path / "out"
    summary = br.build_report([t], [d], out, seed=1, label_errors_path=le)
    page = (out / "report.html").read_text(encoding="utf-8")
    assert "@font-face" in page and "font/woff" in page  # Google Sans, subset and inline
    if not _chromium_available():
        assert summary["pdf"]["written"] is False and summary["pdf"]["reason"]
        pytest.skip("Chromium is not installed for Playwright")
    pdf = out / "report.pdf"
    assert summary["pdf"] == {"written": True, "engine": "chromium"}
    assert pdf.read_bytes().startswith(b"%PDF")
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    assert len(reader.pages) >= 3
    text = " ".join(p.extract_text() or "" for p in reader.pages)
    assert "Methodology" in text and "57.1%" in text
