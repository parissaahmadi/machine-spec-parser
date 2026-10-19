"""machine-spec-parser: messy industrial datasheets in, clean validated specs out."""

from .models import Issue, IssueCode, QuantityValue, Severity, SpecField, SpecRecord
from .pipeline import RunReport, parse_html, run
from .store import Store

__all__ = [
    "Issue",
    "IssueCode",
    "QuantityValue",
    "RunReport",
    "Severity",
    "SpecField",
    "SpecRecord",
    "Store",
    "parse_html",
    "run",
]
__version__ = "0.1.0"
