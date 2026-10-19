"""Command line: ``specparse parse | list | show | compare | issues``."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Any

from .fetch import FileFetcher, FlakyFetcher, RateLimiter, RetryPolicy
from .labels import FIELDS
from .models import Severity, SpecRecord
from .names import identify_model
from .pipeline import RunReport, run
from .store import Store

_FIELD_ORDER = {s.name: i for i, s in enumerate(FIELDS)}
_FIELD_ORDER.update({"length_mm": _FIELD_ORDER["dimensions"] + 0.1,
                     "width_mm": _FIELD_ORDER["dimensions"] + 0.2,
                     "height_mm": _FIELD_ORDER["dimensions"] + 0.3})


def _order(name: str) -> float:
    return _FIELD_ORDER.get(name, 999)


def _fmt(x: float | None) -> str:
    return "" if x is None else f"{x:.6g}"


# --------------------------------------------------------------- serialization
def record_to_dict(rec: SpecRecord) -> dict[str, Any]:
    return {
        "source": rec.source,
        "model_key": rec.model_key,
        "manufacturer": rec.manufacturer,
        "model": rec.model,
        "category": rec.category,
        "lang": rec.lang,
        "fields": {
            f.name: {
                "value": f.quantity.value if f.quantity else None,
                "minimum": f.quantity.minimum if f.quantity else None,
                "maximum": f.quantity.maximum if f.quantity else None,
                "tolerance": f.quantity.tolerance if f.quantity else None,
                "unit": f.quantity.unit if f.quantity else "",
                "text": f.text,
                "suspect": f.suspect,
                "raw": f.raw_value,
            }
            for f in sorted(rec.fields.values(), key=lambda f: _order(f.name))
        },
        "unmapped": [{"label": a, "value": b} for a, b in rec.unmapped],
        "issues": [
            {"code": i.code.value, "severity": i.severity.value, "message": i.message,
             "label": i.label, "raw": i.raw}
            for i in rec.issues
        ],
    }


def write_csv(records: list[SpecRecord], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["model_key", "field", "value", "minimum", "maximum", "tolerance",
                         "unit", "text", "suspect"])
        for rec in records:
            for f in sorted(rec.fields.values(), key=lambda f: _order(f.name)):
                q = f.quantity
                writer.writerow([
                    rec.model_key, f.name,
                    _fmt(q.value) if q else "", _fmt(q.minimum) if q else "",
                    _fmt(q.maximum) if q else "", _fmt(q.tolerance) if q else "",
                    q.unit if q else "", f.text or "", int(f.suspect),
                ])


# ------------------------------------------------------------------- commands
def _collect_sources(paths: list[str]) -> list[str]:
    sources: list[str] = []
    for p in paths:
        path = Path(p)
        sources.extend(str(f) for f in sorted(path.glob("*.html"))) if path.is_dir() \
            else sources.append(p)
    return sources


def _status(rec: SpecRecord) -> str:
    if rec.has_errors:
        return "ERR "
    return "WARN" if rec.count(Severity.WARNING) else "OK  "


def cmd_parse(args: argparse.Namespace) -> int:
    sources = _collect_sources(args.paths)
    if not sources:
        print("no HTML files found", file=sys.stderr)
        return 2

    fetcher: Any = FileFetcher()
    sleep = None
    if args.flaky > 0:  # demo mode: show retries without actually waiting
        fetcher = FlakyFetcher(fetcher, args.flaky, seed=args.seed)
        sleep = lambda _s: None  # noqa: E731
    limiter = RateLimiter(args.rate_limit) if args.rate_limit > 0 else None

    def on_retry(source: str, attempt: int, delay: float) -> None:
        print(f"  retry   {Path(source).name}: attempt {attempt} failed, waiting {delay:.2f}s")

    print(f"Parsing {len(sources)} source(s)\n")
    kwargs: dict[str, Any] = {"policy": RetryPolicy(), "limiter": limiter,
                              "rng": random.Random(args.seed), "on_retry": on_retry}
    if sleep:
        kwargs["sleep"] = sleep
    report: RunReport = run(sources, fetcher, **kwargs)

    for rec in report.records:
        print(f"{_status(rec)}  {rec.model_key:<20} {len(rec.fields):>2} fields  "
              f"{rec.count(Severity.WARNING)} warning(s)  {Path(rec.source).name}")
        if not args.quiet:
            for issue in rec.issues:
                if issue.severity is not Severity.INFO:
                    print(f"        {issue.severity.value:<7} {issue.code.value}: {issue.message}")
    for rec in report.rejected:
        print(f"ERR   (no model)           {Path(rec.source).name}: rejected")
    for issue in report.failures:
        print(f"FAIL  {issue.message}")

    counts = report.counts()
    print(f"\n{len(report.records)} model(s) accepted, {len(report.rejected)} rejected, "
          f"{len(report.failures)} fetch failure(s); issues: "
          f"{counts[Severity.ERROR]} error, {counts[Severity.WARNING]} warning, "
          f"{counts[Severity.INFO]} info")

    if args.db:
        store = Store(args.db)
        store.save(report.records, extra_issues=report.failures)
        store.close()
        print(f"saved to {args.db}")
    if args.json:
        Path(args.json).write_text(
            json.dumps([record_to_dict(r) for r in report.records], indent=2, ensure_ascii=False),
            encoding="utf-8")
        print(f"wrote {args.json}")
    if args.csv:
        write_csv(report.records, Path(args.csv))
        print(f"wrote {args.csv}")
    return 1 if args.strict and counts[Severity.ERROR] else 0


def _resolve(store: Store, query: str) -> str | None:
    key = identify_model(query.upper()).key or query.upper()
    return key if store.has_model(key) else None


def _table(rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _display(spec: dict[str, Any]) -> str:
    if spec["text"]:
        return spec["text"]
    unit = f" {spec['unit']}" if spec["unit"] else ""
    if spec["value"] is not None:
        tol = f" ± {_fmt(spec['tolerance'])}" if spec["tolerance"] is not None else ""
        return f"{_fmt(spec['value'])}{tol}{unit}" + ("  (suspect)" if spec["suspect"] else "")
    return f"{_fmt(spec['minimum'])}–{_fmt(spec['maximum'])}{unit}"


def cmd_list(args: argparse.Namespace) -> int:
    store = Store(args.db)
    rows = [["model", "category", "fields", "source"]]
    rows += [[m["model_key"], m["category"] or "", str(m["field_count"]), Path(m["source"]).name]
             for m in store.list_models()]
    print(_table(rows))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = Store(args.db)
    key = _resolve(store, args.model)
    if key is None:
        print(f"unknown model {args.model!r}; try: specparse list --db {args.db}", file=sys.stderr)
        return 2
    specs = store.get_specs(key)
    print(key)
    rows = [["field", "value", "raw text on the page"]]
    for name in sorted(specs, key=_order):
        rows.append([name, _display(specs[name]), specs[name]["raw_value"] or ""])
    print(_table(rows))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    store = Store(args.db)
    keys = []
    for q in args.models:
        key = _resolve(store, q)
        if key is None:
            print(f"unknown model {q!r}", file=sys.stderr)
            return 2
        keys.append(key)
    specs = {k: store.get_specs(k) for k in keys}
    names = sorted({n for s in specs.values() for n in s}, key=_order)
    rows = [["field", *keys]]
    for name in names:
        rows.append([name, *[_display(specs[k][name]) if name in specs[k] else "—" for k in keys]])
    print(_table(rows))
    return 0


def cmd_issues(args: argparse.Namespace) -> int:
    store = Store(args.db)
    for i in store.issues(Severity(args.min_severity)):
        where = i["model_key"] or Path(i["source"]).name
        print(f"{i['severity']:<7} {i['code']:<20} {where:<18} {i['message']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="specparse", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="parse datasheets (files or folders)")
    p.add_argument("paths", nargs="+")
    p.add_argument("--db", help="save results to this SQLite file")
    p.add_argument("--json", help="write results as JSON")
    p.add_argument("--csv", help="write results as flat CSV")
    p.add_argument("--strict", action="store_true", help="exit 1 if any error-level issue exists")
    p.add_argument("--quiet", action="store_true", help="hide per-record warnings")
    p.add_argument("--flaky", type=float, default=0.0, metavar="RATE",
                   help="simulate transient fetch failures (0..1) to demo retry/backoff")
    p.add_argument("--seed", type=int, default=0, help="seed for --flaky and backoff jitter")
    p.add_argument("--rate-limit", type=float, default=0.0, metavar="SECONDS",
                   help="minimum seconds between fetches")
    p.set_defaults(func=cmd_parse)

    for name, func, helptext in (
        ("list", cmd_list, "list stored models"),
        ("show", cmd_show, "show one model's specs"),
        ("compare", cmd_compare, "compare models side by side"),
        ("issues", cmd_issues, "list recorded issues"),
    ):
        q = sub.add_parser(name, help=helptext)
        q.add_argument("--db", required=True)
        if name == "show":
            q.add_argument("model")
        if name == "compare":
            q.add_argument("models", nargs="+")
        if name == "issues":
            q.add_argument("--min-severity", default="warning",
                           choices=[s.value for s in Severity])
        q.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
