"""Unit tests for parser.tmdl_parser (TMDL-format table/measure parsing)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.tmdl_parser import _parse_tmdl_tables, _parse_tmdl_relationships


SAMPLE_TABLE_TMDL = """
table 'Fact Procurement'

\tcolumn Spend
\t\tdataType: double
\t\tsummarizeBy: sum

\tcolumn Vendor
\t\tdataType: string

\tcolumn Effective Rate = RELATED(ExchangeRate[Rate]) * [Spend]
\t\tdataType: double
\t\tlineageTag: def-456

\tmeasure 'Total Spend' = SUM('Fact Procurement'[Spend])
\t\tformatString: "#,0"

\tmeasure 'Complex Measure' =
\t\t\tVAR x = SUM('Fact Procurement'[Spend])
\t\t\tRETURN
\t\t\tx * 2
\t\tformatString: "#,0"
\t\tlineageTag: abc-123

\tpartition 'Fact Procurement' = m
\t\tmode: import
"""


def test_parses_table_name():
    tables = _parse_tmdl_tables(SAMPLE_TABLE_TMDL)
    assert len(tables) == 1
    assert tables[0].name == "Fact Procurement"


def test_parses_columns():
    tables = _parse_tmdl_tables(SAMPLE_TABLE_TMDL)
    assert set(tables[0].columns) == {"Spend", "Vendor", "Effective Rate"}


def test_parses_calculated_column_expression_without_leaking_properties():
    tables = _parse_tmdl_tables(SAMPLE_TABLE_TMDL)
    calc_column = tables[0].columns["Effective Rate"]
    assert calc_column.expression == "RELATED(ExchangeRate[Rate]) * [Spend]"
    assert "lineageTag" not in calc_column.expression


def test_plain_columns_have_no_expression():
    tables = _parse_tmdl_tables(SAMPLE_TABLE_TMDL)
    assert tables[0].columns["Spend"].expression == ""
    assert tables[0].columns["Vendor"].expression == ""


def test_parses_simple_measure_without_leaking_properties():
    tables = _parse_tmdl_tables(SAMPLE_TABLE_TMDL)
    measures = {m.name: m.dax for m in tables[0].measures}
    assert measures["Total Spend"] == "SUM('Fact Procurement'[Spend])"
    assert "formatString" not in measures["Total Spend"]


def test_parses_multiline_measure_without_leaking_properties():
    tables = _parse_tmdl_tables(SAMPLE_TABLE_TMDL)
    measures = {m.name: m.dax for m in tables[0].measures}
    dax = measures["Complex Measure"]
    assert "VAR x = SUM('Fact Procurement'[Spend])" in dax
    assert "RETURN" in dax
    assert "formatString" not in dax
    assert "lineageTag" not in dax


def test_parses_relationships():
    rel_text = (
        "relationship abc\n"
        "\tfromColumn: 'Fact Procurement'.Vendor\n"
        "\ttoColumn: Dim_Vendor.Vendor\n"
    )
    rels = _parse_tmdl_relationships(rel_text)
    assert len(rels) == 1
    assert rels[0].from_table == "Fact Procurement"
    assert rels[0].from_column == "Vendor"
    assert rels[0].to_table == "Dim_Vendor"
    assert rels[0].to_column == "Vendor"
