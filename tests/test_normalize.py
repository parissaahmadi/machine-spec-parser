import pytest

from machine_spec_parser.models import IssueCode, Severity
from machine_spec_parser.normalize import normalize_row


def go(label, value, **kw):
    return normalize_row(label, value, source="t.html", **kw)


def one(label, value, **kw):
    result = go(label, value, **kw)
    assert len(result.fields) == 1, result
    return result.fields[0], result.issues


def codes(issues):
    return [i.code for i in issues]


# ------------------------------------------------------------ happy paths
def test_simple_quantity():
    f, issues = one("Rated power", "22 kW")
    assert (f.name, f.quantity.value, f.quantity.unit) == ("rated_power", 22.0, "kW")
    assert issues == []


def test_conversion_to_canonical_units():
    f, _ = one("Working pressure", "125 psi")
    assert f.quantity.value == pytest.approx(8.618, abs=1e-3)
    assert f.quantity.unit == "bar"


def test_range_in_fahrenheit():
    f, _ = one("Operating temperature", "14 – 104 °F")
    assert f.quantity.minimum == pytest.approx(-10.0)
    assert f.quantity.maximum == pytest.approx(40.0)
    assert f.quantity.unit == "°C"


def test_reversed_range_is_ordered():
    f, _ = one("Operating temperature", "40 to 5 °C")
    assert (f.quantity.minimum, f.quantity.maximum) == (5.0, 40.0)


def test_absolute_tolerance_is_converted_as_a_difference():
    f, _ = one("Operating temperature", "20 ± 9 °F")
    assert f.quantity.value == pytest.approx(-6.667, abs=1e-3)
    assert f.quantity.tolerance == pytest.approx(5.0)


def test_percent_tolerance():
    f, _ = one("Supply voltage", "400 V ±10%")
    assert (f.quantity.value, f.quantity.tolerance) == (400.0, 40.0)


def test_unit_from_a_separate_cell():
    f, _ = one("Free air delivery", "12.4", unit_cell="m³/min")
    assert f.quantity.value == pytest.approx(744.0)


def test_unit_cell_is_not_added_when_value_has_its_own_unit():
    f, _ = one("Weight", "1,250 kg", unit_cell="typical")
    assert f.quantity.value == 1250.0


def test_unit_hint_from_label():
    f, issues = one("Working pressure [bar]", "8.5")
    assert f.quantity.value == 8.5
    assert issues == []


def test_persian_row_end_to_end():
    f, _ = one("قدرت‌ موتور", "۱۵ کیلووات", lang="fa", decimal_hint=".")
    assert (f.name, f.quantity.value) == ("rated_power", 15.0)
    f, _ = one("فشار کاری", "۱۰٫۵ بار", lang="fa", decimal_hint=".")
    assert f.quantity.value == 10.5


def test_german_decimal_comma_and_thousands_dot():
    f, issues = one("Motorleistung", "11,5 kW", lang="de", decimal_hint=",")
    assert f.quantity.value == 11.5 and issues == []
    f, issues = one("Tragfähigkeit", "3.500 kg", lang="de", decimal_hint=",")
    assert f.quantity.value == 3500.0 and issues == []


# ---------------------------------------------------------- unit policy
def test_missing_unit_is_refused_not_guessed():
    result = go("Voltage", "460")
    assert result.fields == []
    assert codes(result.issues) == [IssueCode.UNIT_MISSING]


def test_unknown_unit_is_reported():
    result = go("Weight", "5 furlongs")
    assert result.fields == []
    assert codes(result.issues) == [IssueCode.UNPARSEABLE_VALUE]


def test_wrong_dimension_is_an_error():
    result = go("Rated power", "8 bar")
    assert result.fields == []
    assert result.issues[0].code is IssueCode.UNIT_MISMATCH
    assert result.issues[0].severity is Severity.ERROR


def test_ambiguous_label_is_resolved_by_unit():
    f, _ = one("Capacity", "440 cfm")
    assert f.name == "flow_rate"
    f, _ = one("Capacity", "3,500 kg", decimal_hint=".")
    assert f.name == "load_capacity"


def test_ambiguous_label_without_unit_is_refused():
    assert codes(go("Capacity", "440").issues) == [IssueCode.UNIT_MISSING]


# ----------------------------------------------------------- validation
def test_ambiguous_number_is_flagged_and_kept():
    f, issues = one("Weight", "2,755 lbs")
    assert f.quantity.value == pytest.approx(1249.65, abs=0.01)
    assert codes(issues) == [IssueCode.AMBIGUOUS_NUMBER]


