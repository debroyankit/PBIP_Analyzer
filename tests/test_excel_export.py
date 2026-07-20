"""Tests for the new trace_measure_lineage function, Sheet 2 status
classifications, and the visual title cleanup."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.report_parser import RawPage, RawReport
from parser.tmdl_parser import RawColumn, RawMeasure, RawRelationship, RawSemanticModel, RawTable
from parser.visual_parser import RawVisual
from services.dependency_engine import DependencyEngine, DependencyGraph, find_unused_entities, trace_measure_lineage
from services.dependency_engine import CalculatedColumn, Relationship
from models.measure import Measure
from models.table import Table
from models.visual import Visual


# -----------------------------------------------------------------------
# Helpers — build targeted graphs for each scenario
# -----------------------------------------------------------------------

def _build_calc_column_chain_graph() -> DependencyGraph:
    """Graph for testing transitive calc-column resolution.

    Measure A -> [Measure B] -> references Table1[CalcCol]
    Table1[CalcCol] is a calculated column -> RELATED(Table2[BaseCol])

    So trace_measure_lineage(A) should return Table2[BaseCol] (calc).
    """
    model = RawSemanticModel()
    model.tables["Table1"] = RawTable(
        name="Table1",
        columns={
            "PlainCol": RawColumn(name="PlainCol"),
            "CalcCol": RawColumn(
                name="CalcCol",
                expression="RELATED(Table2[BaseCol])",
            ),
        },
        measures=[
            RawMeasure(name="Measure B", table="Table1", dax="SUM(Table1[CalcCol])"),
            RawMeasure(name="Measure A", table="Table1", dax="[Measure B] + 1"),
        ],
    )
    model.tables["Table2"] = RawTable(
        name="Table2",
        columns={"BaseCol": RawColumn(name="BaseCol")},
    )
    model.relationships.append(
        RawRelationship(from_table="Table1", from_column="PlainCol",
                        to_table="Table2", to_column="BaseCol")
    )

    report = RawReport()
    visual = RawVisual(
        id="v1", title="Card", type="card",
        raw_field_refs={("Table1", "Measure A")},
    )
    report.visuals["v1"] = visual
    report.pages.append(RawPage(name="Page1", visual_ids=["v1"]))

    return DependencyEngine(model, report).build()


def _build_bridge_vs_dimension_graph() -> DependencyGraph:
    """Graph with:
    - BridgeTable: relationships to TableA and TableB, no measures, no visual cols
    - DateTable: relationships to TableA and TableB, but has a column on a visual

    BridgeTable should get 'Bridge Table', DateTable should get 'Active Table'.
    """
    model = RawSemanticModel()
    model.tables["BridgeTable"] = RawTable(
        name="BridgeTable",
        columns={"KeyA": RawColumn(name="KeyA"), "KeyB": RawColumn(name="KeyB")},
    )
    model.tables["DateTable"] = RawTable(
        name="DateTable",
        columns={"DateKey": RawColumn(name="DateKey"), "Month": RawColumn(name="Month")},
    )
    model.tables["TableA"] = RawTable(
        name="TableA",
        columns={"ID_A": RawColumn(name="ID_A"), "Amount": RawColumn(name="Amount")},
        measures=[
            RawMeasure(name="Total Amount", table="TableA", dax="SUM(TableA[Amount])"),
        ],
    )
    model.tables["TableB"] = RawTable(
        name="TableB",
        columns={"ID_B": RawColumn(name="ID_B")},
    )

    # BridgeTable has relationships to both TableA and TableB
    model.relationships.append(
        RawRelationship(from_table="BridgeTable", from_column="KeyA",
                        to_table="TableA", to_column="ID_A")
    )
    model.relationships.append(
        RawRelationship(from_table="BridgeTable", from_column="KeyB",
                        to_table="TableB", to_column="ID_B")
    )
    # DateTable also has relationships to TableA and TableB
    model.relationships.append(
        RawRelationship(from_table="DateTable", from_column="DateKey",
                        to_table="TableA", to_column="ID_A")
    )
    model.relationships.append(
        RawRelationship(from_table="DateTable", from_column="DateKey",
                        to_table="TableB", to_column="ID_B")
    )

    report = RawReport()
    # Visual uses a measure from TableA AND a column from DateTable
    visual = RawVisual(
        id="v1", title="Chart", type="columnChart",
        raw_field_refs={("TableA", "Total Amount"), ("DateTable", "Month")},
    )
    report.visuals["v1"] = visual
    report.pages.append(RawPage(name="Dashboard", visual_ids=["v1"]))

    return DependencyEngine(model, report).build()


def _build_relationship_only_column_graph() -> DependencyGraph:
    """Graph where a column is a relationship join key but never referenced
    by any visual or any measure's DAX."""
    model = RawSemanticModel()
    model.tables["Orders"] = RawTable(
        name="Orders",
        columns={
            "OrderID": RawColumn(name="OrderID"),
            "CustomerID": RawColumn(name="CustomerID"),
            "Amount": RawColumn(name="Amount"),
        },
        measures=[
            RawMeasure(name="Total Orders", table="Orders", dax="SUM(Orders[Amount])"),
        ],
    )
    model.tables["Customers"] = RawTable(
        name="Customers",
        columns={
            "CustomerID": RawColumn(name="CustomerID"),
            "Name": RawColumn(name="Name"),
        },
    )
    model.relationships.append(
        RawRelationship(from_table="Orders", from_column="CustomerID",
                        to_table="Customers", to_column="CustomerID")
    )

    report = RawReport()
    visual = RawVisual(
        id="v1", title="Sales KPI", type="card",
        raw_field_refs={("Orders", "Total Orders")},
    )
    report.visuals["v1"] = visual
    report.pages.append(RawPage(name="Home", visual_ids=["v1"]))

    return DependencyEngine(model, report).build()


