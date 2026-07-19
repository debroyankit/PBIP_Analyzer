"""Integration tests for services.dependency_engine using small in-memory
raw structures (no filesystem involved)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.report_parser import RawPage, RawReport
from parser.tmdl_parser import RawColumn, RawMeasure, RawRelationship, RawSemanticModel, RawTable
from parser.visual_parser import RawVisual
from services.dependency_engine import DependencyEngine, find_unused_entities


def _build_sample_model() -> RawSemanticModel:
    model = RawSemanticModel()
    model.tables["Sales"] = RawTable(
        name="Sales",
        columns={"Amount": RawColumn(name="Amount"), "Region": RawColumn(name="Region")},
        measures=[
            RawMeasure(name="Total Sales", table="Sales", dax="SUM(Sales[Amount])"),
            RawMeasure(name="Total Sales Rounded", table="Sales", dax="ROUND([Total Sales], 0)"),
        ],
    )
    model.tables["Budget"] = RawTable(
        name="Budget",
        columns={"Target": RawColumn(name="Target")},
        measures=[
            RawMeasure(
                name="Variance",
                table="Sales",
                dax="SUM(Sales[Amount]) - SUM(Budget[Target])",
            )
        ],
    )
    model.tables["Region"] = RawTable(
        name="Region",
        columns={
            "RegionID": RawColumn(name="RegionID"),
            "SalesRegionName": RawColumn(
                name="SalesRegionName", expression="RELATED(Sales[Region])"
            ),
        },
    )
    model.relationships.append(
        RawRelationship(from_table="Sales", from_column="Region", to_table="Region", to_column="RegionID")
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


def _build_graph():
    return DependencyEngine(_build_sample_model(), _build_sample_report()).build()


def test_measure_linked_to_home_table():
    graph = _build_graph()
    assert "Total Sales" in graph.tables["Sales"].measures


def test_measure_linked_to_transitively_referenced_table():
    graph = _build_graph()
    # "Variance" measure's home table is Sales, but its DAX also touches Budget.
    assert "Variance" in graph.tables["Budget"].measures


def test_visual_expands_tables_through_measure():
    graph = _build_graph()
    visual = graph.visuals["v1"]
    assert visual.tables == {"Sales"}  # Total Sales only references Sales


def test_page_aggregates_visual_tables():
    graph = _build_graph()
    page = graph.pages["Home"]
    assert "Sales Card (Page: Home)" in page.visuals
    assert page.tables == {"Sales"}


def test_table_tracks_pages_via_visual():
    graph = _build_graph()
    assert "Home" in graph.tables["Sales"].pages


def test_measure_to_measure_dependency_recorded_both_directions():
    graph = _build_graph()
    assert "Total Sales" in graph.measures["Total Sales Rounded"].depends_on_measures
    assert "Total Sales Rounded" in graph.measures["Total Sales"].used_by_measures


def test_relationship_links_related_tables():
    graph = _build_graph()
    assert "Region" in graph.tables["Sales"].related_tables
    assert "Sales" in graph.tables["Region"].related_tables
    assert len(graph.relationships) == 1
    assert graph.relationships[0].from_table == "Sales"


def test_calculated_column_creates_related_table_link():
    graph = _build_graph()
    # Region.SalesRegionName = RELATED(Sales[Region]) should link Region <-> Sales
    assert "Sales" in graph.tables["Region"].related_tables
    calc = graph.calculated_columns["Region[SalesRegionName]"]
    assert calc.referenced_tables == {"Sales"}


def test_find_unused_entities_reports_unqueried_table_and_measure():
    graph = _build_graph()
    unused = find_unused_entities(graph)
    # "Budget" and "Region" tables have no visual using them directly.
    assert "Budget" in unused["unused_tables"]
    assert "Region" in unused["unused_tables"]
    # "Variance" and "Total Sales Rounded" measures are never used by a visual.
    assert "Variance" in unused["unused_measures"]
    assert "Total Sales Rounded" in unused["unused_measures"]
    # "Region" column on Sales is used in a relationship, so it should not be reported as unused.
    assert "Region" not in unused["unused_columns"].get("Sales", [])
    # "SalesRegionName" calculated column on Region is never queried, so it is unused.
    assert "SalesRegionName" in unused["unused_columns"].get("Region", [])


def test_transitive_unused_entities_and_system_filtering():
    from main import is_system_table

    # 1. Verify system table identifier works
    assert is_system_table("LocalDateTable_1afc3cbb-645a-4716-b8f1-81b44dd03210") is True
    assert is_system_table("DateTableTemplate_9026e257-1032-4e83-b623-381c584ebfac") is True
    assert is_system_table("Fact Sales") is False

    # 2. Verify transitive column usage works
    graph = _build_graph()
    unused = find_unused_entities(graph)

    # "Amount" column on Sales is referenced in "Total Sales" measure, which is in visual "v1".
    # So "Amount" should not be marked as unused.
    assert "Amount" not in unused["unused_columns"].get("Sales", [])
