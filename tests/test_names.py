import pytest

from machine_spec_parser.names import identify_model


@pytest.mark.parametrize("heading", [
    "VORTEX CNC 300 Turning Center",
    "Vortex cnc300 - Technical Data Sheet",
    "Vortex CNC-300",
    "vortex  cnc_300 Datenblatt",
    "Vortex CNC-300 – Technical Data Sheet",
])
def test_spelling_variants_share_one_key(heading):
    assert identify_model(heading).key == "VORTEX CNC-300"


def test_maker_and_model_are_split():
    m = identify_model("Helix RS 75 Screw Compressor")
    assert (m.manufacturer, m.model, m.key) == ("HELIX", "RS-75", "HELIX RS-75")


def test_product_description_words_are_not_part_of_the_model():
    assert identify_model("QUANTA x9 compressor DATA SHEET").key == "QUANTA X-9"
    assert identify_model("Ironwood FL-35E Elektro-Gabelstapler").model == "FL-35-E"


def test_latin_name_inside_persian_heading():
    assert identify_model("پمپ سانتریفیوژ Nimbus CP-150").key == "NIMBUS CP-150"


def test_unregistered_brand_is_still_recognised():
    m = identify_model("Zenith ZX-500 Hydraulic Press")
    assert (m.manufacturer, m.model, m.key) == ("ZENITH", "ZX-500", "ZENITH ZX-500")


def test_model_without_any_brand():
    assert identify_model("ZX-500").key == "ZX-500"


@pytest.mark.parametrize(
    "heading", [None, "", "Technical Data Sheet", "Specifications", "just words"]
)
def test_no_model_found(heading):
    assert identify_model(heading).key is None