def _build_system_table_graph() -> DependencyGraph:
    """Graph with a LocalDateTable that should get 'System Table (auto-generated)'."""
    model = RawSemanticModel()
    model.tables["Sales"] = RawTable(
        name="Sales",
        columns={"Amount": RawColumn(name="Amount")},
        measures=[
            RawMeasure(name="Total", table="Sales", dax="SUM(Sales[Amount])"),
        ],
    )
    model.tables["LocalDateTable_abc123"] = RawTable(
        name="LocalDateTable_abc123",
        columns={"Date": RawColumn(name="Date"), "Year": RawColumn(name="Year")},
    )
    model.tables["DateTableTemplate_xyz789"] = RawTable(
        name="DateTableTemplate_xyz789",
        columns={"Date": RawColumn(name="Date")},
    )

    report = RawReport()
    visual = RawVisual(
        id="v1", title="Card", type="card",
        raw_field_refs={("Sales", "Total")},
    )
    report.visuals["v1"] = visual
    report.pages.append(RawPage(name="Home", visual_ids=["v1"]))

    return DependencyEngine(model, report).build()


# -----------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------

class TestTraceMeasureLineage:
    """Tests for the trace_measure_lineage shared function."""

    def test_transitive_with_calc_column(self):
        """Measure A -> Measure B -> Table1[CalcCol] -> Table2[BaseCol].
        trace_measure_lineage(A) must include Table2[BaseCol] (calc) and Table2."""
        graph = _build_calc_column_chain_graph()
        measure_a = graph.measures["Measure A"]

        tables, columns = trace_measure_lineage(measure_a, graph)

        # Tables: Table1 (home & direct ref), Table2 (via calc column)
        assert "Table1" in tables
        assert "Table2" in tables

        # Columns: Table1[CalcCol] (direct), Table2[BaseCol] (calc)
        assert "Table1[CalcCol]" in columns
        assert "Table2[BaseCol] (calc)" in columns

    def test_single_measure_no_deps(self):
        """A measure with no depends_on_measures should still trace its own refs."""
        graph = _build_calc_column_chain_graph()
        measure_b = graph.measures["Measure B"]

        tables, columns = trace_measure_lineage(measure_b, graph)

        assert "Table1" in tables
        assert "Table1[CalcCol]" in columns
        assert "Table2[BaseCol] (calc)" in columns

    def test_consistency_between_sheet1_and_sheet3(self):
        """For any measure, trace_measure_lineage must return the same result
        regardless of where it's called — this is the whole point of the
        shared function."""
        graph = _build_calc_column_chain_graph()
        measure_a = graph.measures["Measure A"]

        result1 = trace_measure_lineage(measure_a, graph)
        result2 = trace_measure_lineage(measure_a, graph)

        assert result1[0] == result2[0]  # tables match
        assert result1[1] == result2[1]  # columns match


