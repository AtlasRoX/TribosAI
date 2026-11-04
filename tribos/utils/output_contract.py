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
    rf"|\b(?:in\s+)?{_N}\s+words?\s+or\s+(?:less|fewer)\b|\b{_N}[-\s]word\s+(?:limit|cap|answer|maximum|response)\b"
    rf"|\b(?:limited|capped|restricted)\s+to\s+{_N}\s+words?\b|\bword\s+(?:limit|cap|count\s+limit)\s+(?:of|is)\s+{_N}\b")
_MIN_WORDS_RE = re.compile(rf"(?i)\b(?:at\s+least|no\s+(?:fewer|less)\s+than|a\s+minimum\s+of|minimum(?:\s+of)?)\s+{_N}\s+words?\b")
# "220-250 words", "between 220 and 250 words", "220 to 250-word answer".
_WORD_RANGE_RE = re.compile(r"(?i)\b(?:between\s+(\d{1,4})\s+and\s+(\d{1,4})|(\d{1,4})\s*(?:-|–|—|to)\s*(\d{1,4}))[-\s]words?\b")
_EXACT_WORDS_RE = re.compile(rf"(?i)\b(?:in\s+)?exactly\s+{_N}\s+words?\b")
_EXACT_LINES_RE = re.compile(rf"(?i)\b(?:in\s+|on\s+|as\s+|using\s+)?exactly\s+{_N}\s+(?:separate\s+|non-?empty\s+)?lines?\b"
                             rf"|\b(?:in|on|as)\s+{_N}\s+lines?\s+(?:only|exactly)\b")
_EXACT_ITEMS_RE = re.compile(
    rf"(?i)\b(?:in\s+|as\s+|using\s+)?exactly\s+{_N}\s+(?:separate\s+|numbered\s+|bulleted\s+)?items?\b"
    rf"|\b(?:in|as)\s+{_N}\s+(?:numbered\s+|bulleted\s+)?items?\s+(?:only|exactly)\b"
    rf"|\b{_N}\s+numbered\s+items?\s+only\b"
)
_MAX_ITEMS_RE = re.compile(
    rf"(?i)\b(?:at\s+most|no\s+more\s+than|up\s+to|a\s+maximum\s+of|maximum(?:\s+of)?|max\.?)\s+{_N}\s+(?:separate\s+|numbered\s+|bulleted\s+)?items?\b"
    rf"|\b(?:in\s+)?{_N}\s+items?\s+or\s+(?:less|fewer)\b"
)
_NUMBERED_ITEMS_RE = re.compile(
    r"(?i)\b(?:as\s+)?(?:numbered\s+items?|numbered\s+list)\b|\bnumbered\s+(?:1\s*[-–—]\s*\d+|1\s+to\s+\d+)\b"
)
# "Give the solution set on one line": a single line ("each case on one line" is a per-item rule, see _per_item).
_ONE_LINE_RE = re.compile(r"(?i)\b(?:on|in|as)\s+(?:a\s+)?(?:single|one)\s+line\b")
# A limit stated without a number and removed: "there is no word limit", "ignore the length limit", multilingual forms.
_NO_WORD_LIMIT_RE = re.compile(
    r"(?i)\b(?:no|without(?:\s+(?:a|any))?|ignore\s+the|remove\s+the|drop\s+the|lift\s+the|forget\s+the)\s+"
    r"(?:previous\s+|earlier\s+|prior\s+)?(?:word|length|word[-\s]count)\s+(?:limit|cap|restriction|maximum|constraint)s?\b"
    r"|\b(?:sin|no\s+hay)\s+l[ií]mite\s+de\s+(?:\d+\s+)?palabras\b|\b(?:sans|pas\s+de)\s+limite\s+de\s+(?:\d+\s+)?mots\b"
    r"|\b(?:keine|ohne)\s+(?:\d+[-\s]?)?(?:wort|w[öo]rter)[-\s]?(?:grenze|begrenzung|limit)\b|\b(?:senza|nessun)\s+limite\s+di\s+(?:\d+\s+)?parole\b")
# Words that may stand between a removal cue and the limit it governs ("remove the previous 150-word limit").
_FILLER = (r"(?:the|a|an|any|that|this|these|those|previous(?:ly)?|earlier|prior|old|original|former|above|stated|given|"
           r"mentioned|my|your|our|strict|hard|initial|first|default|usual|instruction|instructions|requirement|request|"
           r"constraint|rule|to|about|answer|respond|write|keep|it|of|in|with|be|stay|limited|kept)")
