"""Agreement between readings of one image, and the words a transcription must keep.

Two independent vision readings of the same image are compared after both are put in one canonical form: Unicode
math becomes LaTeX commands (∀ -> \\forall), aliases become one spelling (\\ne -> \\neq, \\le -> \\leq), grouping
braces, spacing commands, \\left/\\right and Markdown emphasis are dropped, and \\text{...}-style wrappers keep only
their content. What still differs after that is a real difference in what was read (a_i against a_1, \\equiv against
=), and it is settled by looking at the image again.

The coverage check asks whether a transcription kept the words of the image. Only words that are surely in the image
count: those both OCR engines read (Indra, and Tesseract with high confidence). OCR garbles mathematics ("(V)ieN*"
for "(∀)i∈ℕ*"), and garbled tokens must never count against a correct LaTeX transcription; standalone numbers count,
digits glued to letters (a1 for a_i) do not.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tesseract import TessResult

MIN_WORDS = 8  # fewer surely-read words than this and coverage is not judged (mostly-math images)

_UNICODE = {
    "∀": r"\forall", "∃": r"\exists", "∄": r"\nexists", "∈": r"\in", "∉": r"\notin", "∋": r"\ni", "≠": r"\neq",
    "≡": r"\equiv", "≤": r"\leq", "≥": r"\geq", "⩽": r"\leq", "⩾": r"\geq", "≈": r"\approx", "∼": r"\sim",
    "≅": r"\cong", "∝": r"\propto", "→": r"\to", "←": r"\leftarrow", "↔": r"\leftrightarrow", "⇒": r"\Rightarrow",
    "⇐": r"\Leftarrow", "⇔": r"\Leftrightarrow", "↦": r"\mapsto", "∞": r"\infty", "∑": r"\sum", "∏": r"\prod",
    "∫": r"\int", "∮": r"\oint", "√": r"\sqrt", "∂": r"\partial", "∇": r"\nabla", "×": r"\times", "·": r"\cdot",
    "⋅": r"\cdot", "÷": r"\div", "±": r"\pm", "∓": r"\mp", "∪": r"\cup", "∩": r"\cap", "⊂": r"\subset",
    "⊆": r"\subseteq", "⊃": r"\supset", "⊇": r"\supseteq", "∅": r"\emptyset", "∖": r"\setminus", "∧": r"\wedge",
    "∨": r"\vee", "¬": r"\neg", "∠": r"\angle", "⊥": r"\perp", "∥": r"\parallel", "°": r"^\circ", "…": r"\ldots",
    "⋯": r"\ldots", "ℕ": r"\mathbb{N}", "ℤ": r"\mathbb{Z}", "ℚ": r"\mathbb{Q}", "ℝ": r"\mathbb{R}",
    "ℂ": r"\mathbb{C}", "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\epsilon",
    "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta", "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu",
    "ν": r"\nu", "ξ": r"\xi", "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "φ": r"\phi", "ϕ": r"\phi",
    "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega", "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Π": r"\Pi", "Σ": r"\Sigma", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega", "−": "-", "–": "-", "—": "-",
    "′": "'", "″": "''", "“": '"', "”": '"', "‘": "'", "’": "'",
}
_ALIAS = {
    r"\ne": r"\neq", r"\le": r"\leq", r"\ge": r"\geq", r"\leqslant": r"\leq", r"\geqslant": r"\geq",
    r"\rightarrow": r"\to", r"\dots": r"\ldots", r"\cdots": r"\ldots", r"\dotsc": r"\ldots", r"\dotsb": r"\ldots",
    r"\lbrace": r"\{", r"\rbrace": r"\}", r"\varepsilon": r"\epsilon", r"\varphi": r"\phi", r"\vert": "|",
    r"\lvert": "|", r"\rvert": "|", r"\mid": "|", r"\land": r"\wedge", r"\lor": r"\vee", r"\lnot": r"\neg",
    r"\gets": r"\leftarrow", r"\implies": r"\Rightarrow", r"\iff": r"\Leftrightarrow", r"\colon": ":",
    r"\bmod": "mod", r"\mod": "mod", r"\dfrac": r"\frac", r"\tfrac": r"\frac", r"\lt": "<", r"\gt": ">",
    r"\N": r"\mathbb{N}", r"\Z": r"\mathbb{Z}", r"\R": r"\mathbb{R}", r"\Q": r"\mathbb{Q}", r"\C": r"\mathbb{C}",
    r"\ast": "*", r"\star": "*",
}
_DROP = {r"\displaystyle", r"\textstyle", r"\left", r"\right", r"\big", r"\Big", r"\bigg", r"\Bigg", r"\bigl",
         r"\bigr", r"\Bigl", r"\Bigr", r"\limits", r"\nolimits", r"\quad", r"\qquad", r"\,", r"\;", r"\:", r"\!",
         r"\ ", r"\mathrm", r"\text", r"\textrm", r"\operatorname", r"\mbox", r"\textit", r"\mathit", r"\textup",
         r"\textnormal", "$", "{", "}", r"\[", r"\]", r"\(", r"\)"}
# Differences made only of these are layout, not reading.
_SOFT = {".", ",", ";", ":", "*", "#", "-", "\\\\", "&"}
_TOKEN_RE = re.compile(r"\\[A-Za-z]+|\\.|[A-Za-z]+|\d+(?:\.\d+)?|\S")
_PMOD_RE = re.compile(r"\\pmod\s*\{([^{}]*)\}|\\pmod\s*(\w)")
_BB_RE = re.compile(r"\\(mathbb|mathcal|mathfrak|mathscr|mathbf|boldsymbol)\s*([A-Za-z0-9])")


def _literal_braces(s: str) -> str:
    """Set braces written as plain { } become \\{ \\}, so "{a_n}" in text equals "\\{a_n\\}" in math.

    Inside math ($...$) a bare brace groups; outside it a brace is printed, unless it follows _, ^ or a \\command
    (a subscript group like "_{n∈ℕ*}" in text that a model left outside $...$). A closing brace takes the kind of
    the brace it closes.
    """
    out: list[str] = []
    stack: list[bool] = []  # True: literal
    math = False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            pair = s[i: i + 2]
            if pair in ("\\(", "\\["):
                math = True
            elif pair in ("\\)", "\\]"):
                math = False
            out.append(pair)
            i += 2
            continue
        if ch == "$":
            math = not math
            if s[i + 1: i + 2] == "$":  # $$ opens or closes one display block
                out.append("$$")
                i += 2
                continue
        elif ch == "{":
            prev = s[:i].rstrip()[-1:] if s[:i].strip() else ""
            after_command = bool(re.search(r"\\[A-Za-z]+\s*$", s[:i]))
            literal = not math and prev not in ("_", "^") and not after_command
            stack.append(literal)
            out.append("\\{" if literal else "{")
            i += 1
            continue
        elif ch == "}":
            literal = stack.pop() if stack else not math
            out.append("\\}" if literal else "}")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def canonical(text: str) -> list[str]:
    """The reading as comparable tokens (see the module docstring)."""
    s = _literal_braces(text or "")
    for ch, tex in _UNICODE.items():
        if ch in s:
            s = s.replace(ch, f" {tex} ")
    s = s.replace("**", " ").replace("__", " ")
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", " ", s)
    s = s.replace("...", r" \ldots ")
    s = _PMOD_RE.sub(lambda m: f" ( mod {m.group(1) or m.group(2)} ) ", s)
    s = _BB_RE.sub(lambda m: f"\\{m.group(1)}{{{m.group(2)}}}", s)
    out: list[str] = []
    for tok in _TOKEN_RE.findall(s):
        mapped = _ALIAS[tok] if tok in _ALIAS else str(tok)
        # An alias may stand for several tokens (\N -> \mathbb{N}); those are split and filtered like the rest.
        parts: list[str] = _TOKEN_RE.findall(mapped) if mapped != tok else [tok]
        out.extend(p for p in parts if p not in _DROP)
    # ℕ* and \mathbb{N}^* are the same mark: a caret before a star is notation, not a reading difference.
    return [t for i, t in enumerate(out) if not (t == "^" and i + 1 < len(out) and out[i + 1] == "*")]


@dataclass
class Agreement:
    agree: bool
    ratio: float
    differences: list[tuple[str, str]] = field(default_factory=list)  # (reading 1 here, reading 2 here) with context


def compare(first: str, second: str, context: int = 3) -> Agreement:
    """Whether two readings say the same thing, and where they do not."""
    a, b = canonical(first), canonical(second)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    diffs: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        changed = a[i1:i2] + b[j1:j2]
        if all(t in _SOFT for t in changed):
            continue
        left = " ".join(a[max(0, i1 - context): i2 + context]) or "(nothing)"
        right = " ".join(b[max(0, j1 - context): j2 + context]) or "(nothing)"
        diffs.append((left, right))
    return Agreement(agree=not diffs, ratio=round(sm.ratio(), 4), differences=diffs[:24])


_PLAIN_WORD_RE = re.compile(r"(?<![\\A-Za-z])[A-Za-z][a-z]+(?![A-Za-z])")
_PLAIN_NUMBER_RE = re.compile(r"(?<![\w.^_])\d+(?:\.\d+)?(?![\w.])")
_HAVE_RE = re.compile(r"[A-Za-z]+|\d+(?:\.\d+)?")


def plain_tokens(text: str, min_len: int = 3) -> list[str]:
    """Words (lowercase or capitalised, not LaTeX commands) and standalone numbers, lowercased, in reading order."""
    t = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", text or "")  # OCR spaces digits in LaTeX: "0 . 1"
    found = [(m.start(), m.group().lower()) for m in _PLAIN_WORD_RE.finditer(t) if len(m.group()) >= min_len]
    found += [(m.start(), m.group()) for m in _PLAIN_NUMBER_RE.finditer(t)]
    return [tok for _, tok in sorted(found)]


def reliable_tokens(ocr_text: str, tess: TessResult | None = None) -> list[str]:
    """The draft's words and numbers that are surely in the image.

    Both engines read it (best); else Tesseract's confident words; else Indra's words of four letters or more (short
    tokens are where garbled mathematics lands: "ien", "kea").
    """
    indra = plain_tokens(ocr_text)
    if tess is not None and tess.words:
        sure = plain_tokens(" ".join(tess.confident_words()))
        counted = Counter(sure)
        both = [t for t in indra if counted[t] > 0]
        if len(both) >= MIN_WORDS:
            return both
        if len(sure) >= MIN_WORDS:
            return sure
    return [t for t in indra if len(t) >= 4 or t[0].isdigit()]


def _have(transcription: str) -> set[str]:
    """Words and numbers a transcription contains (\\pmod{m} and \\bmod contain "mod"; "0 . 1" is 0.1)."""
    t = re.sub(r"\\[pb]mod\b", " mod ", transcription or "")
    t = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", t)
    return {w.lower() for w in _HAVE_RE.findall(t)}


def coverage(transcription: str, reference: str | list[str], min_len: int = 3) -> float:
    """Share of the reference words and numbers the transcription contains (1.0 when there are too few to judge).

    `reference` is a list from reliable_tokens, or exact text (a PDF text layer) whose every word counts.
    """
    words = plain_tokens(reference, min_len) if isinstance(reference, str) else list(reference)
    if len(words) < MIN_WORDS:
        return 1.0
    have = _have(transcription)
    return sum(w in have for w in words) / len(words)


def missing(transcription: str, reference: list[str]) -> list[str]:
    """Reference words the transcription lacks, first occurrence order."""
    have = _have(transcription)
    return list(dict.fromkeys(w for w in reference if w not in have))
