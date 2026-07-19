"""Export a DependencyGraph to a formatted Excel workbook (.xlsx).

Generates exactly three sheets:

    Sheet 1 — Table Dependency Summary
        One row per table. Aggregated columns, measures, and visuals with page names.
        Includes Total Measures and Total Visuals count columns.

    Sheet 2 — Detailed Dependency Mapping
        One row per (table, column, measure, visual) combination.
        Ideal for filtering/searching specific dependencies.

    Sheet 3 — DAX Dependency Lineage
        One row per measure showing which tables and other measures it
        depends on, and the final set of tables reached transitively.

The workbook is always saved to the user's Downloads folder automatically.

Requires: openpyxl  (pip install openpyxl)
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import Union

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from services.dependency_engine import DependencyGraph
from utils.logging_config import get_logger

logger = get_logger("excel_export")

# ---------------------------------------------------------------------------
# Colour palette  (deep navy header, white text, clean body)
# ---------------------------------------------------------------------------
_HEADER_FILL  = PatternFill("solid", fgColor="1F3864")   # deep navy
_HEADER_FONT  = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_BODY_FONT    = Font(name="Calibri", size=10)
_WRAP_ALIGN   = Alignment(wrap_text=True, vertical="top")
_TOP_ALIGN    = Alignment(vertical="top")
_CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_system(name: str) -> bool:
    return name.startswith("LocalDateTable_") or name.startswith("DateTableTemplate_")


def _join(items: set | list, sep: str = ", ") -> str:
    """Convert a set/list to a sorted, deduplicated comma-separated string.
    Returns empty string (not 'None' or '[]') when there are no items."""
    cleaned = sorted({str(i) for i in items if i})
    return sep.join(cleaned) if cleaned else ""


def _val(v: str) -> str | None:
    """Return None for empty strings so cells stay blank in Excel."""
    return v if v else None


def _style_header(ws, n_cols: int) -> None:
    """Apply navy header style, freeze the top row, and enable auto-filter."""
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=1, column=col)
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = _CENTER_ALIGN
    ws.freeze_panes   = "A2"
    ws.auto_filter.ref = ws.dimensions


def _auto_width(ws, min_w: int = 10, max_w: int = 65) -> None:
    """Auto-fit column widths based on the longest line in each column."""
    for col_cells in ws.columns:
        best = min_w
        for cell in col_cells:
            if cell.value is not None:
                longest = max(str(cell.value).split("\n"), key=len, default="")
                best = max(best, min(len(longest) + 4, max_w))
        ws.column_dimensions[get_column_letter(col_cells[0].column)].width = best


def _write_row(ws, row_idx: int, values: list, wrap_cols: set[int] | None = None) -> None:
    for col_idx, val in enumerate(values, 1):
        cell       = ws.cell(row=row_idx, column=col_idx, value=_val(str(val)) if val is not None else None)
        cell.font  = _BODY_FONT
        if wrap_cols and col_idx in wrap_cols:
            cell.alignment = _WRAP_ALIGN
        else:
            cell.alignment = _TOP_ALIGN


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_excel_report(
    graph: DependencyGraph,
    output_path: Union[str, Path, None] = None,
    exclude_system: bool = False,
) -> bytes:
    """Build and save an Excel workbook from a fully-linked DependencyGraph.

    The workbook is always saved to the user's Downloads folder as
    'dependency_report.xlsx'.  An additional copy is also written to
    ``output_path`` when provided.

    Args:
        graph:          The completed DependencyGraph returned by DependencyEngine.build().
        output_path:    Optional extra save location (e.g. ./output/dependency_report.xlsx).
                        The Downloads copy is always written regardless of this argument.
        exclude_system: When True, skip LocalDateTable_* / DateTableTemplate_* tables.

    Returns:
        The raw bytes of the .xlsx workbook.
    """
    wb = Workbook()
    wb.remove(wb.active)   # remove default empty sheet

    _build_sheet1(wb, graph, exclude_system)
    _build_sheet2(wb, graph, exclude_system)
    _build_sheet3(wb, graph, exclude_system)

    buf = io.BytesIO()
    wb.save(buf)
    raw = buf.getvalue()

    # --- Always save a new timestamped file to the user's Downloads folder ---
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    downloads_path = downloads_dir / f"dependency_report_{timestamp}.xlsx"
    downloads_path.write_bytes(raw)
    logger.info("Saved Excel report to Downloads: %s", downloads_path)

    # --- Optional extra copy ---
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        logger.info("Wrote Excel report: %s", path)

    return raw


# ---------------------------------------------------------------------------
# Sheet 1 — Table Dependency Summary
# ---------------------------------------------------------------------------

def _build_sheet1(wb: Workbook, graph: DependencyGraph, exclude_system: bool) -> None:
    ws = wb.create_sheet("Table Dependency Summary")

    headers = ["Table", "Columns", "Measures", "Visuals (Page)", "Total Measures", "Total Visuals"]
    ws.append(headers)
    _style_header(ws, len(headers))

    # Wrap-text columns: Columns(2), Measures(3), Visuals (Page)(4)
    WRAP = {2, 3, 4}

    for name, table in sorted(graph.tables.items()):
        if exclude_system and _is_system(name):
            continue

        # Build "Visual (PageName)" strings — normalise "(Page: X)" → "(X)"
        visual_page_parts: list[str] = []
        for visual_title in sorted(table.visuals):
            normalised = visual_title.replace("(Page: ", "(")
            visual_page_parts.append(normalised)

        cols_str     = _join(table.columns)
        measures_str = _join(table.measures)
        visuals_str  = "\n".join(visual_page_parts) if visual_page_parts else ""

        total_measures = len([m for m in table.measures if m])
        total_visuals  = len(visual_page_parts)

        _write_row(
            ws,
            ws.max_row + 1,
            [
                name,
                cols_str or None,
                measures_str or None,
                visuals_str or None,
                total_measures if total_measures else None,
                total_visuals  if total_visuals  else None,
            ],
            wrap_cols=WRAP,
        )

    _auto_width(ws)


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
            row = (table_part, col_name, None, visual.title, visual.type, visual.page)
            if row not in seen:
                seen.add(row)
                _write_row(ws, ws.max_row + 1, list(row))

        # --- measure-level rows ---
        for measure_name in sorted(visual.measures):
            measure = graph.measures.get(measure_name)
            if measure is None:
                continue
            associated_tables = measure.referenced_tables & visual_tables
            if not associated_tables:
                associated_tables = measure.referenced_tables  # fallback

            for table_name in sorted(associated_tables):
                if exclude_system and _is_system(table_name):
                    continue
                table_cols = sorted(
                    col.partition("[")[2].rstrip("]")
                    for col in measure.referenced_columns
                    if col.startswith(f"{table_name}[")
                )
                if not table_cols:
                    table_cols = [None]  # at least one row per measure-table pairing

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

    WRAP = {2, 3, 4}

    for name, measure in sorted(graph.measures.items()):
        if exclude_system and _is_system(measure.table):
            continue

        # Direct tables — tables referenced directly in this measure's DAX
        dax_direct_tables = measure.referenced_tables - {measure.table}
        if exclude_system:
            dax_direct_tables = {t for t in dax_direct_tables if not _is_system(t)}

        # Direct measures — measures this measure calls
        direct_measures = measure.depends_on_measures

        # Final dependent tables — transitive closure through all called measures
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

        direct_tables_str  = _join(dax_direct_tables)
        direct_measures_str = _join(direct_measures)
        final_tables_str   = _join(final_tables)

        _write_row(
            ws,
            ws.max_row + 1,
            [
                name,
                direct_tables_str  or None,
                direct_measures_str or None,
                final_tables_str   or None,
            ],
            wrap_cols=WRAP,
        )

    _auto_width(ws)
