"""
Presentation check for a written answer: what a reader must never see, and whether the answer follows the user's own
task list. Deterministic, so it runs on every answer at no model cost.

`presentation_issues` lists the problems; `clean_presentation` removes the ones that can be removed without
rewriting (internal ids in headings, "established background:" tags, "(see q3)" cross references); the rest are given to
the editor (tribos.writer.editor) as instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Internal identifiers: sub-question ids, requested-item ids.
_ID_HEADING = re.compile(r"(?m)^(#{1,6}\s*)\[?\s*(?:q|req-?)\d+\s*\]?\s*[:.)\-–—]?\s*")
_ID_INLINE = re.compile(r"\[\s*(?:q|req-?)\d+\s*\]|\((?:see\s+)?(?:q|req-?)\d+\)|\b(?:sub-?question\s+)?q\d+\b(?=[\s,;:.)\]–-]*(?:[–-]\s*q\d+|above|below)?)", re.I)
_BG_TAG = re.compile(r"\(?\b(?:established|textbook)\s+background\b\)?\s*[:,—–-]?\s*", re.I)

# Pipeline vocabulary that tells the reader about the machinery instead of the answer.
_JARGON = [
    (re.compile(r"\b(?:in|from|within|per)\s+(?:the\s+)?evidence\b|\bthe\s+evidence\s+(?:shows|contains|provides|gives|states)\b", re.I), "refers to 'the evidence'"),
    (re.compile(r"\btool_status\b|\bexecution_artifacts?\b|<\/?[a-z_]+(?:\s[^>]*)?>", re.I), "shows internal tags or fields"),
    (re.compile(r"`?\b(?:axiom|dynamis|physis|calcula|archivon|sage)_[a-z_]+\b`?", re.I), "names an internal tool"),
    (re.compile(r"\b(?:the\s+)?(?:verified\s+)?mathematics\s+agent\b|\bmath(?:s)?\s+agent\b|\bthe\s+agent(?:'s)?\b|\bagent\.[a-z_.]+", re.I), "mentions an internal agent"),
    (re.compile(r"\b(?:Calcula|Axiom|Dynamis|Physis|Archivon)\b(?!\s*\()"), "names an internal engine"),
    (re.compile(r"\bcopied\s+exactly\b|\bquoted\s+exactly\b|\bas\s+(?:quoted|returned)\s+by\b", re.I), "narrates copying tool output"),
    (re.compile(r"\b(?:is|are|was|were)\s+not\s+(?:quoted|reported|computed)\s+here\b", re.I), "declines to give a value without a reason the reader can use"),
]
# Computer-algebra output pasted as prose: '**' powers, '*' products between symbols, sqrt( / exp( calls.
_RAW_CAS = re.compile(r"(?<![`$\\])\b(?:sqrt|exp|sin|cos|log)\([^)]{0,80}\)\s*[*/]|\w\*\*\w|\d\*[a-z(]|\)\*\(", re.I)
_LONG_FLOAT = re.compile(r"(?<![\w.])-?\d+\.\d{10,}(?![\w])")


@dataclass
class Issue:
    kind: str
    detail: str
    excerpt: str = ""


def _outside_code(text: str) -> str:
    """The text with fenced and inline code blanked out (code may legitimately show raw expressions)."""
    text = re.sub(r"```.*?```", lambda m: " " * len(m.group(0)), text, flags=re.S)
    return re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), text)


def _outside_math(text: str) -> str:
    text = re.sub(r"\$\$.*?\$\$", lambda m: " " * len(m.group(0)), text, flags=re.S)
    return re.sub(r"\$[^$\n]+\$", lambda m: " " * len(m.group(0)), text)


def _excerpt(text: str, start: int, end: int) -> str:
    s = max(0, start - 40)
    return " ".join(text[s:end + 40].split())


def presentation_issues(answer: str, outline: list[tuple[str, str]] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    text = answer or ""
    prose = _outside_math(_outside_code(text))
    for m in _ID_HEADING.finditer(text):
        issues.append(Issue("internal_id", "heading carries an internal id", m.group(0).strip()))
    for m in _ID_INLINE.finditer(prose):
        issues.append(Issue("internal_id", "internal id in the text", _excerpt(prose, m.start(), m.end())))
    for m in _BG_TAG.finditer(prose):
        issues.append(Issue("label", "'established background' tag", _excerpt(prose, m.start(), m.end())))
    for pat, why in _JARGON:
        for m in pat.finditer(prose if "tag" not in why else _outside_code(text)):
            issues.append(Issue("jargon", why, _excerpt(prose, m.start(), m.end())))
    no_code = _outside_code(text)
    for m in _RAW_CAS.finditer(_outside_math(no_code)):
        issues.append(Issue("raw_math", "computer-algebra syntax instead of LaTeX", _excerpt(no_code, m.start(), m.end())))
    for line in no_code.splitlines():
        if len(line) > 400 and line.count(" ") < len(line) / 25:
            issues.append(Issue("raw_math", "very long unbroken expression", line[:120]))
    for m in _LONG_FLOAT.finditer(_outside_math(no_code)):
        issues.append(Issue("precision", "number with more digits than are meaningful", m.group(0)))
    if outline:
        issues.extend(outline_issues(text, outline))
    # One issue per excerpt and kind is enough for the editor.
    seen: set[tuple[str, str]] = set()
    unique = []
    for i in issues:
        key = (i.kind, i.excerpt[:60])
        if key not in seen:
            seen.add(key)
            unique.append(i)
    return unique


def _headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"(?m)^#{2,4}\s+(.+?)\s*$", text)]


def outline_issues(text: str, outline: list[tuple[str, str]]) -> list[Issue]:
    """Each user task should have its own heading starting with its label, in the user's order."""
    heads = _headings(text)
    positions = []
    missing = []
    for label, body in outline:
        pat = re.compile(rf"^(?:task\s+|part\s+|\()?{re.escape(label)}[.):\s]", re.I)
        idx = next((i for i, h in enumerate(heads) if pat.match(h)), None)
        if idx is None:
            missing.append(f"{label}. {body[:70]}")
        else:
            positions.append(idx)
    out = []
    if missing:
        out.append(Issue("outline", "the user's tasks are not each answered under their own numbered heading",
                         "; ".join(missing[:8])))
    if positions != sorted(positions):
        out.append(Issue("outline", "the task sections are not in the user's order"))
    return out