_REVOKE_BEFORE_RE = re.compile(
    r"(?i)\b(?:no|not|without|ignore|ignoring|disregard|disregarding|drop|dropping|remove|removing|forget|cancel|"
    r"cancell?ing|lift|lifting|waive|waiving|scrap|override|overriding|replace|replacing|instead\s+of|rather\s+than|"
    r"never\s+mind|need(?:n't|\s+not)|(?:do|does)(?:n't|\s+not)(?:\s+(?:need|have\s+to))?|no\s+need\s+to|neither|nor)\b"
    rf"(?:\s+{_FILLER}\b){{0,6}}[\s\"'“‘(]*$")
_REVOKE_AFTER_RE = re.compile(
    r"(?i)^[\s\"'”’)]*(?:(?:limit|cap|rule|restriction|requirement|constraint|instruction|maximum)\s+)?"
    r"(?:no\s+longer\s+(?:applies|holds|matters|stands|exists)|does(?:n't|\s+not)\s+(?:apply|hold|matter)|"
    r"(?:is|was)\s+(?:now\s+)?(?:removed|lifted|cancell?ed|dropped|void|gone|withdrawn|not\s+(?:required|needed|necessary|binding))|"
    r"has\s+been\s+(?:removed|lifted|cancell?ed|dropped|withdrawn)|(?:is|are)\s+optional)")
_CLAUSE_BREAK_RE = re.compile(r"[.!?;:,\n]|\b(?:and|but|then|while|whereas|also)\b", re.I)
_EXAMPLE_RE = re.compile(r"(?i)\b(?:e\.g\.|for\s+example|for\s+instance|such\s+as)")
_QUOTED_RE = re.compile(r"\"[^\"\n]{1,400}\"|“[^”\n]{1,400}”|‘[^’\n]{1,400}’|`[^`\n]{1,400}`|(?<!\w)'[^'\n]{1,400}'(?!\w)")
_WORD_ATTRS = ("max_words", "exact_words", "min_words")
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
    min_words: int | None = None
    exact_words: int | None = None
    exact_lines: int | None = None
    max_lines: int | None = None
    exact_items: int | None = None
    max_items: int | None = None
    numbered_items: bool = False
    sentences: int | None = None
    plain_text: bool = False
    json_only: bool = False
    no_extra: bool = False
    preserve_whitespace: bool = False
    # Limits the request mentions but does not impose: removed, negated, quoted or given as an example. Kept so the
    # decision is visible ("150-word limit: removed by the request"), never enforced.
    inactive: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list, repr=False)

    @property
    def active(self) -> bool:
        return any((self.literal is not None, self.max_words, self.min_words, self.exact_words, self.exact_lines,
                    self.max_lines, self.exact_items is not None, self.max_items is not None, self.numbered_items,
                    self.sentences, self.plain_text, self.json_only, self.no_extra))

    @property
    def strict_form(self) -> bool:
        """The answer's form is fixed tightly enough that report sections, banners or appended notes break it."""
        return any((self.literal is not None, self.exact_lines, self.max_lines, self.exact_items is not None,
                    self.max_items is not None, self.numbered_items, self.json_only, self.no_extra,
                    self.plain_text, self.exact_words, (self.max_words or 10**9) <= 200,
                    (self.sentences or 10**9) <= 3))  # "answer in one sentence" fixes the form as tightly as one line

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("spans", None)
        return {k: v for k, v in d.items() if v not in (None, False, [])}

    def describe(self) -> str:
        """The contract as instructions for a writer model."""
        parts = []
        if self.literal is not None:
            parts.append("return exactly the requested text and nothing else")
        if self.exact_lines:
            parts.append(f"exactly {self.exact_lines} non-empty line(s)")
        if self.max_lines:
            parts.append(f"at most {self.max_lines} line(s)")
        if self.exact_items is not None:
            items_str = "numbered item(s)" if self.numbered_items else "item(s)"
            parts.append(f"exactly {self.exact_items} {items_str}")
        elif self.max_items is not None:
            items_str = "numbered item(s)" if self.numbered_items else "item(s)"
            parts.append(f"at most {self.max_items} {items_str}")
        elif self.numbered_items:
            parts.append("numbered items")
        if self.exact_words:
            parts.append(f"exactly {self.exact_words} words")
        if self.min_words and self.max_words:
            parts.append(f"between {self.min_words} and {self.max_words} words")
        elif self.max_words:
            parts.append(f"at most {self.max_words} words")
        elif self.min_words:
            parts.append(f"at least {self.min_words} words")
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


