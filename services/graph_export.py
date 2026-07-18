"""Exports a DependencyGraph as a Graphviz DOT file.

Purely additive/optional: the analyzer works fully without this module. When
enabled (via `main.py --graph`), it gives a quick visual sanity-check of
table -> page usage and table -> table relationships, which is often faster
to scan than the JSON/console report for a model with many tables.

Render the output with Graphviz, e.g.::

    dot -Tpng dependency_graph.dot -o dependency_graph.png
"""

from __future__ import annotations

from services.dependency_engine import DependencyGraph


def _escape(text: str) -> str:
    """Escape a string for safe use inside a DOT quoted identifier/label."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_dot(graph: DependencyGraph) -> str:
    """Build a Graphviz DOT document for the given dependency graph.

    Nodes:
        - Tables: box, light blue.
        - Pages: folder shape, light yellow.

    Edges:
        - Table -> Page (solid): the table is used by at least one visual on
          that page. Labeled with the visual title(s) that create the link.
        - Table -> Table (dashed): a model relationship or a calculated
          column's cross-table reference.

    Args:
        graph: A fully built DependencyGraph.

    Returns:
        DOT source text.
    """
    lines: list[str] = ["digraph PBIPDependencies {", '  rankdir="LR";', "  node [fontname=\"Helvetica\"];"]

    # Table nodes
    for table_name in sorted(graph.tables):
        lines.append(f'  "table::{_escape(table_name)}" [label="{_escape(table_name)}", shape=box, style=filled, fillcolor="#cfe2f3"];')

    # Page nodes
    for page_name in sorted(graph.pages):
        lines.append(
            f'  "page::{_escape(page_name)}" [label="{_escape(page_name)}", shape=folder, style=filled, fillcolor="#fff2cc"];'
        )

    # Table -> Page edges, labeled with the connecting visual title(s)
    for table_name, table in sorted(graph.tables.items()):
        for page_name in sorted(table.pages):
            page = graph.pages.get(page_name)
            shared_visuals = sorted(table.visuals & page.visuals) if page else []
            label = _escape(", ".join(shared_visuals)) if shared_visuals else ""
            lines.append(
                f'  "table::{_escape(table_name)}" -> "page::{_escape(page_name)}" [label="{label}"];'
            )

    # Table -> Table edges (relationships)
    seen_pairs: set[tuple[str, str]] = set()
    for rel in graph.relationships:
        if not rel.from_table or not rel.to_table:
            continue
        pair = tuple(sorted((rel.from_table, rel.to_table)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        lines.append(
            f'  "table::{_escape(rel.from_table)}" -> "table::{_escape(rel.to_table)}" '
            f'[style=dashed, color="#999999", label="{_escape(rel.from_column)} -> {_escape(rel.to_column)}"];'
        )

    # Table -> Table edges (calculated-column dependencies not already
    # covered by a relationship above)
    for calc_column in graph.calculated_columns.values():
        for other_table in calc_column.referenced_tables:
            pair = tuple(sorted((calc_column.table, other_table)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            lines.append(
                f'  "table::{_escape(calc_column.table)}" -> "table::{_escape(other_table)}" '
                f'[style=dotted, color="#cc6600", label="calc column: {_escape(calc_column.column)}"];'
            )

    lines.append("}")
    return "\n".join(lines)
