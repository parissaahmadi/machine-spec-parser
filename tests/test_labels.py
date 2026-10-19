import pytest

from machine_spec_parser.labels import match_label, split_label


def names(label):
    return [c.name for c in match_label(label).candidates]


@pytest.mark.parametrize("label,field", [
    ("Rated power", "rated_power"),
    ("RATED   POWER", "rated_power"),
    ("Max. working pressure", "working_pressure"),
    ("max working pressure", "working_pressure"),
    ("Net weight", "weight"),
    ("Nennleistung", "rated_power"),
    ("Hubhöhe", "lift_height"),
    ("Schalldruckpegel", "noise_level"),
    ("قدرت موتور", "rated_power"),
    ("قدرت\u200c موتور", "rated_power"),
    ("فشار کاری", "working_pressure"),
    ("سال ساخت", "year_of_manufacture"),
    ("فشار كاري", "working_pressure"),  # Arabic kaf/yeh instead of Persian
    ("سطح صدا", "noise_level"),
])
def test_exact_matches_across_languages(label, field):
    assert names(label) == [field]


def test_capacity_is_ambiguous_by_design():
    assert names("Capacity") == ["flow_rate", "load_capacity"]


def test_fuzzy_match_flags_the_typo():
    m = match_label("Motor outpt")
    assert [c.name for c in m.candidates] == ["rated_power"]
    assert m.fuzzy_from == "motoroutput"


@pytest.mark.parametrize("label", ["Coolant tank", "Warranty", "Oil capacity", "", "جنس بدنه"])
def test_unknown_labels_do_not_match(label):
    assert match_label(label).candidates == []


def test_short_labels_never_fuzzy_match():
    assert match_label("Pwr").candidates == []


def test_split_label_unit_in_brackets():
    p = split_label("Working pressure [bar]")
    assert (p.base, p.unit_hint) == ("Working pressure", "bar")


def test_split_label_unit_in_parentheses_and_after_comma():
    assert split_label("Weight (kg)").unit_hint == "kg"
    assert split_label("Weight, kg").unit_hint == "kg"


def test_split_label_ignores_brackets_that_are_not_units():
    p = split_label("Dimensions (L × W × H)")
    assert p.unit_hint is None
    assert p.stripped == "Dimensions"


def test_split_label_trailing_colon():
    assert split_label("Rated power:").base == "Rated power"
