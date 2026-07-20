"""Builds the cross-referenced dependency graph between tables, measures,
visuals and pages.

This is the single place where raw parser output (tables/measures from the
semantic model, pages/visuals from the report) is combined and linked. Kept
separate from the parsers so it can be unit-tested independently and so a
future FastAPI layer can call `DependencyEngine.build()` directly against
already-parsed data without touching the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from models.measure import Measure
from models.page import Page
from models.table import Table
from models.visual import Visual
from parser.dax_parser import extract_references
from parser.report_parser import RawReport
from parser.tmdl_parser import RawSemanticModel
from utils.logging_config import get_logger

logger = get_logger("dependency_engine")


@dataclass
class Relationship:
    """A relationship edge between two tables, as declared in the model."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str

    def to_dict(self) -> dict[str, str]:
        return {
            "from_table": self.from_table,
            "from_column": self.from_column,
            "to_table": self.to_table,
            "to_column": self.to_column,
        }


@dataclass
class CalculatedColumn:
    """A calculated column's formula and the tables it reaches into."""

    table: str
    column: str
    expression: str
    referenced_tables: set[str] = field(default_factory=set)
    referenced_columns: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, object]:
        return {
            "table": self.table,
            "expression": self.expression,
            "referenced_tables": sorted(self.referenced_tables),
            "referenced_columns": sorted(self.referenced_columns),
        }


@dataclass
class DependencyGraph:
    """Fully linked output: one repository per entity type, keyed by name/id."""

    tables: dict[str, Table] = field(default_factory=dict)
    measures: dict[str, Measure] = field(default_factory=dict)
    visuals: dict[str, Visual] = field(default_factory=dict)
    pages: dict[str, Page] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    calculated_columns: dict[str, CalculatedColumn] = field(default_factory=dict)  # key: "Table[Column]"


