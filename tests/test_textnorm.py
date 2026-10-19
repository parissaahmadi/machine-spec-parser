import pytest

from machine_spec_parser.textnorm import clean, fold, normalize_digits


@pytest.mark.parametrize("raw,expected", [
    ("۱۲۳۴۵۶۷۸۹۰", "1234567890"),
    ("٠١٢٣٤٥٦٧٨٩", "0123456789"),
    ("۱۰٫۵", "10.5"),
    ("۳٬۲۰۰", "3,200"),
    ("−10", "-10"),
    ("abc 12", "abc 12"),
])
def test_normalize_digits(raw, expected):
    assert normalize_digits(raw) == expected


def test_fold_unifies_arabic_and_persian_letters():
    assert fold("كيلو") == fold("کیلو")


def test_fold_removes_zwnj_tatweel_and_diacritics():
    assert fold("میلی\u200cمتر") == "میلیمتر"
    assert fold("قـدرت") == "قدرت"
    assert fold("قُدرت") == "قدرت"


def test_fold_collapses_whitespace_and_special_spaces():
    assert fold("  11\u00a0000 \u202fh \n") == "11 000 h"


def test_nfkc_flattens_superscripts_and_symbols():
    assert clean("12.4 m³/min") == "12.4 m3/min"
    assert clean("5 ℃") == "5 °C"


def test_clean_combines_both_steps():
    assert clean("۱۵ کیلووات") == "15 کیلووات"
