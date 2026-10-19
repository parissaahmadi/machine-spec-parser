import random

import pytest
from conftest import DATA, read

from machine_spec_parser import IssueCode, Severity, parse_html, run
from machine_spec_parser.fetch import FetchError, FileFetcher, FlakyFetcher
from machine_spec_parser.pipeline import decimal_hint_for


def rec(name):
    return parse_html(read(name), name)


def val(record, field):
    return record.fields[field].quantity.value


def codes(record):
    return [i.code for i in record.issues]


# ------------------------------------------------------------ bundled pages
def test_vortex_cnc_300_english_table():
    r = rec("vortex-cnc-300.html")
    assert (r.model_key, r.category, r.lang) == ("VORTEX CNC-300", "CNC machine tool", "en")
    assert val(r, "rated_power") == 22.0
    assert val(r, "rotational_speed") == 4500.0
    voltage = r.fields["supply_voltage"].quantity
    assert (voltage.value, voltage.tolerance) == (400.0, 40.0)
    assert val(r, "weight") == 6800.0
    assert [val(r, k) for k in ("length_mm", "width_mm", "height_mm")] == [3200, 1750, 2100]
    assert val(r, "operating_hours") == 11_000.0
    assert r.fields["ingress_protection"].text == "IP54"
    assert (r.fields["operating_temperature"].quantity.minimum,
            r.fields["operating_temperature"].quantity.maximum) == (5.0, 40.0)
    assert r.fields["drive_type"].text == "Servo / direct drive"
    assert r.unmapped == [("Coolant tank", "180 l")]
    assert "rated_power" in r.fields and 999 not in [f.quantity.value for f in r.fields.values()
                                                       if f.quantity]  # <script> text ignored
    assert [i for i in r.issues if i.severity is not Severity.INFO] == []


def test_helix_rs_75_three_column_layout_and_unit_hints():
    r = rec("helix-rs-75.html")
    assert r.model_key == "HELIX RS-75"
    assert val(r, "working_pressure") == 8.5            # unit came from "[bar]" in the label
    assert val(r, "flow_rate") == pytest.approx(744.0)  # 12.4 m³/min
    assert val(r, "rated_power") == 75.0                # "(100 hp)" agreed
    assert val(r, "rotational_speed") == 2980.0         # min⁻¹
    assert (val(r, "noise_level"), r.fields["noise_level"].quantity.tolerance) == (69.0, 3.0)
    assert val(r, "length_mm") == 2400.0                # unit from the third column
    assert [i for i in r.issues if i.severity is not Severity.INFO] == []


def test_ironwood_german_page_uses_decimal_comma():
    r = rec("ironwood-fl-35e.html")
    assert r.model_key == "IRONWOOD FL-35-E"
    assert val(r, "load_capacity") == 3500.0
    assert val(r, "rated_power") == 11.5
    assert val(r, "operating_hours") == 8420.0
    assert val(r, "length_mm") == 2650.0
    assert r.fields["drive_type"].text == "Elektro, Drehstrom"
    assert IssueCode.AMBIGUOUS_NUMBER not in codes(r)   # the page language settled it


def test_nimbus_persian_page():
    r = rec("nimbus-cp-150-fa.html")
    assert r.model_key == "NIMBUS CP-150" and r.lang == "fa"
    assert val(r, "rated_power") == 15.0
    assert val(r, "working_pressure") == 10.5
    assert val(r, "flow_rate") == 150.0
    assert val(r, "rotational_speed") == 2900.0
    assert val(r, "operating_hours") == 3200.0
    assert val(r, "year_of_manufacture") == 2022.0      # 1401 Solar Hijri
    assert IssueCode.CALENDAR_CONVERTED in codes(r)
    assert r.unmapped == [("جنس بدنه", "چدن")]


def test_quanta_messy_page_reports_every_problem():
    r = rec("quanta-x9.html")
    assert r.model_key == "QUANTA X-9"
    assert val(r, "working_pressure") == pytest.approx(8.618, abs=1e-3)   # psi
    assert val(r, "flow_rate") == pytest.approx(747.56, abs=0.01)         # "Capacity" in cfm
    assert val(r, "weight") == pytest.approx(1249.65, abs=0.01)           # lbs
    assert val(r, "length_mm") == pytest.approx(2387.6)                   # inches
    assert r.fields["operating_temperature"].quantity.minimum == pytest.approx(-10.0)
    assert "supply_voltage" not in r.fields                               # unit-less: refused
    assert "year_of_manufacture" not in r.fields                          # "20l8"
    assert "operating_hours" not in r.fields                              # "n/a"
    assert r.fields["noise_level"].suspect is True
    found = set(codes(r))
    assert {IssueCode.CONFLICTING_VALUES, IssueCode.AMBIGUOUS_NUMBER, IssueCode.UNIT_MISSING,
            IssueCode.OUT_OF_RANGE, IssueCode.UNPARSEABLE_VALUE, IssueCode.FUZZY_LABEL,
            IssueCode.MISSING_VALUE, IssueCode.UNKNOWN_LABEL} <= found


