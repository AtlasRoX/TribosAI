"""
The output contract of a request: what the visible answer must look like, kept apart from what it must say.

"Answer in at most 40 words", "exactly two lines", "as plain text", "JSON only", "return exactly the following ...
and add nothing else" are instructions about the answer's form. They are extracted here once and carried through
generation, revision, final validation and rendering, so that:

- their numerals ("40", "2") are never read as mathematical inputs (mask_instructions);
- a literal-copy request is answered by a deterministic copy of the payload, with no template, research or critique
  (Contract.literal);
- the final text is checked against the contract after the last revision (validate), and the few repairs that cannot
  change the content (unwrapping a JSON fence, trimming surrounding blank lines) are applied deterministically (conform).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "a single": 1, "single": 1,
}
_N = r"(\d{1,4}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|hundred|a\s+single|single)"


def _num(token: str) -> int:
    token = re.sub(r"\s+", " ", token.strip().lower())
    return int(token) if token.isdigit() else _NUM_WORDS[token]


_MAX_WORDS_RE = re.compile(
    rf"(?i)\b(?:(?:in|with|using|within|keep\s+(?:it|the\s+answer)\s+(?:to|under))\s+)?(?:at\s+most|no\s+more\s+than|not\s+more\s+than|"
    rf"under|fewer\s+than|less\s+than|up\s+to|a\s+maximum\s+of|maximum(?:\s+of)?|max\.?)\s+{_N}\s+words?\b"
    rf"|\b(?:in\s+)?{_N}\s+words?\s+or\s+(?:less|fewer)\b|\b{_N}-word\s+(?:limit|answer|maximum|response)\b")
_EXACT_WORDS_RE = re.compile(rf"(?i)\b(?:in\s+)?exactly\s+{_N}\s+words?\b")
_EXACT_LINES_RE = re.compile(rf"(?i)\b(?:in\s+|on\s+|as\s+|using\s+)?exactly\s+{_N}\s+(?:separate\s+|non-?empty\s+)?lines?\b"
                             rf"|\b(?:in|on|as)\s+{_N}\s+lines?\s+(?:only|exactly)\b")
_MAX_LINES_RE = re.compile(rf"(?i)\b(?:in\s+|on\s+|within\s+)?(?:at\s+most|no\s+more\s+than|up\s+to)\s+{_N}\s+lines?\b")
_SENTENCES_RE = re.compile(rf"(?i)\b(?:in\s+)?(?:exactly\s+|at\s+most\s+|no\s+more\s+than\s+)?{_N}\s+sentences?\b")
_PLAIN_RE = re.compile(r"(?i)\bas\s+plain\s+text\b|\bin\s+plain\s+text\b|\bplain[-\s]text\s+only\b|\bno\s+markdown\b|"
                       r"\bwithout\s+(?:any\s+)?(?:markdown|formatting)\b")
_JSON_RE = re.compile(r"(?i)\b(?:valid\s+)?json[-\s]only\b|\bonly\s+(?:a\s+|the\s+)?(?:valid\s+)?json\b|"
                      r"\b(?:return|respond\s+with|reply\s+with|output|answer\s+with|give)\s+(?:only\s+)?(?:a\s+|the\s+)?(?:valid\s+)?json"
                      r"(?:\s+object|\s+array)?(?:\s+only)?\b")
_NO_EXTRA_RE = re.compile(
    r"(?i)\badd\s+nothing\s+(?:else|more)\b|\bnothing\s+else\b|\bno\s+(?:other|additional|extra)\s+(?:text|content|words|"
    r"commentary|explanation|lines?)\b|\bwithout\s+(?:any\s+)?(?:other\s+text|explanation|commentary|preamble)\b|"
    r"\bdo\s+not\s+(?:add|include)\s+(?:anything|any\s+(?:other\s+)?(?:text|explanation|commentary))\b")
_PRESERVE_RE = re.compile(r"(?i)\bpreserve\s+(?:the\s+)?(?:newlines?|line\s+breaks?|indentation|whitespace|spacing)\b")
_LITERAL_INTRO_RE = re.compile(
    r"(?is)\b(?:return|output|print|write|reply\s+with|respond\s+with|repeat|copy|reproduce|echo|type|give\s+back|send\s+back)"
    r"\s+(?:back\s+)?(?:exactly|verbatim|precisely|only|just)?\s*"
    r"(?:the\s+following|this|these|the\s+(?:text|lines?|string|block)\s+below|what\s+follows|the\s+following\s+\w+(?:\s+\w+){0,3})"
    r"\b[^\n:]*:[ \t]*")
_INSTRUCTION_TAIL_RE = re.compile(r"(?i)^\s*(?:do\s+not|don't|no\s+|add\s+nothing|preserve|keep\s+|make\s+sure|note:|(?:and\s+)?nothing\s+else)")


@dataclass
class Contract:
    literal: str | None = None  # exact payload to return, LF-normalised
    pure_copy: bool = False  # the whole request is "return this text": answered by copying it, with no other task
    max_words: int | None = None
    exact_words: int | None = None
    exact_lines: int | None = None
    max_lines: int | None = None
    sentences: int | None = None
    plain_text: bool = False
    json_only: bool = False
    no_extra: bool = False
    preserve_whitespace: bool = False
    spans: list[tuple[int, int]] = field(default_factory=list, repr=False)

    @property
    def active(self) -> bool:
        return any((self.literal is not None, self.max_words, self.exact_words, self.exact_lines, self.max_lines,
                    self.sentences, self.plain_text, self.json_only, self.no_extra))

    @property
    def strict_form(self) -> bool:
        """The answer's form is fixed tightly enough that report sections, banners or appended notes break it."""
        return any((self.literal is not None, self.exact_lines, self.max_lines, self.json_only, self.no_extra,
                    self.plain_text, self.exact_words, (self.max_words or 10**9) <= 200))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("spans", None)
        return {k: v for k, v in d.items() if v not in (None, False)}

    def describe(self) -> str:
        """The contract as instructions for a writer model."""
        parts = []
        if self.literal is not None:
            parts.append("return exactly the requested text and nothing else")
        if self.exact_lines:
            parts.append(f"exactly {self.exact_lines} non-empty line(s)")
        if self.max_lines:
            parts.append(f"at most {self.max_lines} line(s)")
        if self.exact_words:
            parts.append(f"exactly {self.exact_words} words")
        if self.max_words:
            parts.append(f"at most {self.max_words} words")
        if self.sentences:
            parts.append(f"{self.sentences} sentence(s)")
        if self.plain_text:
            parts.append("plain text without Markdown")
        if self.json_only:
            parts.append("valid JSON only, no code fence or prose")
        if self.no_extra:
            parts.append("no text beyond what was asked")
        return "; ".join(parts)