class DependencyEngine:
    """Combines a RawSemanticModel and RawReport into a DependencyGraph."""

    def __init__(self, semantic_model: RawSemanticModel, report: RawReport) -> None:
        self._semantic_model = semantic_model
        self._report = report

    def build(self) -> DependencyGraph:
        """Run the full build pipeline and return the linked graph.

        Order matters:
            1. Tables + columns (from the semantic model).
            2. Measures, with DAX-derived table/column references.
            3. Calculated columns, with DAX-derived table references.
            4. Relationships, linking related tables directly.
            5. Pages + visuals (from the report), with fields classified as
               columns vs. measures using the model built in steps 1-2.
            6. Cross-link everything (table<->measure, table<->visual,
               table<->page, measure<->visual, measure<->page).
        """
        graph = DependencyGraph()

        self._build_tables(graph)
        self._build_measures(graph)
        self._build_calculated_columns(graph)
        self._build_relationships(graph)
        self._build_pages_and_visuals(graph)
        self._link_measures_to_tables(graph)
        self._link_visuals_to_tables_and_measures(graph)
        self._link_pages(graph)

        return graph

    # ------------------------------------------------------------------
    # Step 1: tables/columns
    # ------------------------------------------------------------------

    def _build_tables(self, graph: DependencyGraph) -> None:
        for raw_table in self._semantic_model.tables.values():
            # `raw_table.columns` is a dict[str, RawColumn]; iterating/`set()`-ing
            # a dict yields its keys, which is exactly the plain column-name set
            # the Table model needs.
            graph.tables[raw_table.name] = Table(name=raw_table.name, columns=set(raw_table.columns))

    # ------------------------------------------------------------------
    # Step 2: measures
    # ------------------------------------------------------------------

    def _build_measures(self, graph: DependencyGraph) -> None:
        for raw_table in self._semantic_model.tables.values():
            for raw_measure in raw_table.measures:
                dax_refs = extract_references(raw_measure.dax)

                referenced_tables = set(dax_refs.tables)
                referenced_tables.add(raw_measure.table)  # a measure always "belongs" to its home table

                measure = Measure(
                    name=raw_measure.name,
                    table=raw_measure.table,
                    dax=raw_measure.dax,
                    referenced_tables=referenced_tables,
                    referenced_columns=set(dax_refs.qualified_columns),
                )

                if raw_measure.name in graph.measures:
                    logger.warning(
                        "Duplicate measure name '%s' found on table '%s' "
                        "(already defined on '%s'); keeping the first definition.",
                        raw_measure.name,
                        raw_measure.table,
                        graph.measures[raw_measure.name].table,
                    )
                    continue

                graph.measures[raw_measure.name] = measure

        # Resolve bare "[Name]" references (found via dax_parser) against
        # the full set of known measure names, now that every measure has
        # been registered. This also records the measure-to-measure
        # dependency edge in both directions for lineage purposes.
        all_measure_names = set(graph.measures.keys())
        for measure in graph.measures.values():
            dax_refs = extract_references(measure.dax)
            for bare_name in dax_refs.bare_names:
                if bare_name in all_measure_names and bare_name != measure.name:
                    referenced_measure = graph.measures[bare_name]
                    measure.referenced_tables |= referenced_measure.referenced_tables
                    measure.depends_on_measures.add(bare_name)
                    referenced_measure.used_by_measures.add(measure.name)

    # ------------------------------------------------------------------
    # Step 3: calculated columns
    # ------------------------------------------------------------------

    def _build_calculated_columns(self, graph: DependencyGraph) -> None:
        """Extract cross-table references from calculated column formulas.

        A calculated column such as::

            column Savings = RELATED(Invoice[Discount Percent]) * [Invoice Amount]

        creates a real dependency from its table onto ``Invoice``, even
        though no relationship or measure captures that link. We record it
        both as a standalone `CalculatedColumn` (for the detailed report)
        and by growing each table's `related_tables` set (for the at-a-
        glance table view).
        """
        for raw_table in self._semantic_model.tables.values():
            for raw_column in raw_table.columns.values():
                if not raw_column.expression:
                    continue

                dax_refs = extract_references(raw_column.expression)
                referenced_tables = {t for t in dax_refs.tables if t != raw_table.name}

                key = f"{raw_table.name}[{raw_column.name}]"
                graph.calculated_columns[key] = CalculatedColumn(
                    table=raw_table.name,
                    column=raw_column.name,
                    expression=raw_column.expression,
                    referenced_tables=referenced_tables,
                    referenced_columns=set(dax_refs.qualified_columns),
                )

                if not referenced_tables:
                    continue

                home_table = graph.tables.get(raw_table.name)
                for other_table_name in referenced_tables:
                    if home_table is not None:
                        home_table.related_tables.add(other_table_name)
                    other_table = graph.tables.get(other_table_name)
                    if other_table is not None:
                        other_table.related_tables.add(raw_table.name)

    # ------------------------------------------------------------------
    # Step 4: relationships
    # ------------------------------------------------------------------

    def _build_relationships(self, graph: DependencyGraph) -> None:
        """Record model relationships and link each pair of tables directly."""
        for raw_rel in self._semantic_model.relationships:
            graph.relationships.append(
                Relationship(
                    from_table=raw_rel.from_table,
                    from_column=raw_rel.from_column,
                    to_table=raw_rel.to_table,
                    to_column=raw_rel.to_column,
                )
            )

            from_table = graph.tables.get(raw_rel.from_table)
            to_table = graph.tables.get(raw_rel.to_table)
            if from_table is not None and raw_rel.to_table:
                from_table.related_tables.add(raw_rel.to_table)
            if to_table is not None and raw_rel.from_table:
                to_table.related_tables.add(raw_rel.from_table)

    # ------------------------------------------------------------------
    # Step 5: pages + visuals
    # ------------------------------------------------------------------

    def _build_pages_and_visuals(self, graph: DependencyGraph) -> None:
        measure_names = set(graph.measures.keys())
        table_measure_names: dict[str, set[str]] = {
            table_name: {m.name for m in graph.measures.values() if table_name in m.referenced_tables}
            for table_name in graph.tables
        }

        for raw_page in self._report.pages:
            page = Page(name=raw_page.name)

            for visual_id in raw_page.visual_ids:
                raw_visual = self._report.visuals.get(visual_id)
                if raw_visual is None:
                    continue

                visual = Visual(
                    id=raw_visual.id,
                    title=raw_visual.title,
                    type=raw_visual.type,
                    page=page.name,
                    raw_field_refs=set(raw_visual.raw_field_refs),
                )

                for table_name, field_name in raw_visual.raw_field_refs:
                    visual.tables.add(table_name)
                    is_measure = field_name in measure_names and field_name in table_measure_names.get(
                        table_name, set()
                    )
                    if is_measure or field_name in measure_names:
                        visual.measures.add(field_name)
                    else:
                        visual.columns.add(f"{table_name}[{field_name}]")

                graph.visuals[visual.id] = visual
                page.visuals.add(visual.title)

            graph.pages[page.name] = page

    # ------------------------------------------------------------------
    # Step 6: cross-linking
    # ------------------------------------------------------------------

    def _link_measures_to_tables(self, graph: DependencyGraph) -> None:
        """Table.measures = every measure whose referenced_tables includes it."""
        for measure in graph.measures.values():
            for table_name in measure.referenced_tables:
                table = graph.tables.get(table_name)
                if table is not None:
                    table.measures.add(measure.name)
                else:
                    logger.debug(
                        "Measure '%s' references unknown table '%s' (not in semantic model).",
                        measure.name,
                        table_name,
                    )

    def _link_visuals_to_tables_and_measures(self, graph: DependencyGraph) -> None:
        """Expand each visual's tables transitively through the measures it
        uses, then link tables <-> visuals and measures <-> visuals/pages.
        """
        for visual in graph.visuals.values():
            for measure_name in list(visual.measures):
                measure = graph.measures.get(measure_name)
                if measure is None:
                    continue
                visual.tables |= measure.referenced_tables
                measure.visuals.add(visual.title)
                measure.pages.add(visual.page)

            for table_name in visual.tables:
                table = graph.tables.get(table_name)
                if table is not None:
                    table.visuals.add(visual.title)
                    table.pages.add(visual.page)

    def _link_pages(self, graph: DependencyGraph) -> None:
        """Page.tables = union of tables of every visual on that page."""
        for visual in graph.visuals.values():
            page = graph.pages.get(visual.page)
            if page is not None:
                page.tables |= visual.tables