# ------------------------------------------------------------ page-level rules
def test_missing_model_is_an_error():
    html = "<h1>Specifications</h1><table><tr><td>Power</td><td>1 kW</td></tr></table>"
    r = parse_html(html, "x")
    assert r.model_key is None
    assert r.has_errors and codes(r)[0] is IssueCode.MISSING_MODEL


def test_heading_falls_back_to_title():
    r = parse_html("<title>Helix RS-75</title><h1>Datasheet</h1>", "x")
    assert r.model_key == "HELIX RS-75"


def test_duplicate_field_with_a_different_value_is_reported():
    html = ("<h1>Helix RS-75</h1><table><tr><td>Power</td><td>75 kW</td></tr>"
            "<tr><td>Motor output</td><td>55 kW</td></tr></table>")
    r = parse_html(html, "x")
    assert val(r, "rated_power") == 75.0
    assert IssueCode.CONFLICTING_VALUES in codes(r)


def test_duplicate_field_with_the_same_value_is_silent():
    html = ("<h1>Helix RS-75</h1><table><tr><td>Power</td><td>75 kW</td></tr>"
            "<tr><td>Motor output</td><td>100.6 hp</td></tr></table>")
    assert IssueCode.CONFLICTING_VALUES not in codes(parse_html(html, "x"))


@pytest.mark.parametrize("lang,expected", [
    ("en", "."), ("en-GB", "."), ("fa", "."), ("de", ","), ("de-AT", ","), ("fr_FR", ","),
    ("xx", None), (None, None), ("", None),
])
def test_decimal_hint_for_language(lang, expected):
    assert decimal_hint_for(lang) == expected


# ------------------------------------------------------------------ batch run
def sources():
    return sorted(str(p) for p in DATA.glob("*.html"))


def no_sleep(_):
    pass


def test_run_over_the_bundled_folder():
    report = run(sources(), FileFetcher(), sleep=no_sleep)
    assert sorted(r.model_key for r in report.records) == [
        "HELIX RS-75", "IRONWOOD FL-35-E", "NIMBUS CP-150", "QUANTA X-9", "VORTEX CNC-300"]
    assert report.rejected == [] and report.failures == []
    assert report.counts()[Severity.WARNING] == 6


def test_run_records_fetch_failures_and_continues(tmp_path):
    report = run([str(tmp_path / "missing.html"), *sources()[:1]], FileFetcher(), sleep=no_sleep)
    assert len(report.records) == 1
    assert [f.code for f in report.failures] == [IssueCode.FETCH_FAILED]


def test_run_rejects_pages_without_a_model(tmp_path):
    page = tmp_path / "anon.html"
    page.write_text("<h1>Specs</h1><table><tr><td>Power</td><td>1 kW</td></tr></table>")
    report = run([str(page)], FileFetcher(), sleep=no_sleep)
    assert report.records == [] and len(report.rejected) == 1


def test_run_deduplicates_by_model_keeping_the_richer_page(tmp_path):
    thin = tmp_path / "thin.html"
    thin.write_text("<h1>Vortex CNC 300</h1><table><tr><td>Power</td><td>22 kW</td></tr></table>")
    full = DATA / "vortex-cnc-300.html"
    report = run([str(thin), str(full)], FileFetcher(), sleep=no_sleep)
    assert len(report.records) == 1
    kept = report.records[0]
    assert kept.source == str(full)
    assert IssueCode.DUPLICATE_MODEL in codes(kept)


def test_run_retries_transient_failures_and_reports_them():
    retries = []
    flaky = FlakyFetcher(FileFetcher(), failure_rate=0.5, seed=3)
    report = run(sources(), flaky, sleep=no_sleep, rng=random.Random(3),
                 on_retry=lambda src, attempt, delay: retries.append((src, attempt)))
    assert retries, "seed 3 should trigger at least one retry"
    assert len(report.records) + len(report.failures) == 5


def test_run_is_deterministic():
    def go():
        flaky = FlakyFetcher(FileFetcher(), failure_rate=0.4, seed=11)
        report = run(sources(), flaky, sleep=no_sleep, rng=random.Random(11))
        return [(r.model_key, len(r.fields)) for r in report.records], len(report.failures)

    assert go() == go()


def test_fetch_error_type_is_exposed():
    assert issubclass(FetchError, Exception)
