"""Row-level normalization: (label, raw value) -> validated, unit-normalized fields.

Principles
----------
* **Never guess a unit.** A bare ``460`` for "Voltage" is dropped with a
  ``UNIT_MISSING`` issue, unless the label says ``[V]`` or a unit column exists.
* **Flag, don't hide, doubtful numbers.** Ambiguous separators, implausible
  magnitudes and disagreeing alternates (``75 kW (90 hp)``) are kept or
  dropped according to severity, and always reported.
* **The unit decides what a label means** when the label is ambiguous
  ("Capacity: 440 cfm" is air flow, "Capacity: 3,500 kg" is a load rating).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .labels import FieldSpec, match_label, split_label
from .models import Issue, IssueCode, QuantityValue, Severity, SpecField
from .numbers import (
    NUM_PATTERN,
    DecimalHint,
    NumberParseError,
    RawQuantity,
    parse_number,
    parse_quantities,
)
from .textnorm import clean
from .units import CANONICAL_UNIT, UnitError, UnknownUnit, lookup, to_canonical

ALTERNATE_TOLERANCE = 0.03  # alternates (e.g. "(100 hp)") may differ from the primary by 3 %
PLACEHOLDERS = {"", "-", "–", "—", "n/a", "na", "tbd", "?", "none", "نامشخص"}
SOLAR_HIJRI_OFFSET = 621  # approximate: 1401 SH ≈ 2022 CE (the exact year depends on the month)

_LETTERS = re.compile(r"[^\W\d_]")
_DIM_SEPARATORS = re.compile(r"(?<=\d)\s*[x×*]\s*(?=\d)", re.IGNORECASE)
_DIMENSIONS = re.compile(
    rf"(?P<a>{NUM_PATTERN})\s*[x×*]\s*(?P<b>{NUM_PATTERN})\s*[x×*]\s*(?P<c>{NUM_PATTERN})"
    r"\s*(?P<u>.*)$",
    re.IGNORECASE,
)
_IP = re.compile(r"IP\s*([0-9X]{2})([A-DHMSWK])?", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")


@dataclass
class NormalizedRow:
    fields: list[SpecField] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    unmapped: bool = False


class _Ctx:
    """Everything one row needs, plus a helper to record issues."""

    def __init__(
        self,
        source: str,
        label: str,
        raw_value: str,
        lang: str | None,
        decimal_hint: DecimalHint | None,
        unit_hint: str | None,
    ) -> None:
        self.source, self.label, self.raw_value = source, label, raw_value
        self.lang, self.decimal_hint, self.unit_hint = lang, decimal_hint, unit_hint
        self.issues: list[Issue] = []

    def add(self, code: IssueCode, severity: Severity, message: str) -> None:
        self.issues.append(
            Issue(code, severity, message, self.source, label=self.label, raw=self.raw_value)
        )


def normalize_row(
    label: str,
    raw_value: str,
    *,
    source: str,
    lang: str | None = None,
    decimal_hint: DecimalHint | None = None,
    unit_cell: str | None = None,
) -> NormalizedRow:
    """Normalize one (label, value) pair. Never raises on bad data; reports issues."""
    parts = split_label(label)
    match = match_label(parts.base)
    if not match.candidates and parts.stripped != parts.base:
        match = match_label(parts.stripped)

    ctx = _Ctx(source, label, raw_value, lang, decimal_hint, parts.unit_hint)
    if not match.candidates:
        ctx.add(IssueCode.UNKNOWN_LABEL, Severity.INFO, f"no field for label {label!r}")
        return NormalizedRow(issues=ctx.issues, unmapped=True)
    if match.fuzzy_from:
        ctx.add(IssueCode.FUZZY_LABEL, Severity.INFO,
                f"label {label!r} matched approximately to {match.candidates[0].name}")

    value_text = clean(raw_value)
    if unit_cell and not _LETTERS.search(_DIM_SEPARATORS.sub(" ", value_text)):
        value_text = f"{value_text} {clean(unit_cell)}"

    kind = match.candidates[0].kind
    handler = {
        "quantity": _quantity,
        "int": _year,
        "ip": _ip,
        "text": _text,
        "dimensions": _dimensions,
    }[kind]
    fields = handler(match.candidates, value_text, ctx)
    return NormalizedRow(fields=fields, issues=ctx.issues)


# ----------------------------------------------------------------- quantities
def _convert(q: RawQuantity, unit_text: str, spec: FieldSpec) -> QuantityValue:
    dim = spec.dimension
    assert dim is not None
    canon = CANONICAL_UNIT[dim]
    if q.kind == "single":
        return QuantityValue(canon, value=to_canonical(q.first, unit_text, expected=dim))
    if q.kind == "range":
        lo = to_canonical(q.first, unit_text, expected=dim)
        hi = to_canonical(q.second or 0.0, unit_text, expected=dim)
        return QuantityValue(canon, minimum=min(lo, hi), maximum=max(lo, hi))
    value = to_canonical(q.first, unit_text, expected=dim)
    second = q.second or 0.0
    if q.second_unit.strip() == "%":
        tol = abs(value) * second / 100.0
    else:
        tol = to_canonical(second, q.second_unit or unit_text, expected=dim, delta=True)
    return QuantityValue(canon, value=value, tolerance=abs(tol))


def _quantity(candidates: list[FieldSpec], text: str, ctx: _Ctx) -> list[SpecField]:
    try:
        quantities = parse_quantities(text, ctx.decimal_hint)
    except NumberParseError as exc:
        ctx.add(IssueCode.UNPARSEABLE_VALUE, Severity.WARNING, str(exc))
        return []
    if not quantities:
        if text.strip().casefold() in PLACEHOLDERS:
            ctx.add(IssueCode.MISSING_VALUE, Severity.INFO, "value is a placeholder")
        else:
            ctx.add(IssueCode.UNPARSEABLE_VALUE, Severity.WARNING, "no number found")
        return []

    primary = quantities[0]
    unit_text = primary.unit or ctx.unit_hint
    if not unit_text:
        ctx.add(IssueCode.UNIT_MISSING, Severity.WARNING,
                "value has no unit; refusing to guess one")
        return []
    try:
        dim = lookup(unit_text).dimension
    except UnknownUnit:
        ctx.add(IssueCode.UNPARSEABLE_VALUE, Severity.WARNING, f"unknown unit {unit_text!r}")
        return []

    chosen = [c for c in candidates if c.dimension is dim]
    if not chosen:
        names = ", ".join(c.name for c in candidates)
        ctx.add(IssueCode.UNIT_MISMATCH, Severity.ERROR,
                f"unit {unit_text!r} measures {dim.value}, but the label maps to {names}")
        return []
    spec = chosen[0]

    try:
        qv = _convert(primary, unit_text, spec)
    except UnitError as exc:
        ctx.add(IssueCode.UNIT_MISMATCH, Severity.ERROR, str(exc))
        return []

    if primary.ambiguous:
        shown = qv.representative()
        ctx.add(IssueCode.AMBIGUOUS_NUMBER, Severity.WARNING,
                f"thousands/decimal separator is ambiguous; assumed {shown:g}")

    _cross_check_alternates(quantities[1:], qv, spec, ctx)

    suspect = False
    if spec.bounds is not None:
        lo, hi = spec.bounds
        values = [v for v in (qv.value, qv.minimum, qv.maximum) if v is not None]
        if any(v < lo or v > hi for v in values):
            suspect = True
            ctx.add(IssueCode.OUT_OF_RANGE, Severity.WARNING,
                    f"{qv.display()} is outside the plausible range {lo:g}–{hi:g} "
                    f"{CANONICAL_UNIT[dim]}")
    return [SpecField(spec.name, ctx.label, ctx.raw_value, quantity=qv, suspect=suspect)]


def _cross_check_alternates(
    alternates: list[RawQuantity], primary: QuantityValue, spec: FieldSpec, ctx: _Ctx
) -> None:
    """Compare ``75 kW (100 hp)``-style alternates against the primary value."""
    reference = primary.representative()
    dim = spec.dimension
    if reference is None or dim is None:
        return
    for alt in alternates:
        if alt.kind != "single" or not alt.unit:
            continue
        try:
            value = to_canonical(alt.first, alt.unit, expected=dim)
        except UnitError:
            continue  # e.g. "(approx.)" or a different quantity: nothing to compare
        if abs(value - reference) > max(ALTERNATE_TOLERANCE * abs(reference), 1e-6):
            diff = abs(value - reference) / abs(reference) * 100
            ctx.add(IssueCode.CONFLICTING_VALUES, Severity.WARNING,
                    f"alternate {alt.first:g} {alt.unit} = {value:.4g} "
                    f"{CANONICAL_UNIT[dim]} differs from the primary value "
                    f"{reference:.4g} by {diff:.1f}%; kept the primary")


# ---------------------------------------------------------- other field kinds
def _year(candidates: list[FieldSpec], text: str, ctx: _Ctx) -> list[SpecField]:
    spec = candidates[0]
    m = _YEAR.search(text)
    if not m:
        ctx.add(IssueCode.UNPARSEABLE_VALUE, Severity.WARNING, "no four-digit year found")
        return []
    year = int(m.group(1))
    if (ctx.lang or "").startswith("fa") and 1300 <= year <= 1500:
        converted = year + SOLAR_HIJRI_OFFSET
        ctx.add(IssueCode.CALENDAR_CONVERTED, Severity.INFO,
                f"Solar Hijri year {year} converted to about {converted} CE")
        year = converted
    suspect = False
    if spec.bounds and not (spec.bounds[0] <= year <= spec.bounds[1]):
        suspect = True
        ctx.add(IssueCode.OUT_OF_RANGE, Severity.WARNING, f"year {year} is implausible")
    return [SpecField(spec.name, ctx.label, ctx.raw_value,
                      quantity=QuantityValue("", value=float(year)), suspect=suspect)]


def _ip(candidates: list[FieldSpec], text: str, ctx: _Ctx) -> list[SpecField]:
    m = _IP.search(text)
    if not m:
        ctx.add(IssueCode.UNPARSEABLE_VALUE, Severity.WARNING, "no IP rating found")
        return []
    rating = f"IP{m.group(1).upper()}{(m.group(2) or '').upper()}"
    return [SpecField(candidates[0].name, ctx.label, ctx.raw_value, text=rating)]


def _text(candidates: list[FieldSpec], text: str, ctx: _Ctx) -> list[SpecField]:
    if text.strip().casefold() in PLACEHOLDERS:
        ctx.add(IssueCode.MISSING_VALUE, Severity.INFO, "value is a placeholder")
        return []
    return [SpecField(candidates[0].name, ctx.label, ctx.raw_value, text=text.strip())]


def _dimensions(candidates: list[FieldSpec], text: str, ctx: _Ctx) -> list[SpecField]:
    """``L × W × H`` becomes three fields in millimetres (order is assumed L, W, H)."""
    m = _DIMENSIONS.search(text)
    if not m:
        ctx.add(IssueCode.UNPARSEABLE_VALUE, Severity.WARNING, "expected 'L × W × H unit'")
        return []
    unit_text = m.group("u").strip(" .;,") or ctx.unit_hint
    if not unit_text:
        ctx.add(IssueCode.UNIT_MISSING, Severity.WARNING,
                "dimensions have no unit; refusing to guess one")
        return []
    spec = candidates[0]
    try:
        parsed = [parse_number(m.group(k), ctx.decimal_hint) for k in "abc"]
        values = [to_canonical(p.value, unit_text, expected=spec.dimension) for p in parsed]
    except NumberParseError as exc:
        ctx.add(IssueCode.UNPARSEABLE_VALUE, Severity.WARNING, str(exc))
        return []
    except UnknownUnit:
        ctx.add(IssueCode.UNPARSEABLE_VALUE, Severity.WARNING, f"unknown unit {unit_text!r}")
        return []
    except UnitError as exc:
        ctx.add(IssueCode.UNIT_MISMATCH, Severity.ERROR, str(exc))
        return []
    if any(p.ambiguous for p in parsed):
        ctx.add(IssueCode.AMBIGUOUS_NUMBER, Severity.WARNING,
                "thousands/decimal separator is ambiguous in the dimensions")

    out: list[SpecField] = []
    lo, hi = spec.bounds or (0, float("inf"))
    for name, value in zip(("length_mm", "width_mm", "height_mm"), values, strict=True):
        suspect = not (lo <= value <= hi)
        if suspect:
            ctx.add(IssueCode.OUT_OF_RANGE, Severity.WARNING, f"{name} = {value:.4g} mm")
        out.append(SpecField(name, ctx.label, ctx.raw_value,
                             quantity=QuantityValue("mm", value=value), suspect=suspect))
    return out
