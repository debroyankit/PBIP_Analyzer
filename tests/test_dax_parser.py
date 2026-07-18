"""Unit tests for parser.dax_parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.dax_parser import extract_references


def test_simple_sum_reference():
    refs = extract_references("SUM(Sales[Amount])")
    assert refs.tables == {"Sales"}
    assert refs.qualified_columns == {"Sales[Amount]"}
    assert refs.bare_names == set()


def test_quoted_table_name():
    refs = extract_references("SUM('Fact Sales'[Amount])")
    assert refs.tables == {"Fact Sales"}
    assert refs.qualified_columns == {"Fact Sales[Amount]"}


def test_multiple_tables():
    dax = "DIVIDE(SUM(Sales[Amount]), SUM(Budget[Target]))"
    refs = extract_references(dax)
    assert refs.tables == {"Sales", "Budget"}
    assert refs.qualified_columns == {"Sales[Amount]", "Budget[Target]"}


def test_bare_measure_reference():
    refs = extract_references("[Total Sales] * 1.1")
    assert refs.bare_names == {"Total Sales"}
    assert refs.tables == set()


def test_mixed_qualified_and_bare():
    dax = "SUM(Sales[Amount]) + [Other Measure]"
    refs = extract_references(dax)
    assert refs.tables == {"Sales"}
    assert refs.qualified_columns == {"Sales[Amount]"}
    assert refs.bare_names == {"Other Measure"}


def test_multiline_variable_expression():
    dax = """
    VAR CurrentPrice = SUM('Fact Procurement'[Spend])
    VAR StandardPrice = SUM(Dim_Material[StandardCost])
    RETURN
    CurrentPrice - StandardPrice
    """
    refs = extract_references(dax)
    assert refs.tables == {"Fact Procurement", "Dim_Material"}


def test_empty_expression():
    refs = extract_references("")
    assert refs.tables == set()
    assert refs.qualified_columns == set()
    assert refs.bare_names == set()
