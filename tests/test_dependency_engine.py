"""Integration tests for services.dependency_engine using small in-memory
raw structures (no filesystem involved)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.report_parser import RawPage, RawReport
from parser.tmdl_parser import RawMeasure, RawSemanticModel, RawTable
from parser.visual_parser import RawVisual
from services.dependency_engine import DependencyEngine


def _build_sample_model() -> RawSemanticModel:
    model = RawSemanticModel()
    model.tables["Sales"] = RawTable(
        name="Sales",
        columns={"Amount", "Region"},
        measures=[RawMeasure(name="Total Sales", table="Sales", dax="SUM(Sales[Amount])")],
    )
    model.tables["Budget"] = RawTable(
        name="Budget",
        columns={"Target"},
        measures=[
            RawMeasure(
                name="Variance",
                table="Sales",
                dax="SUM(Sales[Amount]) - SUM(Budget[Target])",
            )
        ],
    )
    return model


def _build_sample_report() -> RawReport:
    report = RawReport()
    visual = RawVisual(
        id="v1",
        title="Sales Card",
        type="card",
        raw_field_refs={("Sales", "Total Sales")},
    )
    report.visuals["v1"] = visual
    page = RawPage(name="Home", visual_ids=["v1"])
    report.pages.append(page)
    return report


def test_measure_linked_to_home_table():
    graph = DependencyEngine(_build_sample_model(), _build_sample_report()).build()
    assert "Total Sales" in graph.tables["Sales"].measures


def test_measure_linked_to_transitively_referenced_table():
    graph = DependencyEngine(_build_sample_model(), _build_sample_report()).build()
    # "Variance" measure's home table is Sales, but its DAX also touches Budget.
    assert "Variance" in graph.tables["Budget"].measures


def test_visual_expands_tables_through_measure():
    graph = DependencyEngine(_build_sample_model(), _build_sample_report()).build()
    visual = graph.visuals["v1"]
    assert visual.tables == {"Sales"}  # Total Sales only references Sales


def test_page_aggregates_visual_tables():
    graph = DependencyEngine(_build_sample_model(), _build_sample_report()).build()
    page = graph.pages["Home"]
    assert "Sales Card" in page.visuals
    assert page.tables == {"Sales"}


def test_table_tracks_pages_via_visual():
    graph = DependencyEngine(_build_sample_model(), _build_sample_report()).build()
    assert "Home" in graph.tables["Sales"].pages
