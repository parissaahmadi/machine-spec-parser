"""Locale-tolerant number and quantity parsing.

The hard part of reading datasheets is not ``float()``; it is deciding what
``1,500``, ``1.500`` and ``11 000`` mean, and splitting ``5 - 10 bar``,
``7.5 ± 0.5 bar`` and ``75 kW (100 hp)`` into structured pieces.

Policy: when a number is genuinely ambiguous we pick the likeliest reading
*and flag it*, so a human can review instead of the pipeline silently guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

DecimalHint = Literal[".", ","]


class NumberParseError(ValueError):
    """The text looked numeric but could not be interpreted."""


# A number: digit groups separated by a space ("11 000") or plain digits with
# optional "." / "," separators. The lookbehinds stop us from reading the "3" in
# "m3/min" or the "1" in "min-1" as a standalone number.
_LETTERS = "A-Za-z\u0600-\u06ff"
NUM_PATTERN = (
    rf"(?<![{_LETTERS}])(?<![{_LETTERS}]-)"
    r"(?:\d{1,3}(?:[ ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*)"
)
_NUM = re.compile(NUM_PATTERN)


@dataclass(frozen=True)
class ParsedNumber:
    value: float
    ambiguous: bool = False


def parse_number(token: str, decimal_hint: DecimalHint | None = None) -> ParsedNumber:
    """Parse one numeric token.

    ``decimal_hint`` states which separator the page uses for decimals ("." for
    English/Persian pages, "," for most of continental Europe). Without a hint,
    a lone separator followed by exactly three digits (``1,500``) is ambiguous.
    """
    t = token.strip().replace(" ", "")
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", t):
        raise NumberParseError(f"not a number: {token!r}")

    seps = [c for c in t if c in ".,"]
    if not seps:
        return ParsedNumber(float(t))

    if "." in t and "," in t:  # the last separator is the decimal one
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        thou = "," if dec == "." else "."
        head, _, tail = t.rpartition(dec)
        if not all(len(g) == 3 for g in head.split(thou)[1:]):
            raise NumberParseError(f"inconsistent separators: {token!r}")
        return ParsedNumber(float(head.replace(thou, "") + "." + tail))

    sep = seps[0]
    parts = t.split(sep)
    if len(seps) > 1:  # "1,000,000": a repeated separator can only be thousands
        if not all(len(g) == 3 for g in parts[1:]):
            raise NumberParseError(f"inconsistent thousands groups: {token!r}")
        return ParsedNumber(float("".join(parts)))

    head, tail = parts
    if decimal_hint == sep:
        return ParsedNumber(float(f"{head}.{tail}"))
    looks_like_thousands = len(tail) == 3 and head != "0" and len(head) <= 3
    if decimal_hint is not None:  # the *other* separator is the decimal one
        if looks_like_thousands:
            return ParsedNumber(float(head + tail))
        return ParsedNumber(float(f"{head}.{tail}"), ambiguous=True)
    if looks_like_thousands:  # no hint: "1,500" / "1.500" could be either
        value = float(head + tail) if sep == "," else float(f"{head}.{tail}")
        return ParsedNumber(value, ambiguous=True)
    return ParsedNumber(float(f"{head}.{tail}"))


@dataclass(frozen=True)
class RawQuantity:
    """A quantity as written: numbers parsed, units still raw text."""

    kind: Literal["single", "range", "tolerance"]
    first: float
    second: float | None = None  # range upper bound, or the +/- tolerance
    unit: str = ""
    second_unit: str = ""        # only differs from ``unit`` for e.g. "400 V ±10%"
    ambiguous: bool = False


_PAREN_LETTER = re.compile(r"\(\s*([A-Za-z])\s*\)")  # dB(A) -> dBA, bar(g) -> barg
_PAIR_SEP = re.compile(
    r"^(?P<u>.*?)\s*(?P<sep>±|\+/-|\+-|–|—|~|-|to|\.\.\.?)\s*$", re.IGNORECASE
)


def _split_parentheses(text: str) -> tuple[str, list[str]]:
    """Return (text outside parentheses, [text inside each top-level group])."""
    main: list[str] = []
    groups: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
            if depth == 1:
                buf = []
                continue
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                groups.append("".join(buf))
                continue
        (buf if depth >= 1 else main).append(ch)
    if depth != 0:  # unbalanced: do not try to be clever
        return text, []
    return "".join(main), groups


def _is_sign(text: str, idx: int) -> bool:
    """Is the "-" at ``idx`` a minus sign (as opposed to a range separator)?"""
    before = text[:idx].rstrip().lower()
    return before == "" or before.endswith(("(", "~", "–", "—", "±")) or before.endswith("to")


def _find_numbers(seg: str, hint: DecimalHint | None) -> list[tuple[int, int, ParsedNumber]]:
    found: list[tuple[int, int, ParsedNumber]] = []
    for m in _NUM.finditer(seg):
        start, end = m.start(), m.end()
        number = parse_number(m.group(), hint)
        if start > 0 and seg[start - 1] == "-" and _is_sign(seg, start - 1):
            number = ParsedNumber(-number.value, number.ambiguous)
            start -= 1
        found.append((start, end, number))
    return found


def _parse_segment(seg: str, hint: DecimalHint | None) -> RawQuantity | None:
    nums = _find_numbers(seg, hint)
    if not nums:
        return None
    s1, e1, n1 = nums[0]
    after1 = seg[e1:].strip(" \t;,:.")

    if len(nums) >= 2:
        s2, e2, n2 = nums[1]
        between = seg[e1:s2]
        m = _PAIR_SEP.match(between)
        if m:
            u_between = m.group("u").strip(" \t;,:.")
            after2 = seg[e2:].strip(" \t;,:.")
            sep = m.group("sep").lower()
            ambiguous = n1.ambiguous or n2.ambiguous
            if sep in ("±", "+/-", "+-"):
                return RawQuantity(
                    "tolerance", n1.value, n2.value,
                    unit=u_between or after2, second_unit=after2 or u_between,
                    ambiguous=ambiguous,
                )
            unit = after2 or u_between
            return RawQuantity("range", n1.value, n2.value, unit, unit, ambiguous)
    return RawQuantity("single", n1.value, None, after1, after1, n1.ambiguous)


def parse_quantities(text: str, decimal_hint: DecimalHint | None = None) -> list[RawQuantity]:
    """Parse ``text`` into quantities; the first item is the primary reading.

    Parenthesised groups become *alternates* (``75 kW (100 hp)`` yields two
    quantities), which the caller can use to cross-check the primary value.
    ``text`` must already be cleaned with :func:`textnorm.clean`.
    """
    text = _PAREN_LETTER.sub(r"\1", text)
    main, groups = _split_parentheses(text)
    out: list[RawQuantity] = []
    for seg in (main, *groups):
        q = _parse_segment(seg, decimal_hint)
        if q is not None:
            out.append(q)
    return out
