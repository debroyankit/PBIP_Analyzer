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
class DependencyGraph:
    """Fully linked output: one repository per entity type, keyed by name/id."""

    tables: dict[str, Table] = field(default_factory=dict)
    measures: dict[str, Measure] = field(default_factory=dict)
    visuals: dict[str, Visual] = field(default_factory=dict)
    pages: dict[str, Page] = field(default_factory=dict)


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
            3. Pages + visuals (from the report), with fields classified as
               columns vs. measures using the model built in steps 1-2.
            4. Cross-link everything (table<->measure, table<->visual,
               table<->page, measure<->visual, measure<->page).
        """
        graph = DependencyGraph()

        self._build_tables(graph)
        self._build_measures(graph)
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
        # been registered.
        all_measure_names = set(graph.measures.keys())
        for measure in graph.measures.values():
            dax_refs = extract_references(measure.dax)
            for bare_name in dax_refs.bare_names:
                if bare_name in all_measure_names and bare_name != measure.name:
                    referenced_measure = graph.measures[bare_name]
                    measure.referenced_tables |= referenced_measure.referenced_tables

    # ------------------------------------------------------------------
    # Step 3: pages + visuals
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
    # Step 4: cross-linking
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
