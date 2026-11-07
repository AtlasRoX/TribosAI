"""
Field conventions an exercise assumes but does not state.

A textbook problem is written for readers who share its field's conventions: a bond's yield is a bond-equivalent rate
on semiannual coupons, "the one-month rate is 2%" is an annualised rate, a physical chemist's w is the work done on the
system, "ordered subsets" are the blocks counted by the Lah numbers. A solver that does not share them reaches a
correct answer to a different question. Each convention here is matched on the question's own words and passed to the
writer (and to the independent cross-check) as a short note: the reading to use, and that it should be stated.

Every entry is a standard convention of its field, never a rule written for one problem: the notes give the
definition and how to apply it, not any problem's answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Convention:
    key: str
    requires: tuple[re.Pattern[str], ...]  # every pattern must match the question
    note: str
    excludes: re.Pattern[str] | None = None  # the question opts out ("annual coupons", "strictly")


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


CONVENTIONS: tuple[Convention, ...] = (
    Convention(
        key="lah_ordered_subsets",
        requires=(_rx(r"\b(?:non-?empty\s+)?(?:linearly\s+)?ordered\s+(?:subsets|lists|blocks)\b"),
                  _rx(r"\b(?:divide|partition|split|distribute|break)\w*\b")),
        excludes=_rx(r"\bordered\s+(?:pairs?|tuples?|sequences?)\s+of\s+(?:subsets|sets)\b"),
        note=("COMBINATORICS TERM: dividing a set into k non-empty ordered subsets is the standard wording of the "
              "Lah numbers: each subset is itself ordered (a linearly ordered list), and the count is "
              "L(n, k) = C(n-1, k-1) * n! / k! (for example L(4, 2) = 36). It is not k! * S(n, k), which orders the "
              "collection of plain subsets. Use the Lah reading and name it."),
    ),
    Convention(
        key="bond_pricing",
        requires=(_rx(r"\bbonds?\b"), _rx(r"\b(?:price|priced|value|worth|pay)\b"),
                  _rx(r"\b(?:yields?|ytm|maturity|matur(?:e|es|ing)|discount\s+rate)\b")),
        excludes=_rx(r"\bannual(?:ly)?\s+(?:coupons?|payments?|interest)\b|\bcoupons?\s+(?:are\s+)?paid\s+annually\b"
                     r"|\bpays?\s+(?:interest|coupons?)\s+annually\b|\bzero[\s-]coupon\b"),
        note=("BOND CONVENTIONS (state them): unless the question says otherwise, a coupon bond pays its coupon "
              "semiannually and its yield is quoted as an annual rate compounded semiannually (bond-equivalent "
              "yield): use 2 x years periods, half the coupon rate and half the yield per period. When no face value "
              "is given, quote the price per 100 of face value (as a percentage of par), and give the per-1,000 "
              "figure only as a side note."),
    ),
    Convention(
        key="annualised_term_rates",
        requires=(_rx(r"\b(?:options?|calls?|puts?|forwards?|futures|put[\s-]call\s+parity|black[\s-]scholes)\b"),
                  _rx(r"\b(?:risk[\s-]free|interest)\s+rates?\b|\b\w+[\s-](?:month|year|week)\s+(?:risk[\s-]free\s+)?rate\b")),
        excludes=_rx(r"\bper\s+(?:month|period)\b|\bmonthly\s+rate\b|\beffective\s+(?:monthly|periodic)\b"),
        note=("RATE CONVENTION: an interest rate quoted for a term (\"the one-month risk-free rate is 2%\", \"the "
              "three-month rate is 4%\") is an annualised rate, as markets quote them; apply it over the term "
              "(T = 1/12 for one month). In option and forward pricing (put-call parity, Black-Scholes, cost of carry) "
              "discount with continuous compounding, PV(K) = K * exp(-r * T), unless the question names another "
              "compounding. State the reading."),
    ),
    Convention(
        key="chemistry_work_sign",
        # Physical chemistry only: its texts say "perfect gas" and work with reactions. A physics problem ("an ideal
        # gas expands; the work done by the gas") keeps the physics convention W = +integral p dV.
        requires=(_rx(r"\bwork\s+(?:done\s+)?(?:by|on)\s+the\s+(?:system|sample)\b|\bcalculate\s+(?:the\s+)?w\b"),
                  _rx(r"\bperfect\s+gas(?:es)?\b|\bgases\s+are\s+perfect\b|\bthermo(?:chemical|dynamic)\s+data\s+are\s+for\b|\breact(?:s|ion|ed|ing)?\b")),
        excludes=_rx(r"\bW\s*=\s*\+?\s*\\?int\s*p\b|\bpositive\s+(?:when|for)\s+(?:the\s+)?(?:gas|system)\s+expands\b"),
        note=("SIGN CONVENTION (physical chemistry, IUPAC): w is the energy transferred to the system as work, so a "
              "system that expands against an external pressure has w = -p_ext * dV < 0. Open with the signed value "
              "of w in this convention (\"w = -2.0 kJ: the system does 2.0 kJ of work on the surroundings\"), also "
              "when the question says \"work done by the system\"; do not open with the unsigned magnitude."),
    ),
    Convention(
        key="tcp_transfer_latency",
        requires=(_rx(r"\bTCP\b|\bslow[\s-]start\b|\bcongestion\s+(?:control|window)\b"),
                  _rx(r"\bRTT\b|\bround[\s-]trip\b"),
                  _rx(r"\bhow\s+long\b|\b(?:latency|delay|time)\b")),
        note=("NETWORK LATENCY MODEL (the standard textbook model of TCP transfer latency): count one RTT to open the "
              "TCP connection and one RTT for the request before the first data byte returns; each segment of S bits "
              "takes S/R to transmit at link rate R; in slow start the sender transmits a window of W segments and "
              "then idles for max(0, S/R + RTT - W * S/R) until the first ACK of that window returns, the window "
              "doubling each round (capped by the receiver window and ssthresh) until the whole object is sent. "
              "Latency = 2 RTT + O/R + the sum of the idle times. Build the window-by-window timeline and show it."),
    ),
    Convention(
        key="stereodescriptor_options",
        # Two or more candidate structures named with stereodescriptor sets, "(1R,2S,3R)-...", "(3aR,...,7aS)-...".
        # Case-sensitive: "(3s)" is a time.
        requires=(re.compile(r"(?:\((?:rel-)?\d{1,3}[a-z]?'*[RSEZ]\*?(?:\s*,\s*\d{1,3}[a-z]?'*[RSEZrs]\*?)+\)-[\s\S]*){2}"),),
        note=("STEREODESCRIPTORS: decide the product's geometry from the mechanism first (which groups end up cis or "
              "trans, syn or anti, endo or exo), and say why. Then match that geometry to the options through the "
              "<chemistry> ring-face results when they are present: they list, for each option's descriptor set, "
              "which substituents share a face of each ring, computed with the CIP rules. Do not assign R/S by hand "
              "when such a result exists; if none exists, assign each centre's CIP priorities explicitly, one centre "
              "at a time, and check that the descriptors of the chosen option give the geometry you derived."),
    ),
)


def conventions_for(question: str) -> list[Convention]:
    """The conventions the question's own words call for, in a fixed order."""
    text = question or ""
    out: list[Convention] = []
    for conv in CONVENTIONS:
        if conv.excludes is not None and conv.excludes.search(text):
            continue
        if all(p.search(text) for p in conv.requires):
            out.append(conv)
    return out


def convention_notes(question: str) -> list[str]:
    return [c.note for c in conventions_for(question)]


__all__ = ["CONVENTIONS", "Convention", "convention_notes", "conventions_for"]
