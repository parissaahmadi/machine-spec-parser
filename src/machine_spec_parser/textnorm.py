"""Text normalization shared by every other module.

Datasheets arrive in many scripts and typographic styles. Before anything is
parsed we fold them into one predictable form:

* Persian (۰-۹) and Arabic-Indic (٠-٩) digits become ASCII digits.
* Persian decimal / thousands separators (٫ ٬ ،) become "." and ",".
* Unicode compatibility forms collapse (``m³`` -> ``m3``, ``℃`` -> ``°C``,
  non-breaking and thin spaces -> a normal space).
* Arabic letter variants used instead of Persian ones (ي ك) are unified, and
  invisible joiners (ZWNJ), tatweel and diacritics are dropped.
"""

from __future__ import annotations

import re
import unicodedata

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

_DIGIT_TABLE: dict[int, str] = {
    **{ord(c): str(i) for i, c in enumerate(_PERSIAN_DIGITS)},
    **{ord(c): str(i) for i, c in enumerate(_ARABIC_INDIC_DIGITS)},
    ord("٫"): ".",  # Arabic decimal separator
    ord("٬"): ",",  # Arabic thousands separator
    ord("،"): ",",  # Arabic comma
    ord("\u2212"): "-",  # true minus sign
}

_ARABIC_TO_PERSIAN: dict[int, str] = {
    ord("ي"): "ی",
    ord("ى"): "ی",
    ord("ك"): "ک",
}

# Arabic harakat, superscript alef and tatweel carry no meaning for matching.
_DIACRITICS = re.compile("[\u064b-\u065f\u0670\u0640]")
_JOINERS = re.compile("[\u200c\u200d\u200e\u200f]")
_SPACES = re.compile(r"\s+")


def normalize_digits(text: str) -> str:
    """Map Persian/Arabic digits and separators to their ASCII equivalents."""
    return text.translate(_DIGIT_TABLE)


def fold(text: str) -> str:
    """Unicode-fold ``text`` and collapse whitespace (case is preserved)."""
    t = unicodedata.normalize("NFKC", text).replace("\u2212", "-")  # "⁻¹" -> "−1" -> "-1"
    t = _DIACRITICS.sub("", t).translate(_ARABIC_TO_PERSIAN)
    t = _JOINERS.sub("", t)
    return _SPACES.sub(" ", t).strip()


def clean(text: str) -> str:
    """``fold`` + ``normalize_digits``: the standard pre-processing for values."""
    return normalize_digits(fold(text))