def _clause_before(text: str, start: int) -> str:
    seg = text[max(0, start - 160): start]
    return seg[max((m.end() for m in _CLAUSE_BREAK_RE.finditer(seg)), default=0):]


def _per_item(text: str, start: int, end: int) -> bool:
    """'each case on one line', 'one per line': a rule for every item, not a one-line answer."""
    return bool(re.search(r"(?i)\b(?:each|every|per)\b(?:\s+\S+){0,3}\s*$", _clause_before(text, start))
                or re.match(r"(?i)\s*(?:each|apiece|per\s+\w+)\b", text[end:]))


def _not_imposed(text: str, start: int, end: int, quoted: list[tuple[int, int]]) -> str | None:
    """Why a limit mentioned at text[start:end] is not a constraint on this answer, or None when it is one."""
    if any(a <= start and end <= b for a, b in quoted):
        return "quoted"
    before = text[max(0, start - 80): start]
    example = None
    for example in _EXAMPLE_RE.finditer(before):
        pass
    if example is not None and not re.search(r"[!?;\n]|(?<!e\.g)\.\s+[A-Z]", before[example.end():]):
        return "an example"
    if _REVOKE_BEFORE_RE.search(_clause_before(text, start)) or _REVOKE_AFTER_RE.match(text[end: end + 80]):
        return "removed or negated by the request"
    return None


def _apply_limits(c: Contract, text: str) -> None:
    """Numeric length rules in the order they are stated. A later rule replaces an earlier one of the same kind; a
    removal ("there is no 150-word limit", "remove the previous limit") cancels the earlier rule and imposes nothing;
    quoted or example limits ('classify "at most 50 words"') impose nothing."""
    events: list[tuple[int, int, str, Any]] = []
    for m in _ONE_LINE_RE.finditer(text):
        if not _per_item(text, m.start(), m.end()):
            events.append((m.start(), m.end(), "exact_lines", 1))
    for rx, attr in ((_EXACT_WORDS_RE, "exact_words"), (_MAX_WORDS_RE, "max_words"), (_MIN_WORDS_RE, "min_words"),
                     (_EXACT_LINES_RE, "exact_lines"), (_MAX_LINES_RE, "max_lines"),
                     (_EXACT_ITEMS_RE, "exact_items"), (_MAX_ITEMS_RE, "max_items"),
                     (_SENTENCES_RE, "sentences")):
        for m in rx.finditer(text):
            val = _num(next(g for g in m.groups() if g))
            events.append((m.start(), m.end(), attr, val))
            if "numbered" in m.group(0).lower():
                events.append((m.start(), m.end(), "numbered_items", True))
    for m in _WORD_RANGE_RE.finditer(text):
        lo, hi = sorted(int(g) for g in m.groups() if g)
        events.append((m.start(), m.end(), "word_range", (lo, hi)))
    for m in _NO_WORD_LIMIT_RE.finditer(text):
        events.append((m.start(), m.end(), "no_word_limit", None))
    for m in _NUMBERED_ITEMS_RE.finditer(text):
        events.append((m.start(), m.end(), "numbered_items", True))
    quoted = [m.span() for m in _QUOTED_RE.finditer(text)]
    for start, end, attr, value in sorted(events, key=lambda e: (e[0], -e[1])):
        mention = re.sub(r"\s+", " ", text[start:end].strip())
        reason = "removed by the request" if attr == "no_word_limit" else _not_imposed(text, start, end, quoted)
        if reason == "quoted":
            c.inactive.append(f"{mention}: quoted, not an instruction for this answer")
            continue
        c.spans.append((start, end))  # its numbers are about the answer's form either way, never problem data
        if reason is not None:
            c.inactive.append(f"{mention}: {reason}")
            if reason != "an example":
                for a in _WORD_ATTRS if attr in (*_WORD_ATTRS, "word_range", "no_word_limit") else (attr,):
                    setattr(c, a, None)
            continue
        if attr == "word_range":
            c.min_words, c.max_words, c.exact_words = value[0], value[1], None
        elif attr == "numbered_items":
            c.numbered_items = bool(value)
        else:
            setattr(c, attr, value)
    if c.min_words and c.max_words and c.min_words > c.max_words:
        c.inactive.append(f"at least {c.min_words} words: conflicts with at most {c.max_words}; the later rule applies")
        c.min_words = None


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
    _apply_limits(c, instructions)
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
_ITEM_START_RE = re.compile(
    r"(?m)^[ \t]{0,3}(?:(?:\d{1,3}[\.)]|\([0-9]{1,3}\)|\[[0-9]{1,3}\]|[-*•])\s+|[A-Za-z][\.)]\s+|Item\s+\d+[:.]\s+)",
)
_NUMBERED_START_RE = re.compile(
    r"(?m)^[ \t]{0,3}(?:(?:\d{1,3}[\.)]|\([0-9]{1,3}\)|\[[0-9]{1,3}\])\s+|Item\s+\d+[:.]\s+)",
)
_WARNING_BANNER_RE = re.compile(r"(?ms)^\s*>\s*⚠️[^\n]*\n(?:[ \t]*>.*?\n)*\s*")
_LIMITATIONS_BLOCK_RE = re.compile(r"(?ms)\n{2,}###\s+Evidence limitations\b.*$")


