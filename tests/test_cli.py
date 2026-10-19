import contextlib
import csv
import io
import json

from conftest import DATA

from machine_spec_parser.cli import main


def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def parse_all(tmp_path, *extra):
    db = tmp_path / "specs.db"
    return call("parse", DATA, "--db", db, *extra), db


def test_parse_folder_writes_db_json_and_csv(tmp_path):
    js, cs = tmp_path / "out.json", tmp_path / "out.csv"
    (code, out, _), db = parse_all(tmp_path, "--json", js, "--csv", cs)
    assert code == 0
    assert "5 model(s) accepted" in out and "OK    VORTEX CNC-300" in out
    data = json.loads(js.read_text(encoding="utf-8"))
    assert len(data) == 5
    vortex = next(r for r in data if r["model_key"] == "VORTEX CNC-300")
    assert vortex["fields"]["rated_power"]["value"] == 22.0
    rows = list(csv.DictReader(cs.open(encoding="utf-8")))
    assert {r["model_key"] for r in rows} >= {"HELIX RS-75", "NIMBUS CP-150"}
    assert any(r["field"] == "noise_level" and r["suspect"] == "1" for r in rows)


def test_parse_prints_warnings_unless_quiet(tmp_path):
    _, out, _ = call("parse", DATA)
    assert "unit_missing" in out
    _, quiet, _ = call("parse", DATA, "--quiet")
    assert "unit_missing" not in quiet


def test_strict_mode_fails_on_error_level_issues(tmp_path):
    code, out, _ = call("parse", DATA / "vortex-cnc-300.html", tmp_path / "missing.html",
                        "--strict")
    assert code == 1 and "FAIL" in out
    code, _, _ = call("parse", DATA / "vortex-cnc-300.html", "--strict")
    assert code == 0


def test_flaky_mode_prints_retries():
    _, out, _ = call("parse", DATA, "--flaky", "0.6", "--seed", "3", "--quiet")
    assert "retry" in out


def test_empty_folder_is_an_error(tmp_path):
    code, _, err = call("parse", tmp_path)
    assert code == 2 and "no HTML files" in err


def test_list_show_compare_issues(tmp_path):
    _, db = parse_all(tmp_path)

    code, out, _ = call("list", "--db", db)
    assert code == 0 and "NIMBUS CP-150" in out

    code, out, _ = call("show", "ironwood fl35e", "--db", db)      # sloppy spelling still resolves
    assert code == 0 and "3500 kg" in out and "3.500 kg" in out

    code, out, _ = call("compare", "helix rs 75", "vortex cnc300", "--db", db)
    assert code == 0 and "HELIX RS-75" in out and "VORTEX CNC-300" in out and "—" in out

    code, out, _ = call("issues", "--db", db)
    assert code == 0 and out.count("warning") == 6


def test_unknown_model_gives_a_clear_error(tmp_path):
    _, db = parse_all(tmp_path)
    code, _, err = call("show", "zzz 999", "--db", db)
    assert code == 2 and "unknown model" in err
    code, _, err = call("compare", "helix rs 75", "zzz 999", "--db", db)
    assert code == 2
