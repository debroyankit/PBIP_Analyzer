"""Export a DependencyGraph to a formatted Excel workbook (.xlsx).

Generates exactly three sheets:

    Sheet 1 — Table Dependency Summary
        One row per table. Aggregated columns, measures, and visuals.

    Sheet 2 — Detailed Dependency Mapping
        One row per (table, column, measure, visual) combination.
        Ideal for filtering/searching specific dependencies.

    Sheet 3 — DAX Dependency Lineage
        One row per measure showing which tables and other measures it
        depends on, and the final set of tables reached transitively.

Requires: openpyxl  (pip install openpyxl)
"""

from __future__ import annotations

import io
from itertools import product
from pathlib import Path
from typing import Union

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from services.dependency_engine import DependencyGraph
from utils.logging_config import get_logger

logger = get_logger("excel_export")

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_HEADER_FILL = PatternFill("solid", fgColor="1F3864")   # deep navy
_HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_BODY_FONT   = Font(name="Calibri", size=10)
_WRAP_ALIGN  = Alignment(wrap_text=True, vertical="top")
_TOP_ALIGN   = Alignment(vertical="top")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_excel_report(
    graph: DependencyGraph,
    output_path: Union[str, Path, None] = None,
    exclude_system: bool = False,
) -> bytes:
    """Build and save an Excel workbook from a fully-linked DependencyGraph.

    Args:
        graph:         The completed DependencyGraph returned by DependencyEngine.build().
        output_path:   Optional filesystem path to write the .xlsx file.
                       If None the workbook is only returned as raw bytes.
        exclude_system: When True, skip LocalDateTable_* / DateTableTemplate_* tables.

    Returns:
        The raw bytes of the .xlsx workbook (useful for in-memory delivery,
        e.g. a Streamlit download button).
    """
    wb = Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    _build_sheet1(wb, graph, exclude_system)
    _build_sheet2(wb, graph, exclude_system)
    _build_sheet3(wb, graph, exclude_system)

    buf = io.BytesIO()
    wb.save(buf)
    raw = buf.getvalue()

    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        logger.info("Wrote Excel report: %s", path)

    return raw


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_system(name: str) -> bool:
    return name.startswith("LocalDateTable_") or name.startswith("DateTableTemplate_")


def _join(items: set | list, sep: str = ", ") -> str:
    """Convert a set/list to a sorted, deduplicated string. Returns '' if empty."""
    cleaned = sorted({str(i) for i in items if i})
    return sep.join(cleaned) if cleaned else ""


def _style_header(ws, n_cols: int) -> None:
    """Apply navy header style and freeze the top row."""
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=1, column=col)
        cell.font   = _HEADER_FONT
        cell.fill   = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _auto_width(ws, min_w: int = 12, max_w: int = 60) -> None:
    """Estimate column widths based on cell contents."""
    for col_cells in ws.columns:
        best = min_w
        for cell in col_cells:
            if cell.value:
                # Use the longest line inside a wrapped cell for width estimation
                longest_line = max(str(cell.value).split("\n"), key=len, default="")
                best = max(best, min(len(longest_line) + 4, max_w))
        ws.column_dimensions[get_column_letter(col_cells[0].column)].width = best


def _write_row(ws, row_idx: int, values: list, wrap_cols: set[int] | None = None) -> None:
    for col_idx, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=col_idx, value=val or None)
        cell.font = _BODY_FONT
        if wrap_cols and col_idx in wrap_cols:
            cell.alignment = _WRAP_ALIGN
        else:
            cell.alignment = _TOP_ALIGN


# ---------------------------------------------------------------------------
# Sheet 1 — Table Dependency Summary
# ---------------------------------------------------------------------------

def _build_sheet1(wb: Workbook, graph: DependencyGraph, exclude_system: bool) -> None:
    ws = wb.create_sheet("Table Dependency Summary")

    headers = ["Table", "Columns", "Measures", "Visuals (Page)", "Total Measures", "Total Visuals"]
    ws.append(headers)
    _style_header(ws, len(headers))

    # wrap-text columns: Columns(2), Measures(3), Visuals(4)
    WRAP = {2, 3, 4}

    for name, table in sorted(graph.tables.items()):
        if exclude_system and _is_system(name):
            continue

        # Build "Visual (Page)" strings — visual titles already contain "(Page: X)"
        # supplied by the engine; here we normalise them to "Title (Page)" format.
        visual_page_parts: list[str] = []
        for visual_title in sorted(table.visuals):
            # Engine stores titles as "Title (Page: PageName)"
            # Convert to "Title (PageName)" for the Excel cell
            normalised = visual_title.replace("(Page: ", "(").rstrip(")")
            if normalised.endswith(")"):
                visual_page_parts.append(normalised)
            else:
                visual_page_parts.append(visual_title)

        cols_str    = _join(table.columns)
        measures_str = _join(table.measures)
        visuals_str  = "\n".join(visual_page_parts) if visual_page_parts else ""

        _write_row(
            ws,
            ws.max_row + 1,
            [
                name,
                cols_str,
                measures_str,
                visuals_str,
                len(table.measures),
                len(table.visuals),
            ],
            wrap_cols=WRAP,
        )

    _auto_width(ws)
    # Give fixed widths to the count columns
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 14