def writer_rule(contract: Contract | None) -> str:
    """The contract as the last instruction of a writer or reviser prompt ('' when the user fixed no form). It overrides
    the report template: a requested two-line answer gets two lines, not a report about them."""
    if contract is None or not contract.active:
        return ""
    head = ("\n\nOUTPUT CONTRACT - the user's explicit format. It overrides every structure, section, template, "
            "confidence-line, citation-format and length rule above: ")
    if contract.strict_form:
        return (head + contract.describe() + ". Write only the requested content: no headings, no Executive Summary, "
                "Result, Verification, Evidence or Confidence sections, and no notes about sources, tools or checks "
                "(the interface shows those separately).")
    return head + contract.describe() + "."


def _normalise_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _literal_payload(text: str) -> tuple[str | None, tuple[int, int] | None, str]:
    m = None
    for m in _LITERAL_INTRO_RE.finditer(text):
        break
    if m is None:
        return None, None, ""
    rest = text[m.end():]
    # The instruction may continue after the colon on the same line ("... plain text. Preserve the newline:").
    payload = rest.lstrip(" \t")
    if payload.startswith("\n"):
        payload = payload.lstrip("\n")
    lines = payload.split("\n")
    # Drop a trailing instruction paragraph ("Do not add anything else.").
    paras = re.split(r"\n[ \t]*\n", "\n".join(lines))
    tail: list[str] = []
    while len(paras) > 1 and _INSTRUCTION_TAIL_RE.match(paras[-1]):
        tail.insert(0, paras.pop())
    payload = "\n\n".join(paras).rstrip("\n ")
    payload = "\n".join(line.rstrip() for line in payload.split("\n"))
    fence = re.fullmatch(r"```[\w+-]*\n(.*?)\n```", payload, re.S)
    if fence:
        payload = fence.group(1)
    if not payload.strip() or len(payload) > 20_000:
        return None, None, ""
    return payload, (m.start(), m.end()), "\n\n".join(tail)


