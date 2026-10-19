"""SQLite persistence (stdlib ``sqlite3``).

Saving a record replaces everything previously stored for the same model key
inside one transaction, so re-running the pipeline is idempotent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .models import Issue, Severity, SpecRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    model_key    TEXT PRIMARY KEY,
    manufacturer TEXT,
    model        TEXT,
    category     TEXT,
    title        TEXT,
    source       TEXT NOT NULL,
    lang         TEXT
);
CREATE TABLE IF NOT EXISTS specs (
    model_key TEXT NOT NULL REFERENCES machines(model_key) ON DELETE CASCADE,
    field     TEXT NOT NULL,
    value     REAL,
    minimum   REAL,
    maximum   REAL,
    tolerance REAL,
    unit      TEXT NOT NULL DEFAULT '',
    text      TEXT,
    suspect   INTEGER NOT NULL DEFAULT 0,
    raw_label TEXT,
    raw_value TEXT,
    PRIMARY KEY (model_key, field)
);
CREATE TABLE IF NOT EXISTS issues (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    model_key TEXT,
    source    TEXT NOT NULL,
    code      TEXT NOT NULL,
    severity  TEXT NOT NULL,
    label     TEXT,
    message   TEXT NOT NULL,
    raw       TEXT
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ write
    def save(self, records: list[SpecRecord], extra_issues: list[Issue] | None = None) -> None:
        with self._conn:  # one transaction: all or nothing
            for rec in records:
                if rec.model_key is None:
                    continue
                self._conn.execute("DELETE FROM machines WHERE model_key = ?", (rec.model_key,))
                self._conn.execute("DELETE FROM issues WHERE model_key = ?", (rec.model_key,))
                self._conn.execute(
                    "INSERT INTO machines VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (rec.model_key, rec.manufacturer, rec.model, rec.category, rec.title,
                     rec.source, rec.lang),
                )
                for f in rec.fields.values():
                    q = f.quantity
                    self._conn.execute(
                        "INSERT INTO specs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (rec.model_key, f.name,
                         q.value if q else None, q.minimum if q else None,
                         q.maximum if q else None, q.tolerance if q else None,
                         q.unit if q else "", f.text, int(f.suspect), f.raw_label, f.raw_value),
                    )
                for issue in rec.issues:
                    self._insert_issue(rec.model_key, issue)
            for issue in extra_issues or []:
                self._insert_issue(None, issue)

    def _insert_issue(self, model_key: str | None, i: Issue) -> None:
        self._conn.execute(
            "INSERT INTO issues (model_key, source, code, severity, label, message, raw) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (model_key, i.source, i.code.value, i.severity.value, i.label, i.message, i.raw),
        )

    # ------------------------------------------------------------------- read
    def list_models(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT m.*, (SELECT COUNT(*) FROM specs s WHERE s.model_key = m.model_key) "
            "AS field_count FROM machines m ORDER BY model_key"
        )
        return [dict(r) for r in rows]

    def get_specs(self, model_key: str) -> dict[str, dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM specs WHERE model_key = ? ORDER BY field", (model_key,)
        )
        return {r["field"]: dict(r) for r in rows}

    def has_model(self, model_key: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM machines WHERE model_key = ?", (model_key,))
        return row.fetchone() is not None

    def issues(self, min_severity: Severity = Severity.INFO) -> list[dict[str, Any]]:
        order = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}
        rows = self._conn.execute("SELECT * FROM issues ORDER BY id")
        return [dict(r) for r in rows if order[Severity(r["severity"])] >= order[min_severity]]
