"""Pull a heading and (label, value) rows out of a datasheet page.

Uses only the standard library's ``HTMLParser``. Two common layouts are
supported: two- or three-cell table rows (``label | value [| unit]``) and
definition lists (``<dt>`` / ``<dd>``). Header rows made only of ``<th>`` cells
are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass(frozen=True)
class Row:
    label: str
    value: str
    unit_cell: str | None = None  # third column, when the page has one


@dataclass
class Document:
    title: str | None = None
    h1: str | None = None
    lang: str | None = None
    meta: dict[str, str] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)


def _squash(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doc = Document()
        self._skip = 0
        self._title: list[str] | None = None
        self._h1: list[str] | None = None
        self._cell: list[str] | None = None
        self._cells: list[tuple[str, str]] | None = None  # (tag, text)
        self._cell_tag = ""
        self._dt: list[str] | None = None
        self._dd: list[str] | None = None
        self._pending_dt: str | None = None

    # -- helpers -----------------------------------------------------------
    def _buffers(self) -> list[list[str]]:
        return [b for b in (self._title, self._h1, self._cell, self._dt, self._dd) if b is not None]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "html" and a.get("lang"):
            self.doc.lang = a["lang"]
        elif tag == "meta" and a.get("name"):
            self.doc.meta[a["name"].lower()] = a.get("content", "")
        elif tag == "title":
            self._title = []
        elif tag == "h1" and self.doc.h1 is None:
            self._h1 = []
        elif tag == "tr":
            self._cells = []
        elif tag in ("th", "td") and self._cells is not None:
            self._cell, self._cell_tag = [], tag
        elif tag == "dt":
            self._dt = []
        elif tag == "dd":
            self._dd = []
        elif tag == "br":
            for buf in self._buffers():
                buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title" and self._title is not None:
            self.doc.title = _squash(self._title) or None
            self._title = None
        elif tag == "h1" and self._h1 is not None:
            self.doc.h1 = _squash(self._h1) or None
            self._h1 = None
        elif tag in ("th", "td") and self._cell is not None and self._cells is not None:
            self._cells.append((self._cell_tag, _squash(self._cell)))
            self._cell = None
        elif tag == "tr" and self._cells is not None:
            self._finish_row(self._cells)
            self._cells = None
        elif tag == "dt" and self._dt is not None:
            self._pending_dt = _squash(self._dt)
            self._dt = None
        elif tag == "dd" and self._dd is not None:
            if self._pending_dt:
                self.doc.rows.append(Row(self._pending_dt, _squash(self._dd)))
            self._pending_dt = None
            self._dd = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        for buf in self._buffers():
            buf.append(data)

    def _finish_row(self, cells: list[tuple[str, str]]) -> None:
        if len(cells) < 2 or all(tag == "th" for tag, _ in cells):
            return  # header or decorative row
        texts = [text for _, text in cells]
        if len(texts) == 2:
            self.doc.rows.append(Row(texts[0], texts[1]))
        elif len(texts) == 3:
            self.doc.rows.append(Row(texts[0], texts[1], texts[2] or None))


def extract_document(html: str) -> Document:
    parser = _Extractor()
    parser.feed(html)
    parser.close()
    return parser.doc
