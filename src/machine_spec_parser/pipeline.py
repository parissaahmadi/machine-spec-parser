"""Glue: page HTML -> ``SpecRecord``, and a batch runner with fetching and de-duplication."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .fetch import Fetcher, FetchFailed, RateLimiter, RetryPolicy, fetch_with_retry
from .html_table import extract_document
from .models import Issue, IssueCode, Severity, SpecField, SpecRecord
from .names import identify_model
from .normalize import normalize_row
from .numbers import DecimalHint

# Languages whose pages normally write "1.234,5" (comma = decimal separator).
COMMA_DECIMAL_LANGS = frozenset(
    {"de", "fr", "es", "it", "pt", "nl", "tr", "ru", "pl", "cs", "sv", "da", "nb", "fi"}
)
DOT_DECIMAL_LANGS = frozenset({"en", "fa", "ja", "zh", "ko", "he"})
DUPLICATE_TOLERANCE = 0.01


def decimal_hint_for(lang: str | None) -> DecimalHint | None:
    """Which decimal separator does a page in ``lang`` use? ``None`` if we cannot tell."""
    code = (lang or "").lower().replace("_", "-").split("-")[0]
    if code in COMMA_DECIMAL_LANGS:
        return ","
    if code in DOT_DECIMAL_LANGS:
        return "."
    return None


def _same_value(a: SpecField, b: SpecField) -> bool:
    if a.quantity and b.quantity:
        x, y = a.quantity.representative(), b.quantity.representative()
        if x is None or y is None:
            return False
        return abs(x - y) <= DUPLICATE_TOLERANCE * max(abs(x), abs(y), 1e-9)
    return (a.text or "") == (b.text or "")


def parse_html(html: str, source: str) -> SpecRecord:
    """Parse one datasheet page. Pure function: no I/O, no clock."""
    doc = extract_document(html)
    lang = doc.lang.lower() if doc.lang else None
    hint = decimal_hint_for(lang)

    identity = identify_model(doc.h1) if doc.h1 else identify_model(doc.title)
    if identity.key is None and doc.title:  # the heading may be generic ("Specifications")
        identity = identify_model(doc.title)

    record = SpecRecord(
        source=source,
        manufacturer=identity.manufacturer,
        model=identity.model,
        model_key=identity.key,
        title=doc.h1 or doc.title,
        category=doc.meta.get("category"),
        lang=lang,
    )
    if identity.key is None:
        record.issues.append(Issue(
            IssueCode.MISSING_MODEL, Severity.ERROR,
            "could not identify a model name in the page heading or title", source))

    for row in doc.rows:
        result = normalize_row(
            row.label, row.value, source=source, lang=lang, decimal_hint=hint,
            unit_cell=row.unit_cell,
        )
        record.issues.extend(result.issues)
        if result.unmapped:
            record.unmapped.append((row.label, row.value))
        for fld in result.fields:
            existing = record.fields.get(fld.name)
            if existing is None:
                record.fields[fld.name] = fld
            elif not _same_value(existing, fld):
                record.issues.append(Issue(
                    IssueCode.CONFLICTING_VALUES, Severity.WARNING,
                    f"{fld.name} appears twice with different values "
                    f"({existing.display()} vs {fld.display()}); kept the first",
                    source, label=row.label, raw=row.value))
    return record


@dataclass
class RunReport:
    records: list[SpecRecord] = field(default_factory=list)   # accepted, one per model
    rejected: list[SpecRecord] = field(default_factory=list)  # parsed but no model identity
    failures: list[Issue] = field(default_factory=list)       # sources that could not be fetched

    def all_issues(self) -> list[Issue]:
        issues = list(self.failures)
        for rec in (*self.records, *self.rejected):
            issues.extend(rec.issues)
        return issues

    def counts(self) -> dict[Severity, int]:
        out = dict.fromkeys(Severity, 0)
        for issue in self.all_issues():
            out[issue.severity] += 1
        return out


def run(
    sources: Iterable[str],
    fetcher: Fetcher,
    *,
    policy: RetryPolicy | None = None,
    limiter: RateLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    on_retry: Callable[[str, int, float], None] | None = None,
) -> RunReport:
    """Fetch and parse every source; de-duplicate by canonical model key."""
    report = RunReport()
    by_key: dict[str, SpecRecord] = {}

    for source in sources:
        if limiter:
            limiter.wait()
        retry_cb = (lambda a, d, _e, s=source: on_retry(s, a, d)) if on_retry else None
        try:
            html = fetch_with_retry(fetcher, source, policy, sleep=sleep, rng=rng,
                                    on_retry=retry_cb)
        except FetchFailed as exc:
            report.failures.append(Issue(IssueCode.FETCH_FAILED, Severity.ERROR, str(exc), source))
            continue

        record = parse_html(html, source)
        if record.model_key is None:
            report.rejected.append(record)
            continue

        previous = by_key.get(record.model_key)
        if previous is None:
            by_key[record.model_key] = record
            report.records.append(record)
            continue
        keep, drop = (record, previous) if len(record.fields) > len(previous.fields) \
            else (previous, record)
        keep.issues.append(Issue(
            IssueCode.DUPLICATE_MODEL, Severity.INFO,
            f"{drop.source} describes the same model; kept the page with more fields",
            keep.source))
        by_key[record.model_key] = keep
        report.records = [keep if r.model_key == record.model_key else r for r in report.records]
    return report
