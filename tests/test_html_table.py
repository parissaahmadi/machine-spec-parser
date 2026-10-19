from machine_spec_parser.html_table import Row, extract_document


def test_two_cell_rows_and_header_rows():
    doc = extract_document("""
      <table>
        <tr><th>Parameter</th><th>Value</th></tr>
        <tr><th>Weight</th><td>1,250 kg</td></tr>
        <tr><td>Power</td><td>75 kW</td></tr>
      </table>""")
    assert doc.rows == [Row("Weight", "1,250 kg"), Row("Power", "75 kW")]


def test_three_cell_rows_keep_the_unit_cell():
    doc = extract_document("<table><tr><td>Weight</td><td>1,250</td><td>kg</td></tr></table>")
    assert doc.rows == [Row("Weight", "1,250", "kg")]


def test_empty_third_cell_becomes_none():
    doc = extract_document("<table><tr><td>Year</td><td>2021</td><td></td></tr></table>")
    assert doc.rows[0].unit_cell is None


def test_definition_lists():
    doc = extract_document(
        "<dl><dt>Gewicht</dt><dd>5.250 kg</dd><dt>Baujahr</dt><dd>2020</dd></dl>"
    )
    assert doc.rows == [Row("Gewicht", "5.250 kg"), Row("Baujahr", "2020")]


def test_title_h1_lang_and_meta():
    doc = extract_document(
        '<html lang="fa"><head><title> T  1 </title><meta name="Category" content="Pump">'
        "</head><body><h1>Main <b>heading</b></h1><h1>second</h1></body></html>"
    )
    assert (doc.title, doc.h1, doc.lang) == ("T 1", "Main heading", "fa")
    assert doc.meta == {"category": "Pump"}


def test_scripts_and_styles_are_ignored():
    doc = extract_document(
        "<style>td{}</style><script>var x='<tr><td>a</td><td>b</td></tr>';</script>"
        "<table><tr><td>Power</td><td>1 kW</td></tr></table>"
    )
    assert doc.rows == [Row("Power", "1 kW")]


def test_entities_and_line_breaks_in_cells():
    doc = extract_document("<table><tr><td>Power</td><td>22&nbsp;kW<br>(29.5 hp)</td></tr></table>")
    assert doc.rows[0].value == "22 kW (29.5 hp)"


def test_rows_with_one_cell_are_skipped():
    assert extract_document("<table><tr><td>Just a note</td></tr></table>").rows == []


def test_malformed_html_does_not_crash():
    doc = extract_document("<table><tr><td>Power<td>1 kW<tr><td>Weight</td><td>2 kg")
    assert isinstance(doc.rows, list)
