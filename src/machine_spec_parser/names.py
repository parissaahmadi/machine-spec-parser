"""Turn a page heading into (manufacturer, model, canonical key).

``"VORTEX CNC 300 Turning Center"``, ``"Vortex cnc300 - Technical Data Sheet"``
and ``"Vortex CNC-300"`` all become the key ``VORTEX CNC-300``, so the same
machine described on different pages lands on the same database row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .textnorm import fold

# Fictional manufacturers used by the sample datasheets.
KNOWN_MAKERS = ("Vortex", "Helix", "Ironwood", "Nimbus", "Quanta")
_MAKERS = {m.casefold(): m.upper() for m in KNOWN_MAKERS}

_BOILERPLATE = re.compile(
    r"\b(technical\s+)?(data\s*sheet|datasheet|specifications?|spec\s*sheet|datenblatt|"
    r"technische\s+daten)\b.*$",
    re.IGNORECASE,
)
_LETTER_DIGIT = re.compile(r"(?<=[A-Z])(?=\d)|(?<=\d)(?=[A-Z])")


@dataclass(frozen=True)
class ModelId:
    manufacturer: str | None
    model: str | None
    key: str | None


def _is_model_token(token: str) -> bool:
    """CNC, FL-35E, x9, 300 qualify; "Turning", "Compressor" do not."""
    return any(ch.isdigit() for ch in token) or (token.isalpha() and token.isupper())


def _canonical_model(tokens: list[str]) -> str:
    text = "-".join(tokens).upper()
    text = re.sub(r"[^A-Z0-9.\-]+", "-", text)
    text = _LETTER_DIGIT.sub("-", text)
    return re.sub(r"-{2,}", "-", text).strip("-.")


def identify_model(heading: str | None) -> ModelId:
    """Extract the model identity from a heading; all-``None`` if there is none."""
    if not heading:
        return ModelId(None, None, None)
    text = re.sub(r"[^\x00-\x7f]+", " ", fold(heading))  # keep the Latin part of mixed text
    text = _BOILERPLATE.sub("", text)
    tokens = [t for t in re.split(r"[\s_/|,:]+", text) if t.strip("-–—.")]
    if not tokens:
        return ModelId(None, None, None)

    maker = _MAKERS.get(tokens[0].casefold())
    if (
        maker is None
        and len(tokens) > 1
        and tokens[0].isalpha()
        and not _is_model_token(tokens[0])
        and _is_model_token(tokens[1])
    ):
        maker = tokens[0].upper()  # an unregistered brand followed by something model-like
    rest = tokens[1:] if maker else tokens

    model_tokens: list[str] = []
    for i, token in enumerate(rest):
        # "cnc 300" / "rs 75": a short lower-case series prefix directly before a bare number
        series_prefix = (
            token.isalpha() and len(token) <= 4 and i + 1 < len(rest) and rest[i + 1].isdigit()
        )
        if not (_is_model_token(token) or series_prefix):
            break
        model_tokens.append(token)
    model = _canonical_model(model_tokens)
    if not model or not any(ch.isdigit() for ch in model):
        return ModelId(maker, None, None)
    return ModelId(maker, model, f"{maker} {model}" if maker else model)