def extract(question: str) -> Contract:
    """The output contract stated in a question (an empty contract when there is none)."""
    text = _normalise_newlines(question)
    c = Contract()
    payload, span, tail = _literal_payload(text)
    instructions = text
    if payload is not None and span is not None:
        c.literal = payload
        c.spans.append(span)
        # Nothing but the copy instruction before the payload ("Return exactly ... :"), and nothing but instructions
        # after it: no other task is mixed in, so the answer is the payload itself.
        c.pure_copy = not text[: span[0]].strip() and "?" not in text[span[0]: span[1]]
        # Only the instructions (before the payload, plus a trailing instruction paragraph) are searched for further
        # rules, never the payload itself; the payload is blanked so spans keep their offsets.
        instructions = text[: span[1]] + " " * (len(text) - span[1] - len(tail)) + tail if tail else text[: span[1]]
    for rx, attr in ((_EXACT_WORDS_RE, "exact_words"), (_MAX_WORDS_RE, "max_words"), (_EXACT_LINES_RE, "exact_lines"),
                     (_MAX_LINES_RE, "max_lines"), (_SENTENCES_RE, "sentences")):
        for m in rx.finditer(instructions):
            token = next(g for g in m.groups() if g)
            if getattr(c, attr) is None:
                setattr(c, attr, _num(token))
            c.spans.append(m.span())
    for rx, attr in ((_PLAIN_RE, "plain_text"), (_JSON_RE, "json_only"), (_NO_EXTRA_RE, "no_extra"), (_PRESERVE_RE, "preserve_whitespace")):
        for m in rx.finditer(instructions):
            setattr(c, attr, True)
            c.spans.append(m.span())
    m = re.search(r"(?i)\b(?:following|these|the)\s+" + _N + r"\s+lines?\b", instructions)
    if c.literal is not None and c.exact_lines is None and m:
        c.exact_lines = _num(m.group(1))
    return c


def mask_instructions(text: str) -> str:
    """The text with its output-format instructions blanked (same length), so their numbers and words are not read as
    part of the problem: "Answer in at most 40 words" contributes no 40."""
    c = extract(text)
    if not c.spans:
        return text
    out = list(text)
    for a, b in c.spans:
        if c.literal is not None and (a, b) == c.spans[0]:
            continue  # the literal intro itself carries no numbers worth masking; its payload is handled by callers
        for i in range(a, min(b, len(out))):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def word_count(text: str) -> int:
    return len([t for t in re.split(r"\s+", text or "") if re.search(r"\w", t)])


def nonempty_lines(text: str) -> list[str]:
    return [line for line in _normalise_newlines(text).split("\n") if line.strip()]


_MARKDOWN_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s|\*\*[^*\n]+\*\*|^\s*```|^\s*>\s|^\s*\|.*\|\s*$|__[^_\n]+__")


def validate(answer: str, contract: Contract) -> list[str]:
    """Violations of the contract by the final answer text (empty when it conforms)."""
    text = _normalise_newlines(answer)
    out: list[str] = []
    if contract.literal is not None and text.strip("\n") != contract.literal:
        out.append("the answer is not exactly the requested text")
    if contract.exact_lines is not None and len(nonempty_lines(text)) != contract.exact_lines:
        out.append(f"{len(nonempty_lines(text))} non-empty lines, {contract.exact_lines} required")
    if contract.max_lines is not None and len(nonempty_lines(text)) > contract.max_lines:
        out.append(f"{len(nonempty_lines(text))} lines, at most {contract.max_lines} allowed")
    words = word_count(text)
    if contract.max_words is not None and words > contract.max_words:
        out.append(f"{words} words, at most {contract.max_words} allowed")
    if contract.exact_words is not None and words != contract.exact_words:
        out.append(f"{words} words, exactly {contract.exact_words} required")
    if contract.json_only:
        try:
            json.loads(text.strip())
        except ValueError:
            out.append("the answer is not valid JSON on its own")
    if contract.plain_text and _MARKDOWN_RE.search(text):
        out.append("the answer contains Markdown formatting")
    return out


def conform(answer: str, contract: Contract) -> str:
    """Repairs that cannot change the content: LF newlines, no surrounding blank lines, a JSON code fence unwrapped
    when JSON only was asked, and the literal payload when the answer contains exactly it plus wrapping."""
    text = _normalise_newlines(answer).strip("\n")
    if contract.literal is not None:
        if text.strip() == contract.literal.strip() or contract.literal in text:
            return contract.literal
        return text
    if contract.json_only:
        fence = re.fullmatch(r"\s*```(?:json)?\s*\n(.*?)\n\s*```\s*", text, re.S)
        if fence:
            try:
                json.loads(fence.group(1))
                return fence.group(1).strip()
            except ValueError:
                pass
    if not contract.preserve_whitespace:
        text = text.strip()
    return text


__all__ = ["Contract", "conform", "extract", "mask_instructions", "nonempty_lines", "validate", "word_count", "writer_rule"]
