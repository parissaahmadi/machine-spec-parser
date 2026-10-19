import pytest

from machine_spec_parser.numbers import NumberParseError, parse_number, parse_quantities


@pytest.mark.parametrize("token,hint,value,ambiguous", [
    ("22", None, 22.0, False),
    ("12.4", None, 12.4, False),
    ("0,5", None, 0.5, False),
    ("1,000,000", None, 1_000_000.0, False),
    ("1.234,5", None, 1234.5, False),
    ("1,234.5", None, 1234.5, False),
    ("11 000", None, 11_000.0, False),
    # a lone separator + exactly three digits is ambiguous without a hint ...
    ("1,500", None, 1500.0, True),
    ("1.500", None, 1.5, True),
    # ... and settled by the page language
    ("1,500", ".", 1500.0, False),
    ("1.500", ",", 1500.0, False),
    ("3.500", ",", 3500.0, False),
    ("11,5", ",", 11.5, False),
    ("2.5", ".", 2.5, False),
    ("0.500", None, 0.5, False),
])
def test_parse_number(token, hint, value, ambiguous):
    result = parse_number(token, hint)
    assert result.value == pytest.approx(value)
    assert result.ambiguous is ambiguous


@pytest.mark.parametrize("token", ["", "abc", "1,2,3", "1.234.56", "12-3"])
def test_parse_number_rejects_garbage(token):
    with pytest.raises(NumberParseError):
        parse_number(token)


def q1(text, hint=None):
    return parse_quantities(text, hint)[0]


def test_single_value_with_unit():
    q = q1("22 kW")
    assert (q.kind, q.first, q.unit) == ("single", 22.0, "kW")


def test_range_with_various_separators():
    for text in ("5 – 40 °C", "5 - 40 °C", "5 to 40 °C", "5~40 °C", "5 °C – 40 °C"):
        q = q1(text)
        assert (q.kind, q.first, q.second, q.unit) == ("range", 5.0, 40.0, "°C"), text


def test_negative_numbers_and_ranges():
    assert q1("-10 to -5 °C").first == -10.0
    assert q1("-10 to -5 °C").second == -5.0
    assert q1("-20 °C").first == -20.0


def test_tolerance_absolute_and_percent():
    q = q1("7.5 ± 0.5 bar")
    assert (q.kind, q.first, q.second, q.unit) == ("tolerance", 7.5, 0.5, "bar")
    q = q1("400 V ±10%")
    assert (q.unit, q.second_unit, q.second) == ("V", "%", 10.0)


def test_alternates_in_parentheses():
    qs = parse_quantities("75 kW (100 hp)")
    assert [(q.first, q.unit) for q in qs] == [(75.0, "kW"), (100.0, "hp")]


def test_parentheses_without_numbers_are_ignored():
    assert len(parse_quantities("75 kW (approx.)")) == 1


def test_letter_in_parentheses_is_part_of_the_unit():
    assert q1("74 dB(A)").unit == "dBA"
    assert q1("8 bar(g)").unit == "barg"


def test_digits_inside_units_are_not_numbers():
    assert q1("12.4 m3/min").unit == "m3/min"
    assert q1("4500 min-1").unit == "min-1"
    q = q1("4,500 1/min")
    assert (q.first, q.unit) == (4500.0, "1/min")


def test_text_before_the_number_is_ignored():
    assert q1("approx. 3,550 rpm").first == 3550.0


def test_hint_flows_into_quantities():
    assert q1("3.500 kg", ",").first == 3500.0
    assert q1("3.500 kg", ",").ambiguous is False
    assert q1("3,500 kg").ambiguous is True


def test_no_number_gives_no_quantity():
    assert parse_quantities("n/a") == []
    assert parse_quantities("") == []
