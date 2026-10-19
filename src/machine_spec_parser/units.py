"""Unit registry and conversion to canonical units.

Canonical units: kW, bar, m³/h, kg, mm, rpm, V, Hz, °C, dB(A), A, h.

Unit lookup is forgiving about spelling (``m³/min``, ``m3/min``, ``M3/MIN``),
and understands a few Persian unit names. Unknown units raise ``UnknownUnit``:
we never guess a conversion factor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .textnorm import fold


class Dimension(StrEnum):
    POWER = "power"
    PRESSURE = "pressure"
    FLOW = "flow"
    MASS = "mass"
    LENGTH = "length"
    SPEED = "speed"
    VOLTAGE = "voltage"
    FREQUENCY = "frequency"
    TEMPERATURE = "temperature"
    NOISE = "noise"
    CURRENT = "current"
    TIME = "time"


CANONICAL_UNIT: dict[Dimension, str] = {
    Dimension.POWER: "kW",
    Dimension.PRESSURE: "bar",
    Dimension.FLOW: "m³/h",
    Dimension.MASS: "kg",
    Dimension.LENGTH: "mm",
    Dimension.SPEED: "rpm",
    Dimension.VOLTAGE: "V",
    Dimension.FREQUENCY: "Hz",
    Dimension.TEMPERATURE: "°C",
    Dimension.NOISE: "dB(A)",
    Dimension.CURRENT: "A",
    Dimension.TIME: "h",
}


class UnitError(ValueError):
    """Base class for unit problems."""


class UnknownUnit(UnitError):
    """The unit text is not in the registry."""


class DimensionMismatch(UnitError):
    """The unit measures something other than what the field expects."""


@dataclass(frozen=True)
class UnitDef:
    dimension: Dimension
    factor: float          # canonical = value * factor + offset
    offset: float = 0.0


def _key(text: str) -> str:
    """Spelling-insensitive lookup key: folded, lower-cased, no spaces/dots/degree signs."""
    return re.sub(r"[\s.·*^()°º_]", "", fold(text).casefold())


_ALIASES: dict[str, UnitDef] = {}


def _add(dim: Dimension, factor: float, *names: str, offset: float = 0.0) -> None:
    for name in names:
        _ALIASES[_key(name)] = UnitDef(dim, factor, offset)


D = Dimension
_add(D.POWER, 1.0, "kW", "kilowatt", "کیلووات")
_add(D.POWER, 0.001, "W", "watt", "وات")
_add(D.POWER, 1000.0, "MW")
_add(D.POWER, 0.745699872, "hp", "bhp", "horsepower", "اسب بخار", "اسب‌بخار")
_add(D.POWER, 0.73549875, "PS", "CV")

_add(D.PRESSURE, 1.0, "bar", "barg", "bara", "بار")
_add(D.PRESSURE, 0.001, "mbar")
_add(D.PRESSURE, 0.0689475729, "psi", "psig", "psia")
_add(D.PRESSURE, 10.0, "MPa")
_add(D.PRESSURE, 0.01, "kPa")
_add(D.PRESSURE, 1e-5, "Pa")
_add(D.PRESSURE, 1.01325, "atm")
_add(D.PRESSURE, 0.980665, "kgf/cm²")

_add(D.FLOW, 1.0, "m³/h", "m3/hr", "cbm/h", "مترمکعب بر ساعت")
_add(D.FLOW, 60.0, "m³/min", "cbm/min", "مترمکعب بر دقیقه")
_add(D.FLOW, 3600.0, "m³/s")
_add(D.FLOW, 0.06, "l/min", "lpm", "لیتر بر دقیقه")
_add(D.FLOW, 3.6, "l/s")
_add(D.FLOW, 1.69901082, "cfm", "ft³/min")
_add(D.FLOW, 0.22712471, "gpm")  # US gallons per minute

_add(D.MASS, 1.0, "kg", "کیلوگرم")
_add(D.MASS, 0.001, "g", "گرم")
_add(D.MASS, 1000.0, "t", "tonne", "تن")
_add(D.MASS, 0.45359237, "lb", "lbs", "pound")

_add(D.LENGTH, 1.0, "mm", "میلی‌متر")
_add(D.LENGTH, 10.0, "cm", "سانتی‌متر")
_add(D.LENGTH, 1000.0, "m", "متر")
_add(D.LENGTH, 25.4, "in", "inch", '"')
_add(D.LENGTH, 304.8, "ft")

_add(D.SPEED, 1.0, "rpm", "1/min", "min-1", "r/min", "rev/min", "دور بر دقیقه", "دور در دقیقه")
_add(D.SPEED, 60.0, "rps", "rev/s")

_add(D.VOLTAGE, 1.0, "V", "volt", "ولت")
_add(D.VOLTAGE, 1000.0, "kV", "کیلوولت")
_add(D.VOLTAGE, 0.001, "mV")

_add(D.FREQUENCY, 1.0, "Hz", "هرتز")
_add(D.FREQUENCY, 1000.0, "kHz")

_add(D.CURRENT, 1.0, "A", "amp", "آمپر")
_add(D.CURRENT, 0.001, "mA")

_add(D.TIME, 1.0, "h", "hr", "hrs", "hour", "hours", "std", "ساعت")
_add(D.TIME, 1 / 60, "min")
_add(D.TIME, 1 / 3600, "s")

_add(D.TEMPERATURE, 1.0, "C", "degC", "celsius", "درجه سانتی‌گراد")
_add(D.TEMPERATURE, 5 / 9, "F", "degF", "fahrenheit", offset=-160 / 9)
_add(D.TEMPERATURE, 1.0, "K", "kelvin", offset=-273.15)

_add(D.NOISE, 1.0, "dB(A)", "dBA", "dB", "دسیبل")
del D


def lookup(unit_text: str) -> UnitDef:
    """Resolve ``unit_text`` or raise ``UnknownUnit``."""
    try:
        return _ALIASES[_key(unit_text)]
    except KeyError:
        raise UnknownUnit(f"unknown unit: {unit_text!r}") from None


def dimension_of(unit_text: str) -> Dimension | None:
    try:
        return lookup(unit_text).dimension
    except UnknownUnit:
        return None


def to_canonical(
    value: float,
    unit_text: str,
    *,
    expected: Dimension | None = None,
    delta: bool = False,
) -> float:
    """Convert ``value`` from ``unit_text`` to the canonical unit.

    ``delta=True`` converts a *difference* (e.g. a ±3 °F tolerance), so the
    temperature offset is not applied.
    """
    unit = lookup(unit_text)
    if expected is not None and unit.dimension is not expected:
        raise DimensionMismatch(
            f"{unit_text!r} measures {unit.dimension.value}, expected {expected.value}"
        )
    return value * unit.factor + (0.0 if delta else unit.offset)
