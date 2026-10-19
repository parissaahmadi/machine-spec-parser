from conftest import DATA, read

from machine_spec_parser import Severity, Store, parse_html, run
from machine_spec_parser.fetch import FileFetcher


def loaded_store():
    store = Store()
    report = run([str(p) for p in sorted(DATA.glob("*.html"))], FileFetcher(), sleep=lambda s: None)
    store.save(report.records, extra_issues=report.failures)
    return store


def test_models_and_specs_round_trip():
    store = loaded_store()
    models = {m["model_key"]: m for m in store.list_models()}
    assert set(models) == {"HELIX RS-75", "IRONWOOD FL-35-E", "NIMBUS CP-150", "QUANTA X-9",
                           "VORTEX CNC-300"}
    assert models["VORTEX CNC-300"]["field_count"] == 14
    specs = store.get_specs("VORTEX CNC-300")
    assert specs["rated_power"]["value"] == 22.0 and specs["rated_power"]["unit"] == "kW"
    assert specs["supply_voltage"]["tolerance"] == 40.0
    assert specs["operating_temperature"]["minimum"] == 5.0
    assert specs["drive_type"]["text"] == "Servo / direct drive"
    assert specs["rated_power"]["raw_value"] == "22 kW (29.5 hp)"


def test_suspect_flag_is_persisted():
    specs = loaded_store().get_specs("QUANTA X-9")
    assert specs["noise_level"]["suspect"] == 1
    assert specs["weight"]["suspect"] == 0


def test_saving_twice_replaces_instead_of_duplicating():
    store = Store()
    record = parse_html(read("quanta-x9.html"), "quanta-x9.html")
    store.save([record])
    first_issue_count = len(store.issues())
    store.save([record])
    assert len(store.list_models()) == 1
    assert len(store.issues()) == first_issue_count
    assert len(store.get_specs("QUANTA X-9")) == len(record.fields)


def test_issue_filtering_by_severity():
    store = loaded_store()
    warnings = store.issues(Severity.WARNING)
    assert len(warnings) == 6 and all(i["severity"] == "warning" for i in warnings)
    assert len(store.issues(Severity.INFO)) > len(warnings)
    assert store.issues(Severity.ERROR) == []


def test_records_without_a_model_key_are_skipped():
    store = Store()
    store.save([parse_html("<h1>Specs</h1>", "x")])
    assert store.list_models() == []


def test_deleting_a_machine_cascades_to_specs():
    store = loaded_store()
    store._conn.execute("DELETE FROM machines WHERE model_key = 'HELIX RS-75'")
    assert store.get_specs("HELIX RS-75") == {}


def test_has_model():
    store = loaded_store()
    assert store.has_model("HELIX RS-75") and not store.has_model("NOPE")