def find_unused_entities(graph: DependencyGraph) -> dict[str, object]:
    """Identify tables, measures, and columns that appear unused in the report.

    "Unused" means never referenced by any visual (transitively for measures,
    and considering relationships/DAX/calculated columns for columns) -- a
    useful model-hygiene signal. This is purely a report on top of the already
    -built graph; it does not mutate anything.

    Returns:
        A dict with three keys:
            - "unused_tables": table names with no visuals.
            - "unused_measures": measure names with no visuals (transitively).
            - "unused_columns": {table_name: [column_names]} for tables that
              have at least one column never referenced.
    """
    # 1. Trace used measures transitively
    used_measures: set[str] = set()
    queue_measures: list[str] = []
    for visual in graph.visuals.values():
        for m in visual.measures:
            if m in graph.measures and m not in used_measures:
                used_measures.add(m)
                queue_measures.append(m)

    while queue_measures:
        current_m = queue_measures.pop(0)
        measure_obj = graph.measures[current_m]
        for dep in measure_obj.depends_on_measures:
            if dep in graph.measures and dep not in used_measures:
                used_measures.add(dep)
                queue_measures.append(dep)

    unused_tables = sorted(name for name, table in graph.tables.items() if not table.visuals)
    unused_measures = sorted(name for name in graph.measures if name not in used_measures)

    # 2. Trace used columns
    used_columns: set[str] = set()

    # Columns directly referenced in visuals
    for visual in graph.visuals.values():
        for col in visual.columns:
            used_columns.add(col)

    # Columns referenced by used measures
    for m in used_measures:
        measure_obj = graph.measures[m]
        for ref_col in measure_obj.referenced_columns:
            used_columns.add(ref_col)

    # Columns used in relationships
    for rel in graph.relationships:
        used_columns.add(f"{rel.from_table}[{rel.from_column}]")
        used_columns.add(f"{rel.to_table}[{rel.to_column}]")

    # Columns referenced by used calculated columns (trace recursively)
    queue_columns = list(used_columns)
    visited_calc_cols: set[str] = set()

    while queue_columns:
        current_col = queue_columns.pop(0)
        if current_col in graph.calculated_columns and current_col not in visited_calc_cols:
            visited_calc_cols.add(current_col)
            calc_col = graph.calculated_columns[current_col]
            for ref_col in calc_col.referenced_columns:
                if ref_col not in used_columns:
                    used_columns.add(ref_col)
                    queue_columns.append(ref_col)

    unused_columns: dict[str, list[str]] = {}
    for table_name, table in graph.tables.items():
        table_prefix = f"{table_name}["
        table_used = set()
        for col in used_columns:
            if col.startswith(table_prefix) and col.endswith("]"):
                col_name = col[len(table_prefix):-1]
                table_used.add(col_name)
        unused = sorted(table.columns - table_used)
        if unused:
            unused_columns[table_name] = unused

    return {
        "unused_tables": unused_tables,
        "unused_measures": unused_measures,
        "unused_columns": unused_columns,
    }