# ---------------------------------------------------------------------------
# Sheet 2 — Detailed Dependency Mapping
# ---------------------------------------------------------------------------

def _build_sheet2(wb: Workbook, graph: DependencyGraph, exclude_system: bool) -> None:
    ws = wb.create_sheet("Detailed Dependency Mapping")

    headers = ["Table", "Column", "Measure", "Visual Name", "Visual Type", "Page Name"]
    ws.append(headers)
    _style_header(ws, len(headers))

    seen: set[tuple] = set()

    for visual in sorted(graph.visuals.values(), key=lambda v: (v.page, v.title)):
        if exclude_system:
            visual_tables = {t for t in visual.tables if not _is_system(t)}
        else:
            visual_tables = visual.tables

        # --- column-level rows ---
        for col_ref in sorted(visual.columns):
            table_part, _, col_name = col_ref.partition("[")
            col_name = col_name.rstrip("]")
            if exclude_system and _is_system(table_part):
                continue
            row = (table_part, col_name, "", visual.title, visual.type, visual.page)
            if row not in seen:
                seen.add(row)
                _write_row(ws, ws.max_row + 1, list(row))

        # --- measure-level rows ---
        for measure_name in sorted(visual.measures):
            measure = graph.measures.get(measure_name)
            if measure is None:
                continue
            # Associate with every table the measure touches that's in this visual
            associated_tables = measure.referenced_tables & visual_tables
            if not associated_tables:
                associated_tables = measure.referenced_tables  # fallback: all referenced tables

            for table_name in sorted(associated_tables):
                if exclude_system and _is_system(table_name):
                    continue
                # Find columns of this table referenced by the measure
                table_cols = sorted(
                    col.partition("[")[2].rstrip("]")
                    for col in measure.referenced_columns
                    if col.startswith(f"{table_name}[")
                )
                if not table_cols:
                    table_cols = [""]  # at least one row per measure-table pairing

                for col_name in table_cols:
                    row = (table_name, col_name, measure_name, visual.title, visual.type, visual.page)
                    if row not in seen:
                        seen.add(row)
                        _write_row(ws, ws.max_row + 1, list(row))

    _auto_width(ws)


# ---------------------------------------------------------------------------
# Sheet 3 — DAX Dependency Lineage
# ---------------------------------------------------------------------------

def _build_sheet3(wb: Workbook, graph: DependencyGraph, exclude_system: bool) -> None:
    ws = wb.create_sheet("DAX Dependency Lineage")

    headers = ["Measure", "Direct Tables", "Direct Measures", "Final Dependent Tables"]
    ws.append(headers)
    _style_header(ws, len(headers))

    WRAP = {2, 3, 4}  # Direct Tables, Direct Measures, Final Tables

    for name, measure in sorted(graph.measures.items()):
        if exclude_system and _is_system(measure.table):
            continue

        # Direct tables — tables mentioned directly in the measure's own DAX
        dax_direct_tables = measure.referenced_tables - {measure.table}
        if exclude_system:
            dax_direct_tables = {t for t in dax_direct_tables if not _is_system(t)}

        # Direct measures — measures this measure's DAX calls
        direct_measures = measure.depends_on_measures

        # Final dependent tables — union of all tables reachable through the
        # measure's direct measures (transitive resolution)
        final_tables: set[str] = set(dax_direct_tables)
        visited: set[str] = set()
        queue = list(direct_measures)
        while queue:
            dep_name = queue.pop(0)
            if dep_name in visited:
                continue
            visited.add(dep_name)
            dep_measure = graph.measures.get(dep_name)
            if dep_measure:
                extra = dep_measure.referenced_tables - {dep_measure.table}
                if exclude_system:
                    extra = {t for t in extra if not _is_system(t)}
                final_tables |= extra
                for sub_dep in dep_measure.depends_on_measures:
                    if sub_dep not in visited:
                        queue.append(sub_dep)

        _write_row(
            ws,
            ws.max_row + 1,
            [
                name,
                _join(dax_direct_tables),
                _join(direct_measures),
                _join(final_tables),
            ],
            wrap_cols=WRAP,
        )

    _auto_width(ws)