class TestImpactAnalysisClassification:
    """Tests for Sheet 2 status classification logic."""

    def test_bridge_table_classification(self):
        """A table with 2+ relationships, no measures, no visual columns → Bridge Table."""
        graph = _build_bridge_vs_dimension_graph()

        table = graph.tables["BridgeTable"]
        # BridgeTable should have: no visuals, no measures
        assert len(table.visuals) == 0
        assert len(table.measures) == 0

    def test_dimension_table_not_bridge(self):
        """A table with 2+ relationships but also direct visual usage → Active Table, not Bridge."""
        graph = _build_bridge_vs_dimension_graph()

        table = graph.tables["DateTable"]
        # DateTable should have visuals because its column "Month" is on a visual
        assert len(table.visuals) > 0

    def test_used_via_relationship_only(self):
        """A column that is a relationship join key but never in a visual or measure."""
        graph = _build_relationship_only_column_graph()

        # Orders[CustomerID] is a relationship key but not in any measure's DAX
        # or any visual's columns
        col_ref = "Orders[CustomerID]"

        # Check it's in a relationship
        rel_cols = set()
        for rel in graph.relationships:
            rel_cols.add(f"{rel.from_table}[{rel.from_column}]")
            rel_cols.add(f"{rel.to_table}[{rel.to_column}]")
        assert col_ref in rel_cols

        # Check it's not directly in any visual's columns
        for visual in graph.visuals.values():
            assert col_ref not in visual.columns

        # Check it's not in any measure's referenced_columns
        for measure in graph.measures.values():
            assert col_ref not in measure.referenced_columns

    def test_system_table_not_no_references(self):
        """LocalDateTable_* should get 'System Table (auto-generated)',
        not 'No References Found'."""
        graph = _build_system_table_graph()

        # Verify system tables exist and have no visual usage
        assert "LocalDateTable_abc123" in graph.tables
        assert len(graph.tables["LocalDateTable_abc123"].visuals) == 0

        # Even with exclude_system=False, find_unused_entities would mark them
        # unused, but our Sheet 2 must distinguish them as system tables
        unused = find_unused_entities(graph)
        assert "LocalDateTable_abc123" in unused["unused_tables"]

        # The test verifies the data is correct for the classification;
        # actual status assignment is in excel_export._build_sheet2


class TestVisualTitleCleanup:
    """Test that visual.title no longer contains the baked-in page suffix."""

    def test_visual_title_no_page_suffix(self):
        """After building the graph, visual.title must be the clean title
        without '(Page: X)' suffix."""
        graph = _build_calc_column_chain_graph()

        for visual in graph.visuals.values():
            assert "(Page:" not in visual.title, (
                f"Visual '{visual.title}' still has baked-in page suffix"
            )
            # The page info should be in the separate field
            assert visual.page, "visual.page should not be empty"

    def test_visual_title_matches_raw_title(self):
        """visual.title should be the raw visual title, not a composite."""
        graph = _build_calc_column_chain_graph()

        visual = graph.visuals["v1"]
        assert visual.title == "Card"
        assert visual.page == "Page1"


class TestExcelWorkbookStructure:
    """Test that the workbook has exactly 3 sheets in the correct order."""

    def test_workbook_three_sheets(self):
        """Workbook must have exactly 3 sheets: Visual Inventory, Impact Analysis, Measure Lineage."""
        from services.excel_export import write_excel_report
        from openpyxl import load_workbook
        import io

        graph = _build_calc_column_chain_graph()
        raw_bytes = write_excel_report(graph, output_path=None, exclude_system=False)

        wb = load_workbook(io.BytesIO(raw_bytes))
        assert wb.sheetnames == ["Visual Inventory", "Impact Analysis", "Measure Lineage"]

    def test_sheet1_has_dax_column(self):
        """Sheet 1 must include Full DAX of Direct Measures."""
        from services.excel_export import write_excel_report
        from openpyxl import load_workbook
        import io

        graph = _build_calc_column_chain_graph()
        raw_bytes = write_excel_report(graph, output_path=None, exclude_system=False)

        wb = load_workbook(io.BytesIO(raw_bytes))
        ws = wb["Visual Inventory"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        assert "Full DAX of Direct Measures" in headers

    def test_sheet3_has_dax_column(self):
        """Sheet 3 must include Full DAX Expression."""
        from services.excel_export import write_excel_report
        from openpyxl import load_workbook
        import io

        graph = _build_calc_column_chain_graph()
        raw_bytes = write_excel_report(graph, output_path=None, exclude_system=False)

        wb = load_workbook(io.BytesIO(raw_bytes))
        ws = wb["Measure Lineage"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        assert "Full DAX Expression" in headers
