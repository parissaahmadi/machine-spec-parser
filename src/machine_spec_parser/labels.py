"""Map free-text row labels ("Motor output", "Nennleistung", "قدرت موتور") to canonical fields.

Matching is key-based (case, spaces, punctuation and Persian ZWNJ are ignored),
supports English, German and Persian synonyms, falls back to fuzzy matching
for typos, and may return *several* candidates: a label such as "Capacity" can
mean air flow for a compressor or a load rating for a forklift. The unit that
accompanies the value decides (see ``normalize``).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Literal

from .textnorm import fold
from .units import Dimension, UnknownUnit, lookup

Kind = Literal["quantity", "int", "text", "ip", "dimensions"]
D = Dimension


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: Kind
    dimension: Dimension | None = None
    bounds: tuple[float, float] | None = None  # plausible range, canonical units
    synonyms: tuple[str, ...] = ()


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("rated_power", "quantity", D.POWER, (0.01, 10_000), (
        "rated power", "power", "motor power", "motor output", "installed power", "nominal power",
        "engine power", "spindle power", "power rating", "nennleistung", "leistung",
        "motorleistung", "قدرت", "قدرت موتور", "توان", "توان نامی")),
    FieldSpec("working_pressure", "quantity", D.PRESSURE, (0, 1_000), (
        "working pressure", "operating pressure", "max pressure", "max. working pressure",
        "maximum pressure", "discharge pressure", "rated pressure", "pressure", "arbeitsdruck",
        "betriebsdruck", "druck", "فشار کاری", "فشار", "حداکثر فشار")),
    FieldSpec("flow_rate", "quantity", D.FLOW, (0, 200_000), (
        "flow rate", "free air delivery", "fad", "airflow", "capacity", "delivery",
        "volume flow", "flow", "fördermenge", "förderstrom", "دبی", "ظرفیت")),
    FieldSpec("load_capacity", "quantity", D.MASS, (0, 500_000), (
        "load capacity", "rated capacity", "capacity", "lifting capacity", "payload",
        "tragfähigkeit", "nutzlast", "ظرفیت بار", "ظرفیت باربری")),
    FieldSpec("rotational_speed", "quantity", D.SPEED, (0, 200_000), (
        "rotational speed", "rated speed", "speed", "spindle speed", "max speed", "motor speed",
        "drehzahl", "سرعت دوران", "سرعت", "دور موتور")),
    FieldSpec("supply_voltage", "quantity", D.VOLTAGE, (0.5, 1_000_000), (
        "voltage", "supply voltage", "power supply", "rated voltage", "battery voltage",
        "spannung", "betriebsspannung", "batteriespannung", "ولتاژ", "ولتاژ تغذیه")),
    FieldSpec("frequency", "quantity", D.FREQUENCY, (0, 10_000), (
        "frequency", "mains frequency", "supply frequency", "frequenz", "netzfrequenz",
        "فرکانس")),
    FieldSpec("weight", "quantity", D.MASS, (0.001, 1_000_000), (
        "weight", "net weight", "mass", "operating weight", "service weight", "dead weight",
        "gewicht", "eigengewicht", "betriebsgewicht", "وزن", "وزن خالص")),
    FieldSpec("noise_level", "quantity", D.NOISE, (20, 160), (
        "noise level", "noise", "sound pressure level", "sound level", "schalldruckpegel",
        "geräuschpegel", "سطح صدا", "نویز")),
    FieldSpec("operating_temperature", "quantity", D.TEMPERATURE, (-100, 1_000), (
        "operating temperature", "ambient temperature", "temperature range",
        "betriebstemperatur", "دمای کاری")),
    FieldSpec("operating_hours", "quantity", D.TIME, (0, 300_000), (
        "operating hours", "hours", "hour meter", "running hours", "betriebsstunden",
        "ساعت کارکرد")),
    FieldSpec("lift_height", "quantity", D.LENGTH, (0, 100_000), (
        "lift height", "lifting height", "max lift height", "hubhöhe", "ارتفاع بالابری")),
    FieldSpec("year_of_manufacture", "int", None, (1950, 2100), (
        "year", "year of manufacture", "model year", "manufacture year", "baujahr",
        "سال ساخت")),
    FieldSpec("ingress_protection", "ip", None, None, (
        "ip rating", "ingress protection", "protection class", "protection", "schutzart",
        "درجه حفاظت")),
    FieldSpec("dimensions", "dimensions", D.LENGTH, (1, 100_000), (
        "dimensions", "overall dimensions", "size", "abmessungen", "ابعاد")),
    FieldSpec("drive_type", "text", None, None, (
        "drive type", "drive", "power source", "antriebsart", "antrieb", "نوع محرک")),
)

_DROP = re.compile(r"[\s\-_.:/]+")


def label_key(text: str) -> str:
    """Matching key: folded, lower-cased, with spaces and punctuation removed."""
    return _DROP.sub("", fold(text).casefold())


def _build_index() -> dict[str, list[FieldSpec]]:
    index: dict[str, list[FieldSpec]] = {}
    for spec in FIELDS:
        for synonym in (spec.name.replace("_", " "), *spec.synonyms):
            bucket = index.setdefault(label_key(synonym), [])
            if spec not in bucket:
                bucket.append(spec)
    return index


_INDEX = _build_index()


@dataclass(frozen=True)
class LabelParts:
    base: str                  # label without a trailing unit hint
    unit_hint: str | None      # e.g. "bar" from "Working pressure [bar]"
    stripped: str              # label without any trailing bracket


_BRACKET = re.compile(r"[\[(]\s*([^\])]+?)\s*[\])]\s*$")
_COMMA_UNIT = re.compile(r",\s*([^,]+)$")


def split_label(label: str) -> LabelParts:
    """Separate a trailing unit hint from the label text.

    ``"Working pressure [bar]"`` -> base ``"Working pressure"``, hint ``"bar"``.
    ``"Weight, kg"`` works too. A bracket that is not a unit (``"(L × W × H)"``)
    is kept out of the way in ``stripped`` instead.
    """
    text = fold(label).strip(" :")
    m = _BRACKET.search(text)
    stripped = text[: m.start()].strip(" :") if m else text
    for pattern in (_BRACKET, _COMMA_UNIT):
        m = pattern.search(text)
        if m:
            try:
                lookup(m.group(1))
            except UnknownUnit:
                continue
            return LabelParts(text[: m.start()].strip(" :"), m.group(1), stripped)
    return LabelParts(text, None, stripped)


@dataclass(frozen=True)
class LabelMatch:
    candidates: list[FieldSpec]
    fuzzy_from: str | None = None  # the synonym a typo'd label was matched to


FUZZY_CUTOFF = 0.86


def match_label(label: str) -> LabelMatch:
    """Find the field(s) a label refers to; empty candidates means unknown."""
    key = label_key(label)
    if not key:
        return LabelMatch([])
    if key in _INDEX:
        return LabelMatch(list(_INDEX[key]))
    if len(key) >= 5:
        close = difflib.get_close_matches(key, _INDEX.keys(), n=1, cutoff=FUZZY_CUTOFF)
        if close:
            return LabelMatch(list(_INDEX[close[0]]), fuzzy_from=close[0])
    return LabelMatch([])