def test_alternate_agreeing_with_primary_is_silent():
    _, issues = one("Rated power", "22 kW (29.5 hp)")
    assert issues == []


def test_alternate_disagreeing_with_primary_warns_and_keeps_primary():
    f, issues = one("Rated power", "75 kW (90 hp)")
    assert f.quantity.value == 75.0
    assert codes(issues) == [IssueCode.CONFLICTING_VALUES]


def test_alternate_with_unrelated_unit_is_ignored():
    _, issues = one("Rated power", "75 kW (4 bar)")
    assert issues == []


def test_out_of_range_is_kept_but_marked_suspect():
    f, issues = one("Noise level", "690 dB(A)")
    assert f.suspect is True
    assert codes(issues) == [IssueCode.OUT_OF_RANGE]


def test_placeholder_values_are_not_errors():
    for value in ("n/a", "-", "TBD"):
        result = go("Weight", value)
        assert result.fields == []
        assert codes(result.issues) == [IssueCode.MISSING_VALUE]
        assert result.issues[0].severity is Severity.INFO


def test_text_without_number_for_a_quantity_is_unparseable():
    assert codes(go("Weight", "heavy").issues) == [IssueCode.UNPARSEABLE_VALUE]


# -------------------------------------------------------- other kinds
def test_year_plain_and_with_noise():
    f, _ = one("Year of manufacture", "built in 2019 (refurbished)")
    assert f.quantity.value == 2019.0


def test_solar_hijri_year_is_converted_on_persian_pages_only():
    f, issues = one("سال ساخت", "۱۴۰۱", lang="fa")
    assert f.quantity.value == 2022.0
    assert codes(issues) == [IssueCode.CALENDAR_CONVERTED]
    result = go("Year", "1401", lang="en")
    assert result.fields[0].suspect is True
    assert IssueCode.OUT_OF_RANGE in codes(result.issues)


def test_bad_year_is_unparseable():
    assert codes(go("Year", "20l8").issues) == [IssueCode.UNPARSEABLE_VALUE]


@pytest.mark.parametrize("raw,expected", [("IP 54", "IP54"), ("ip55", "IP55"), ("IP66K", "IP66K")])
def test_ip_rating(raw, expected):
    f, _ = one("Ingress protection", raw)
    assert f.text == expected


def test_bad_ip_rating():
    assert codes(go("IP rating", "waterproof").issues) == [IssueCode.UNPARSEABLE_VALUE]


def test_dimensions_become_three_fields():
    result = go("Dimensions (L × W × H)", "3200 × 1750 × 2100 mm")
    assert [(f.name, f.quantity.value) for f in result.fields] == [
        ("length_mm", 3200.0), ("width_mm", 1750.0), ("height_mm", 2100.0)]


def test_dimensions_convert_units_and_use_unit_cell():
    result = go("Dimensions", "94 x 44 x 70 in")
    assert result.fields[0].quantity.value == pytest.approx(2387.6)
    result = go("Dimensions", "2400 x 1100 x 1750", unit_cell="mm")
    assert result.fields[2].quantity.value == 1750.0


def test_dimensions_without_unit_are_refused():
    assert codes(go("Dimensions", "2400 x 1100 x 1750").issues) == [IssueCode.UNIT_MISSING]


def test_dimensions_with_decimal_comma():
    result = go("Abmessungen", "2.650 × 1.150 × 2.100 mm", decimal_hint=",")
    assert result.fields[0].quantity.value == 2650.0


def test_text_field_and_placeholder():
    f, _ = one("Drive type", "Servo / direct drive")
    assert f.text == "Servo / direct drive"
    assert go("Drive type", "n/a").fields == []


# ------------------------------------------------------------- labels
def test_unknown_label_is_reported_as_unmapped():
    result = go("Coolant tank", "180 l")
    assert result.unmapped is True
    assert codes(result.issues) == [IssueCode.UNKNOWN_LABEL]
    assert result.issues[0].severity is Severity.INFO


def test_fuzzy_label_is_reported_but_used():
    f, issues = one("Motor outpt", "75 kW")
    assert f.name == "rated_power"
    assert codes(issues) == [IssueCode.FUZZY_LABEL]


def test_issue_carries_context():
    issue = go("Voltage", "460").issues[0]
    assert (issue.source, issue.label, issue.raw) == ("t.html", "Voltage", "460")