def extract_items(text: str) -> list[str]:
    """Returns top-level items extracted from a list in the text."""
    numbered = list(_NUMBERED_START_RE.finditer(text))
    if len(numbered) >= 2:
        matches = numbered
    else:
        matches = list(_ITEM_START_RE.finditer(text))
    if not matches:
        return []
    items: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        item_raw = text[start:end]
        if i == len(matches) - 1:
            paras = re.split(r"\n[ \t]*\n", item_raw)
            kept = [paras[0]]
            for p in paras[1:]:
                if p.startswith((" ", "\t", ">")) or re.match(r"^[ \t]*[-*•]\s+", p):
                    kept.append(p)
                else:
                    break
            item_raw = "\n\n".join(kept)
        items.append(item_raw.rstrip())
    return items


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
    if contract.exact_items is not None:
        items = extract_items(text)
        if len(items) != contract.exact_items:
            out.append(f"{len(items)} items, {contract.exact_items} required")
    if contract.max_items is not None:
        items = extract_items(text)
        if len(items) > contract.max_items:
            out.append(f"{len(items)} items, at most {contract.max_items} allowed")
    if contract.numbered_items:
        items = extract_items(text)
        if items and not all(_NUMBERED_START_RE.match(it) for it in items):
            out.append("items are not consistently numbered")
    words = word_count(text)
    if contract.max_words is not None and words > contract.max_words:
        out.append(f"{words} words, at most {contract.max_words} allowed")
    if contract.min_words is not None and words < contract.min_words:
        out.append(f"{words} words, at least {contract.min_words} required")
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
    when JSON only was asked, stripping injected banners when strict form is active, trimming extraneous prose
    for exact item contracts, and the literal payload when the answer contains exactly it plus wrapping."""
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
    if contract.strict_form:
        text = _WARNING_BANNER_RE.sub("", text).strip("\n")
        text = _LIMITATIONS_BLOCK_RE.sub("", text).strip("\n")
        if contract.exact_items is not None:
            matches = list(_ITEM_START_RE.finditer(text))
            if len(matches) >= contract.exact_items:
                start_pos = matches[0].start()
                last_idx = contract.exact_items - 1
                end_pos = matches[last_idx + 1].start() if last_idx + 1 < len(matches) else len(text)
                last_block = text[matches[last_idx].start():end_pos]
                paras = re.split(r"\n[ \t]*\n", last_block)
                kept = [paras[0]]
                for p in paras[1:]:
                    if p.startswith((" ", "\t", ">")):
                        kept.append(p)
                    else:
                        break
                actual_end = matches[last_idx].start() + len("\n\n".join(kept).rstrip())
                text = text[start_pos:actual_end].strip()
    if not contract.preserve_whitespace:
        text = text.strip()
    return text


__all__ = ["Contract", "conform", "extract", "extract_items", "mask_instructions", "nonempty_lines", "validate", "word_count", "writer_rule"]
