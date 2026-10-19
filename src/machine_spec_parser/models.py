"""Data types: issues found while parsing, normalized values, and the final record."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    INFO = "info"        # worth knowing, nothing to fix
    WARNING = "warning"  # value kept, but a human should look
    ERROR = "error"      # value dropped or record rejected


class IssueCode(StrEnum):
    UNKNOWN_LABEL = "unknown_label"
    FUZZY_LABEL = "fuzzy_label"
    UNPARSEABLE_VALUE = "unparseable_value"
    MISSING_VALUE = "missing_value"
    UNIT_MISSING = "unit_missing"
    UNIT_MISMATCH = "unit_mismatch"
    AMBIGUOUS_NUMBER = "ambiguous_number"
    OUT_OF_RANGE = "out_of_range"
    CONFLICTING_VALUES = "conflicting_values"
    CALENDAR_CONVERTED = "calendar_converted"
    MISSING_MODEL = "missing_model"
    DUPLICATE_MODEL = "duplicate_model"
    FETCH_FAILED = "fetch_failed"


@dataclass(frozen=True)
class Issue:
    code: IssueCode
    severity: Severity
    message: str
    source: str
    label: str | None = None
    raw: str | None = None


def _fmt(x: float) -> str:
    return f"{x:.6g}"


@dataclass(frozen=True)
class QuantityValue:
    """A value in canonical units: a single number, a range, or value ± tolerance."""

    unit: str
    value: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    tolerance: float | None = None

    def representative(self) -> float | None:
        """One number standing for the whole quantity (the midpoint of a range)."""
        if self.value is not None:
            return self.value
        if self.minimum is not None and self.maximum is not None:
            return (self.minimum + self.maximum) / 2
        return None

    def display(self) -> str:
        suffix = f" {self.unit}" if self.unit else ""
        if self.value is not None:
            tol = f" ± {_fmt(self.tolerance)}" if self.tolerance is not None else ""
            return f"{_fmt(self.value)}{tol}{suffix}"
        if self.minimum is not None and self.maximum is not None:
            return f"{_fmt(self.minimum)}–{_fmt(self.maximum)}{suffix}"
        return "?"


@dataclass(frozen=True)
class SpecField:
    name: str
    raw_label: str
    raw_value: str
    quantity: QuantityValue | None = None
    text: str | None = None
    suspect: bool = False  # kept, but outside plausible bounds

    def display(self) -> str:
        if self.quantity is not None:
            return self.quantity.display()
        return self.text or ""


@dataclass
class SpecRecord:
    source: str
    manufacturer: str | None = None
    model: str | None = None
    model_key: str | None = None
    title: str | None = None
    category: str | None = None
    lang: str | None = None
    fields: dict[str, SpecField] = field(default_factory=dict)
    unmapped: list[tuple[str, str]] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def count(self, severity: Severity) -> int:
        return sum(1 for i in self.issues if i.severity is severity)

    @property
    def has_errors(self) -> bool:
        return self.count(Severity.ERROR) > 0