def trace_measure_lineage(
    measure: Measure, graph: DependencyGraph
) -> tuple[set[str], set[str]]:
    """Return (tables, columns) a measure ultimately depends on, transitively
    through every measure it calls (measure.depends_on_measures), with
    calculated-column references resolved down to their base columns.

    ``columns`` uses "Table[Column]" format; entries reached only via a
    calculated column's RELATED()/RELATEDTABLE() formula are suffixed " (calc)".
    """
    # 1. Walk depends_on_measures transitively (BFS)
    all_measures_in_chain: list[Measure] = [measure]
    visited_measures: set[str] = {measure.name}
    queue: list[str] = list(measure.depends_on_measures)

    while queue:
        dep_name = queue.pop(0)
        if dep_name in visited_measures:
            continue
        visited_measures.add(dep_name)
        dep_measure = graph.measures.get(dep_name)
        if dep_measure is not None:
            all_measures_in_chain.append(dep_measure)
            for sub_dep in dep_measure.depends_on_measures:
                if sub_dep not in visited_measures:
                    queue.append(sub_dep)

    # 2. Union referenced_tables and referenced_columns from every measure
    tables: set[str] = set()
    columns: set[str] = set()
    for m in all_measures_in_chain:
        tables |= m.referenced_tables
        columns |= m.referenced_columns

    # 3. Resolve calculated-column references to their base columns
    #    Reuses the exact BFS pattern from find_unused_entities.
    col_queue = list(columns)
    visited_calc_cols: set[str] = set()
    calc_derived_columns: set[str] = set()

    while col_queue:
        current_col = col_queue.pop(0)
        if current_col in graph.calculated_columns and current_col not in visited_calc_cols:
            visited_calc_cols.add(current_col)
            calc_col = graph.calculated_columns[current_col]
            # Add the calculated column's own referenced tables
            tables |= calc_col.referenced_tables
            for ref_col in calc_col.referenced_columns:
                if ref_col not in columns:
                    # Mark as calc-derived
                    calc_derived_columns.add(ref_col)
                    col_queue.append(ref_col)

    # 4. Build final columns set with (calc) suffix for calc-derived entries
    final_columns: set[str] = set()
    for col in columns:
        final_columns.add(col)
    for col in calc_derived_columns:
        final_columns.add(f"{col} (calc)")

    return tables, final_columns