def _drop_echoed_instructions(text: str, question: str) -> str:
    """Remove the question's own prohibitions repeated verbatim as a sentence of the answer ("... infinitely many twin
    primes. Do not claim a proof that does not exist."): an instruction to the writer, not part of the answer."""
    rules = {re.sub(r"\s+", " ", m.group(0)).strip() for m in _PROHIBITION_RE.finditer(question or "")}
    rules = {r for r in rules if len(r.split()) >= 4}
    if not rules:
        return text
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    for i in range(0, len(parts), 2):  # outside code fences
        for rule in rules:
            pattern = r"(?<![^\s])" + r"\s+".join(map(re.escape, rule.split())) + r"(?=\s|$)"
            parts[i] = re.sub(r"[ \t]*" + pattern, "", parts[i], flags=re.I)
    return "".join(parts)


_PROHIBITION_RE = re.compile(r"(?:^|(?<=[.!?\n]))\s*(?:Do\s+not|Don't|Never|Avoid)\b[^.!?\n]*[.!]", re.I)


def clean_presentation(answer: str, question: str = "") -> str:
    """Remove what needs no rewriting: internal ids in headings and bracketed references, background tags, and the
    question's prohibitions echoed back as sentences."""
    text = _drop_echoed_instructions(answer or "", question)
    text = _ID_HEADING.sub(lambda m: m.group(1), text)
    text = re.sub(r"\s*\[\s*(?:q|req-?)\d+\s*\]", "", text)
    text = re.sub(r"\s*\((?:see\s+)?(?:q|req-?)\d+\)", "", text, flags=re.I)

    lines = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and _BG_TAG.search(line):
            lead = re.match(r"^(\s*(?:[-*]|\d+\.)?\s*)", line).group(1)
            starts_with_tag = bool(_BG_TAG.match(line[len(lead):]))
            line = _BG_TAG.sub("", line)
            if starts_with_tag:  # "established background: the natural ..." -> "The natural ..."
                rest = line[len(lead):]
                line = lead + rest[:1].upper() + rest[1:]
        lines.append(line)
    text = "\n".join(lines)
    text = _tidy_evidence_labels(text)
    # A bare "Executive Summary" line (no colon, no #) -> a heading; "Executive Summary: The system ..." as a run-in
    # label -> its own heading, like every other section.
    text = _SUMMARY_LINE.sub("### Executive Summary", text, count=1)
    return _SUMMARY_LABEL.sub(lambda m: "### Executive Summary\n\n" + m.group(1)[:1].upper() + m.group(1)[1:], text, count=1)


_PAREN_RE = re.compile(r"\s?\(([^()\n]{0,240})\)")
# "[Getachew et al., 2025 | DOI:10.1109/x] (DOI:10.1109/x; preprint)": the identifier written twice.
_CITED_THEN_ID_RE = re.compile(r"(\[[^\[\]\n]*?\|\s*([^\[\]\n|]+?)\s*\])\s*\(\s*([^();\n]+?)\s*(?:;\s*([^()\n]*?)\s*)?\)")


def _same_id(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"\s+", "", s).lower().rstrip(".")  # noqa: E731
    return norm(a) == norm(b)


def _tidy_evidence_labels(text: str) -> str:
    """Evidence labels a reader can use: an identifier repeated right after the citation that names it is dropped
    (its level stays), and "unclassified" (no level known) is dropped from a label. Code and math are untouched."""
    def tidy(segment: str) -> str:
        def unlabel(m: re.Match[str]) -> str:
            inner = m.group(1)
            if not re.search(r"\bunclassified\b", inner, re.I):
                return m.group(0)
            parts = [p.strip() for p in re.split(r"[;,]", inner)]
            kept = [p for p in parts if p and p.lower() != "unclassified"]
            return f"{m.group(0)[:1] if m.group(0)[:1].isspace() else ''}({'; '.join(kept)})" if kept else ""

        segment = _PAREN_RE.sub(unlabel, segment)

        def dedupe(m: re.Match[str]) -> str:
            if not _same_id(m.group(2), m.group(3)):
                return m.group(0)
            return m.group(1) + (f" ({m.group(4)})" if m.group(4) else "")

        return _CITED_THEN_ID_RE.sub(dedupe, segment)

    # Outside fenced code, inline code and math.
    parts = re.split(r"(```.*?```|`[^`\n]*`|\$\$.*?\$\$|\$[^$\n]*\$)", text, flags=re.S)
    return "".join(p if i % 2 else tidy(p) for i, p in enumerate(parts))


_SUMMARY_LINE = re.compile(r"(?m)^[ \t]*(?:\*\*|__)?Executive Summary(?:\*\*|__)?[ \t]*$")
_SUMMARY_LABEL = re.compile(r"(?m)^[ \t]*(?:\*\*)?Executive Summary(?:\*\*)?[ \t]*[:.—-][ \t]*(?:\*\*)?[ \t]*(\S.*)$")


__all__ = ["Issue", "clean_presentation", "outline_issues", "presentation_issues"]
