import pytest

from machine_spec_parser.units import (
    Dimension,
    DimensionMismatch,
    UnknownUnit,
    dimension_of,
    to_canonical,
)


@pytest.mark.parametrize("value,unit,expected", [
    (22, "kW", 22.0),
    (100, "hp", 74.5699872),
    (100, "PS", 73.549875),
    (22000, "W", 22.0),
    (125, "psi", 8.6184466),
    (1, "MPa", 10.0),
    (100, "kPa", 1.0),
    (12.4, "m³/min", 744.0),
    (440, "cfm", 747.5647),
    (1000, "l/min", 60.0),
    (2755, "lbs", 1249.6),
    (94, "in", 2387.6),
    (2, "t", 2000.0),
    (2980, "min⁻¹", 2980.0),
    (50, "rps", 3000.0),
    (1.5, "kV", 1500.0),
    (11, "min", 11 / 60),
])
def test_conversions(value, unit, expected):
    assert to_canonical(value, unit) == pytest.approx(expected, rel=1e-4)


def test_temperature_uses_offsets():
    assert to_canonical(104, "°F") == pytest.approx(40.0)
    assert to_canonical(14, "°F") == pytest.approx(-10.0)
    assert to_canonical(300, "K") == pytest.approx(26.85)
    assert to_canonical(21, "°C") == 21.0


def test_temperature_difference_ignores_offset():
    assert to_canonical(9, "°F", delta=True) == pytest.approx(5.0)


@pytest.mark.parametrize("spelling", ["m³/min", "m3/min", "M3/MIN", "m^3/min", " m 3 / min "])
def test_spelling_variants_resolve_to_the_same_unit(spelling):
    assert to_canonical(1, spelling) == 60.0


@pytest.mark.parametrize("spelling", ["dB(A)", "dBA", "db(a)", "dB"])
def test_noise_spellings(spelling):
    assert dimension_of(spelling) is Dimension.NOISE


@pytest.mark.parametrize("value,unit,expected", [
    (15, "کیلووات", 15.0),
    (10.5, "بار", 10.5),
    (150, "مترمکعب بر ساعت", 150.0),
    (2900, "دور بر دقیقه", 2900.0),
    (240, "کیلوگرم", 240.0),
    (50, "هرتز", 50.0),
    (380, "ولت", 380.0),
    (3200, "ساعت", 3200.0),
    (5, "میلی\u200cمتر", 5.0),
    (1, "اسب بخار", 0.745699872),
])
def test_persian_unit_names(value, unit, expected):
    assert to_canonical(value, unit) == pytest.approx(expected)


def test_unknown_unit_is_refused():
    with pytest.raises(UnknownUnit):
        to_canonical(1, "furlongs")


def test_dimension_mismatch_is_refused():
    with pytest.raises(DimensionMismatch):
        to_canonical(8, "bar", expected=Dimension.POWER)


def test_dimension_of_unknown_is_none():
    assert dimension_of("furlongs") is None
