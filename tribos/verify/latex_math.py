"""A small LaTeX math parser that builds SymPy expressions directly (no eval, no string parsing by SymPy).

It reads the notation answers are written in: fractions, roots, powers, sub- and superscripts, Greek letters,
elementary functions, implicit multiplication, dotted and primed derivatives, function application (x(t), x_p(t)),
definite integrals and sums. Anything else (matrices, limits, +-, ellipses) raises Unsupported, so a caller can mark
the statement as not checkable instead of guessing.

Function names are decided by the caller (`functions`): a known name followed by "(" is an application, a bare known
name is applied to the independent variable (so "k x" with x a function of t reads k*x(t)). Derivatives of a known
function are placeholders named "<name>__d<order>" that the caller resolves against its bindings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import sympy as sp


class Unsupported(ValueError):
    """The LaTeX uses notation this parser does not read; the statement is not checkable, not wrong."""


GREEK = {
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu", "nu",
    "xi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda",
    "Xi", "Sigma", "Upsilon", "Phi", "Psi", "Omega",
}
GREEK_ALIASES = {"varphi": "phi", "vartheta": "theta", "varepsilon": "epsilon", "varrho": "rho", "varsigma": "sigma",
                 "lambda": "lamda", "Lambda": "Lamda"}
_UNICODE = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ρ": "rho", "σ": "sigma", "τ": "tau",
    "φ": "phi", "ϕ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega", "Δ": "Delta", "Φ": "Phi", "Ω": "Omega",
    "π": "pi", "∞": "infty", "√": "sqrt", "≈": "approx", "≃": "simeq", "×": "times", "·": "cdot", "⋅": "cdot",
    "≤": "le", "≥": "ge", "≠": "neq", "±": "pm", "∫": "int", "∑": "sum", "⇒": "Rightarrow", "→": "to",
}
_UNICODE_SYMS = {"−": "-", "–": "-", "’": "'", "′": "'", "″": "''"}
_SUPERSCRIPTS = {"²": "2", "³": "3", "⁴": "4", "¹": "1", "⁰": "0", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}

FUNCTIONS = {
    "sqrt": sp.sqrt, "abs": sp.Abs, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "sec": sp.sec, "csc": sp.csc, "cot": sp.cot,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh, "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "ln": sp.log, "log": sp.log, "exp": sp.exp,
    "sgn": sp.sign, "sign": sp.sign, "Re": sp.re, "Im": sp.im,
}
# f^{-1} on a trigonometric or hyperbolic function is its inverse function.
_INVERSE = {sp.sin: sp.asin, sp.cos: sp.acos, sp.tan: sp.atan, sp.sec: sp.asec, sp.csc: sp.acsc, sp.cot: sp.acot,
            sp.sinh: sp.asinh, sp.cosh: sp.acosh, sp.tanh: sp.atanh}
TWO_ARG_FUNCTIONS = {"atan2": lambda y, x: sp.atan2(y, x), "arctan2": lambda y, x: sp.atan2(y, x)}
# Longest first, so "arctan2" is read before "arctan" and "atan2" before "atan".
_PLAIN_FUNCS = sorted({*FUNCTIONS, *TWO_ARG_FUNCTIONS, "sqrt", "abs", "pi"} - {"Re", "Im", "sec", "csc", "cot", "sign"},
                      key=len, reverse=True)

# Units that may trail a value; never read as variables when they follow a number in \mathrm{} or \text{}.
UNIT_RE = re.compile(
    r"^(?:[kMmμunGcd]?(?:m|s|g|N|J|W|Hz|Pa|V|A|K|rad|mol|L|Ω|ohm|eV)(?:\s*(?:\^|\*\*)?\s*\{?-?\d\}?)?"
    r"(?:\s*(?:/|\\cdot|·|\s)\s*[kMmμunGcd]?(?:m|s|g|N|J|W|Hz|Pa|V|A|K|rad|mol)(?:\s*\^?\s*\{?-?\d\}?)?)*"
    r"|deg|degrees?|°|\\circ|rad/s|s\^\{-1\}|%)$"
)
_WORD_FUNCS = {"atan2", "arctan2", "sgn", "sign", "Re", "Im", "exp", "ln", "log", "sin", "cos", "tan"}
_SPACING = {",", ";", "!", ":", " ", "quad", "qquad", "enspace", "thinspace", "medspace", "thickspace", "hspace",
            "displaystyle", "textstyle", "scriptstyle", "limits", "nolimits", "big", "Big", "bigg", "Bigg",
            "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr", "middle"}
RELATIONS = {"=": "eq", "approx": "approx", "simeq": "approx", "approxeq": "approx", "cong": "approx",
             "equiv": "eq", "coloneqq": "eq"}
INEQUALITIES = {"<", ">", "le", "leq", "ge", "geq", "neq", "ne", "lt", "gt", "ll", "gg", "propto", "sim", "in"}
SEPARATORS = {"quad", "qquad", "Longrightarrow", "implies", "Rightarrow", "iff", "Leftrightarrow", "therefore",
              "text_sep", "\\\\"}


@dataclass
class Tok:
    kind: str  # cmd | num | letter | sym | word | unit
    value: str


def tokenize(src: str) -> list[Tok]:
    """LaTeX source to tokens. Spacing commands become ("cmd", "quad"-like) only where they separate statements."""
    s = src
    for a, b in _UNICODE_SYMS.items():
        s = s.replace(a, b)
    out: list[Tok] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+)", s[i:])
            if m:
                name = m.group(1)
                i += len(m.group(0))
                if name in ("text", "mathrm", "textrm", "operatorname", "mathit", "mathbf", "rm", "textbf",
                            "textit", "mbox", "mathsf", "mathcal", "boldsymbol", "bm", "vec", "hat", "bar", "tilde"):
                    j = i
                    while j < n and s[j].isspace():
                        j += 1
                    if j < n and s[j] == "{":
                        depth, k = 0, j
                        while k < n:
                            if s[k] == "{":
                                depth += 1
                            elif s[k] == "}":
                                depth -= 1
                                if depth == 0:
                                    break
                            k += 1
                        content = s[j + 1:k].strip()
                        i = k + 1
                        if name in ("vec", "hat", "bar", "tilde", "boldsymbol", "bm", "mathbf", "mathit", "mathcal",
                                    "mathsf"):
                            out.extend(tokenize(content))  # decoration: the symbol itself
                        else:
                            out.append(Tok("word", content))
                        continue
                    if name == "rm":
                        continue
                    out.append(Tok("word", ""))
                    continue
                if name in ("left", "right"):
                    # The delimiter that follows is kept as an ordinary bracket; "\left." means none.
                    if i < n and s[i] == ".":
                        i += 1
                    continue
                if name in _SPACING and name not in ("quad", "qquad"):
                    continue
                out.append(Tok("cmd", name))
                continue
            nxt = s[i + 1:i + 2]
            if nxt == "\\":
                out.append(Tok("sym", "\\\\"))
            elif nxt in "{}":
                out.append(Tok("sym", nxt))
            elif nxt == "|":
                out.append(Tok("sym", "|"))
            elif nxt == "%":
                out.append(Tok("sym", "%"))
            # "\," "\;" "\!" "\ " ...: spacing
            i += 2
            continue
        if c == "⁻" and i + 1 < n and s[i + 1] in _SUPERSCRIPTS:
            # "s⁻¹", "10⁻⁶": a superscript exponent with its sign.
            j = i + 1
            digits = ""
            while j < n and s[j] in _SUPERSCRIPTS:
                digits += _SUPERSCRIPTS[s[j]]
                j += 1
            out.extend([Tok("sym", "^"), Tok("sym", "{"), Tok("sym", "-"), Tok("num", digits), Tok("sym", "}")])
            i = j
            continue
        # ASCII digits only: other Unicode digits (superscripts, other scripts) are handled above or are symbols.
        if (c.isascii() and c.isdigit()) or (c == "." and i + 1 < n and s[i + 1].isascii() and s[i + 1].isdigit()):
            m = re.match(r"\d*\.?\d+", s[i:])
            assert m is not None
            out.append(Tok("num", m.group(0)))
            i += len(m.group(0))
            continue
        if c in _SUPERSCRIPTS:
            out.extend([Tok("sym", "^"), Tok("num", _SUPERSCRIPTS[c])])
            i += 1
            continue
        if c in _UNICODE:
            out.append(Tok("cmd", _UNICODE[c]))
            i += 1
            continue
        if c.isascii() and c.isalpha():
            # Function names written without a backslash ("cos(4t)", "sqrt(2)", "atan2(y, x)") are functions, not
            # products of letters; any other run of letters is a product of single-letter symbols.
            m = re.match(r"[A-Za-z]+\d?", s[i:])
            run = m.group(0) if m else c
            word = next((w for w in _PLAIN_FUNCS if run.startswith(w) and (w[-1].isdigit() or not run[len(w):len(w) + 1].isdigit())), None)
            if word is not None and (i == 0 or not s[i - 1].isalpha()):
                out.append(Tok("word", word))
                i += len(word)
                continue
            out.append(Tok("letter", c))
            i += 1
            continue
        out.append(Tok("sym", c))
        i += 1
    return out


@dataclass
class ParseContext:
    """What the parser needs to know about names: which are functions, the independent variable, symbol renames."""

    functions: set[str] = field(default_factory=set)
    variable: str = "t"
    symbols: set[str] = field(default_factory=set)  # declared local symbols that shadow conventional aliases
    imaginary_i: bool = True
    decimals: list[str] = field(default_factory=list)  # decimal literals seen (for tolerances)
    has_function_refs: bool = False  # an explicit application f(...) or derivative of a known function
    bare_function_refs: bool = False  # a known function used without an argument (an unknown in an equation)
    # \log with no base: natural (log_base None) or the base given here; bare_log records that one was read, so a
    # caller can check the claim under both conventions (\ln is always natural, \log_{b} always base b).
    log_base: int | None = None
    bare_log: bool = False


def deriv_name(base: str, order: int) -> str:
    return f"{base}__d{order}"


def split_deriv(name: str) -> tuple[str, int] | None:
    m = re.fullmatch(r"(.+)__d(\d+)", name)
    return (m.group(1), int(m.group(2))) if m else None


class _Parser:
    def __init__(self, toks: list[Tok], ctx: ParseContext) -> None:
        self.t = toks
        self.i = 0
        self.ctx = ctx

    # -- token helpers -------------------------------------------------------------------------------------------------
    def peek(self, k: int = 0) -> Tok | None:
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def next(self) -> Tok:
        tok = self.peek()
        if tok is None:
            raise Unsupported("unexpected end of expression")
        self.i += 1
        return tok

    def at(self, kind: str, value: str | None = None, k: int = 0) -> bool:
        tok = self.peek(k)
        return tok is not None and tok.kind == kind and (value is None or tok.value == value)

    def expect(self, kind: str, value: str) -> None:
        tok = self.next()
        if tok.kind != kind or tok.value != value:
            raise Unsupported(f"expected {value!r}, got {tok.value!r}")

    # -- grammar -------------------------------------------------------------------------------------------------------
    def parse(self) -> sp.Expr:
        e = self.expr()
        if self.peek() is not None:
            raise Unsupported(f"unread input from {self.peek().value!r}")  # type: ignore[union-attr]
        return e

    def expr(self) -> sp.Expr:
        e = self.term()
        while self.at("sym", "+") or self.at("sym", "-"):
            op = self.next().value
            rhs = self.term()
            e = e + rhs if op == "+" else e - rhs
        return e

    def starts_atom(self) -> bool:
        tok = self.peek()
        if tok is None:
            return False
        if tok.kind in ("num", "letter"):
            return True
        if tok.kind == "sym":
            return tok.value in ("(", "[", "{", "|")
        if tok.kind == "word":
            w = tok.value.strip()
            return (w in _WORD_FUNCS or w in FUNCTIONS or w in TWO_ARG_FUNCTIONS or w in ("e", "d", "i", "pi")
                    or bool(re.fullmatch(r"[A-Za-z]", w)))
        if tok.kind == "cmd":
            v = tok.value
            return (v in FUNCTIONS or v in GREEK or v in GREEK_ALIASES or v in TWO_ARG_FUNCTIONS
                    or v in ("frac", "dfrac", "tfrac", "cfrac", "sqrt", "pi", "infty", "dot", "ddot", "int", "sum",
                             "exp", "lvert", "lfloor", "lceil", "binom"))
        return False

    def term(self) -> sp.Expr:
        f = self.unary()
        while True:
            if self.at("sym", "*") or self.at("cmd", "cdot") or self.at("cmd", "times"):
                self.next()
                f = f * self.unary()
            elif self.at("sym", "/") or self.at("cmd", "div"):
                self.next()
                f = f / self.unary()
            elif self.starts_atom():
                f = f * self.power()
            else:
                return f

    def unary(self) -> sp.Expr:
        if self.at("sym", "-"):
            self.next()
            return -self.unary()
        if self.at("sym", "+"):
            self.next()
            return self.unary()
        return self.power()

    def power(self) -> sp.Expr:
        base = self.atom()
        while True:
            if self.at("sym", "*") and self.at("sym", "*", 1):
                self.next()
                self.next()
                base = sp.Pow(base, self.unary())
            elif self.at("sym", "^"):
                self.next()
                exp = self.script_arg()
                base = sp.Pow(base, exp)
            elif self.at("sym", "!"):
                self.next()
                base = sp.factorial(base)
            elif self.at("sym", "%"):
                self.next()
                base = base / 100
            else:
                return base

    def script_arg(self) -> sp.Expr:
        """The argument of ^ or _: a braced group, or one token (one digit of a number)."""
        if self.at("sym", "{"):
            return self.group("{", "}")
        if self.at("sym", "-"):
            self.next()
            return -self.script_arg()
        tok = self.peek()
        if tok is not None and tok.kind == "num" and len(tok.value) > 1 and "." not in tok.value:
            self.t[self.i] = Tok("num", tok.value[1:])
            return sp.Integer(int(tok.value[0]))
        return self.atom()

    def group(self, open_: str, close: str) -> sp.Expr:
        self.expect("sym", open_)
        start = self.i
        depth = 0
        while self.i < len(self.t):
            tok = self.t[self.i]
            if tok.kind == "sym" and tok.value in ("(", "[", "{"):
                depth += 1
            elif tok.kind == "sym" and tok.value in (")", "]", "}"):
                if depth == 0:
                    break
                depth -= 1
            self.i += 1
        inner = self.t[start:self.i]
        self.expect("sym", close)
        return _Parser(inner, self.ctx).parse_inner()

    def parse_inner(self) -> sp.Expr:
        if not self.t:
            raise Unsupported("empty group")
        return self.parse()

    def raw_group(self) -> list[Tok]:
        """The tokens of a braced group (or one token) without parsing them."""
        if self.at("sym", "{"):
            self.next()
            start, depth = self.i, 0
            while self.i < len(self.t):
                tok = self.t[self.i]
                if tok.kind == "sym" and tok.value == "{":
                    depth += 1
                elif tok.kind == "sym" and tok.value == "}":
                    if depth == 0:
                        break
                    depth -= 1
                self.i += 1
            inner = self.t[start:self.i]
            self.expect("sym", "}")
            return inner
        tok = self.peek()
        if tok is not None and tok.kind == "num" and len(tok.value) > 1 and "." not in tok.value:
            # "\frac34" is 3/4: an unbraced argument is one digit.
            self.t[self.i] = Tok("num", tok.value[1:])
            return [Tok("num", tok.value[0])]
        return [self.next()]

    def args(self) -> list[sp.Expr]:
        """Comma-separated arguments of an application f( ... )."""
        self.expect("sym", "(")
        parts: list[list[Tok]] = [[]]
        depth = 0
        while True:
            tok = self.next()
            if tok.kind == "sym" and tok.value in ("(", "[", "{"):
                depth += 1
            elif tok.kind == "sym" and tok.value in (")", "]", "}"):
                if depth == 0:
                    if tok.value != ")":
                        raise Unsupported("unbalanced brackets")
                    break
                depth -= 1
            if tok.kind == "sym" and tok.value == "," and depth == 0:
                parts.append([])
                continue
            parts[-1].append(tok)
        return [_Parser(p, self.ctx).parse_inner() for p in parts]

    def identifier_suffix(self, name: str) -> str:
        if self.at("sym", "_"):
            self.next()
            sub = self.raw_group()
            text = "".join(GREEK_ALIASES.get(t.value, t.value) if t.kind == "cmd" else t.value for t in sub
                           if t.kind in ("letter", "num", "cmd", "word"))
            text = re.sub(r"[^A-Za-z0-9]", "", text)
            if not text:
                raise Unsupported("empty subscript")
            name = f"{name}_{text}"
        return name

    def name_atom(self, name: str, order: int = 0) -> sp.Expr:
        """A symbol or function name, with subscript, primes and an optional application."""
        name = self.identifier_suffix(name)
        while self.at("sym", "'"):
            self.next()
            order += 1
        is_fn = name in self.ctx.functions
        if order and not is_fn:
            raise Unsupported(f"derivative of unknown function {name}")
        if is_fn:
            fname = deriv_name(name, order) if order else name
            if self.at("sym", "("):
                args = self.args()
                self.ctx.has_function_refs = True
                return sp.Function(fname)(*args)
            self.ctx.bare_function_refs = True
            return sp.Function(fname)(sp.Symbol(self.ctx.variable))
        if name in TWO_ARG_FUNCTIONS and self.at("sym", "("):
            a = self.args()
            if len(a) != 2:
                raise Unsupported(f"{name} takes two arguments")
            return TWO_ARG_FUNCTIONS[name](*a)
        if name in FUNCTIONS and self.at("sym", "("):
            return FUNCTIONS[name](*self.args())
        if name in self.ctx.symbols or name == self.ctx.variable:
            return sp.Symbol(name)
        if name == "i" and self.ctx.imaginary_i:
            return sp.I
        return sp.Symbol(name)

    def function_call(self, fn: Any, name: str = "") -> sp.Expr:
        power = base = None
        for _ in range(2):  # "\log_{10}", "\sin^2", "\log_2^2": a base and a power in either order
            if self.at("sym", "^") and power is None:
                self.next()
                power = self.script_arg()
            elif self.at("sym", "_") and base is None and name == "log":
                self.next()
                base = self.script_arg()
        if power is not None and power == -1 and fn in _INVERSE:
            # "\tan^{-1}(1)" is arctan(1), not 1/tan(1); "\sin^2 x" stays a power.
            fn, power = _INVERSE[fn], None
        if self.at("sym", "(") or self.at("sym", "["):
            close = ")" if self.at("sym", "(") else "]"
            arg = self.group(self.peek().value, close)  # type: ignore[union-attr]
        elif self.at("sym", "{"):
            arg = self.group("{", "}")
        else:
            # "\cos 4t": the argument runs over the following factors, up to + - or another function.
            f = self.power()
            while self.starts_atom() and not (self.at("cmd") and self.peek().value in FUNCTIONS):  # type: ignore[union-attr]
                f = f * self.power()
            arg = f
        if base is not None:
            out = sp.log(arg, base)
        elif name == "log":
            self.ctx.bare_log = True
            out = sp.log(arg) if self.ctx.log_base is None else sp.log(arg, self.ctx.log_base)
        else:
            out = fn(arg)
        return out ** power if power is not None else out

    def atom(self) -> sp.Expr:
        tok = self.next()
        if tok.kind == "num":
            if "." in tok.value:
                self.ctx.decimals.append(tok.value)
            return sp.Rational(tok.value)
        if tok.kind == "sym":
            if tok.value == "(":
                self.i -= 1
                return self.group("(", ")")
            if tok.value == "[":
                self.i -= 1
                return self.group("[", "]")
            if tok.value == "{":
                self.i -= 1
                return self.group("{", "}")
            if tok.value == "|":
                start, depth = self.i, 0
                while self.i < len(self.t) and not (self.t[self.i].kind == "sym" and self.t[self.i].value == "|"
                                                    and depth == 0):
                    if self.t[self.i].kind == "sym" and self.t[self.i].value in "([{":
                        depth += 1
                    elif self.t[self.i].kind == "sym" and self.t[self.i].value in ")]}":
                        depth -= 1
                    self.i += 1
                inner = self.t[start:self.i]
                self.expect("sym", "|")
                return sp.Abs(_Parser(inner, self.ctx).parse_inner())
            raise Unsupported(f"unexpected {tok.value!r}")
        if tok.kind == "letter":
            if tok.value == "e" and self.at("sym", "^"):
                return sp.E
            return self.name_atom(tok.value)
        if tok.kind == "word":
            w = tok.value.strip()
            if w == "e":
                return sp.E
            if w == "pi":
                return sp.pi
            if w in TWO_ARG_FUNCTIONS and self.at("sym", "("):
                a = self.args()
                if len(a) != 2:
                    raise Unsupported(f"{w} takes two arguments")
                return TWO_ARG_FUNCTIONS[w](*a)
            if w in FUNCTIONS:
                return self.function_call(FUNCTIONS[w], w)
            if re.fullmatch(r"[A-Za-z]", w):
                return self.name_atom(w)
            raise Unsupported(f"text {w!r}")
        if tok.kind == "cmd":
            v = tok.value
            if v in ("frac", "dfrac", "tfrac", "cfrac"):
                return self.fraction()
            if v == "binom":
                a, b = self.script_arg(), self.script_arg()
                return sp.binomial(a, b)
            if v == "sqrt":
                index = None
                if self.at("sym", "["):
                    index = self.group("[", "]")
                arg = self.script_arg()
                return sp.sqrt(arg) if index is None else sp.root(arg, index)
            if v in TWO_ARG_FUNCTIONS and self.at("sym", "("):
                a = self.args()
                return TWO_ARG_FUNCTIONS[v](*a)
            if v in FUNCTIONS:
                return self.function_call(FUNCTIONS[v], v)
            if v == "pi":
                return sp.pi
            if v == "infty":
                return sp.oo
            if v in ("dot", "ddot"):
                base = self.raw_group()
                if len(base) != 1 or base[0].kind not in ("letter", "cmd"):
                    raise Unsupported("dot over a non-symbol")
                b = base[0].value if base[0].kind == "letter" else GREEK_ALIASES.get(base[0].value, base[0].value)
                return self.name_atom(b, order=1 if v == "dot" else 2)
            if v in GREEK or v in GREEK_ALIASES:
                return self.name_atom(GREEK_ALIASES.get(v, v))
            if v == "int":
                return self.integral()
            if v == "sum":
                return self.summation()
            if v in ("lvert",):
                self.i -= 1
                raise Unsupported("\\lvert")
        raise Unsupported(f"unsupported token {tok.value!r}")

    def fraction(self) -> sp.Expr:
        num_toks = self.raw_group()
        den_toks = self.raw_group()
        # d/dt, dx/dt, d^2x/dt^2
        if num_toks and _is_d(num_toks[0]) and den_toks and _is_d(den_toks[0]):
            order = 1
            rest = num_toks[1:]
            if rest and rest[0].kind == "sym" and rest[0].value == "^":
                order = int(rest[1].value) if len(rest) > 1 and rest[1].kind == "num" else 0
                rest = rest[2:]
            var_toks = [t for t in den_toks[1:] if t.kind in ("letter", "cmd")]
            if not order or len(var_toks) != 1:
                raise Unsupported("derivative notation")
            var = var_toks[0].value
            if not rest:
                # \frac{d}{dt} applies to what follows.
                target = self.power()
                return sp.Derivative(target, sp.Symbol(var), order)
            sub = _Parser(rest, self.ctx)
            f = sub.parse_inner()
            if isinstance(f, sp.core.function.AppliedUndef):
                name = type(f).__name__
                self.ctx.has_function_refs = True
                return sp.Function(deriv_name(name, order))(*f.args)
            return sp.Derivative(f, sp.Symbol(var), order)
        num = _Parser(num_toks, self.ctx).parse_inner()
        den = _Parser(den_toks, self.ctx).parse_inner()
        return num / den

    def integral(self) -> sp.Expr:
        lo = hi = None
        for _ in range(2):
            if self.at("sym", "_"):
                self.next()
                lo = self.script_arg()
            elif self.at("sym", "^"):
                self.next()
                hi = self.script_arg()
        # The integrand runs to the differential "d<var>" at depth 0.
        start, depth = self.i, 0
        while self.i < len(self.t):
            tok = self.t[self.i]
            if tok.kind == "sym" and tok.value in "([{":
                depth += 1
            elif tok.kind == "sym" and tok.value in ")]}":
                depth -= 1
            elif depth == 0 and _is_d(tok) and self.i + 1 < len(self.t) and self.t[self.i + 1].kind in ("letter", "cmd"):
                break
            self.i += 1
        if self.i >= len(self.t):
            raise Unsupported("integral without a differential")
        integrand = _Parser(self.t[start:self.i], self.ctx).parse_inner()
        self.next()
        var_tok = self.next()
        var = sp.Symbol(GREEK_ALIASES.get(var_tok.value, var_tok.value))
        if lo is None or hi is None:
            raise Unsupported("indefinite integral")
        return sp.Integral(integrand, (var, lo, hi))

    def summation(self) -> sp.Expr:
        if not self.at("sym", "_"):
            raise Unsupported("sum without bounds")
        self.next()
        sub = self.raw_group()
        eq = next((k for k, t in enumerate(sub) if t.kind == "sym" and t.value == "="), None)
        if eq is None or eq != 1 or sub[0].kind != "letter":
            raise Unsupported("sum index")
        var = sp.Symbol(sub[0].value)
        lo = _Parser(sub[2:], self.ctx).parse_inner()
        if not self.at("sym", "^"):
            raise Unsupported("sum without upper bound")
        self.next()
        hi = self.script_arg()
        body = self.term()
        return sp.Sum(body, (var, lo, hi))  # type: ignore[return-value]


def _is_d(tok: Tok) -> bool:
    return (tok.kind == "letter" and tok.value == "d") or (tok.kind == "word" and tok.value.strip() == "d")


def parse_tokens(toks: list[Tok], ctx: ParseContext) -> sp.Expr:
    if not toks:
        raise Unsupported("empty expression")
    return _Parser(list(toks), ctx).parse()


def parse_latex(src: str, ctx: ParseContext | None = None) -> sp.Expr:
    return parse_tokens(tokenize(src), ctx or ParseContext())


def is_unit_word(text: str) -> bool:
    return bool(UNIT_RE.match(text.strip().replace(" ", "")))


__all__ = [
    "FUNCTIONS",
    "INEQUALITIES",
    "RELATIONS",
    "SEPARATORS",
    "ParseContext",
    "Tok",
    "Unsupported",
    "deriv_name",
    "is_unit_word",
    "parse_latex",
    "parse_tokens",
    "split_deriv",
    "tokenize",
]
