"""CLI entry point and public API for the PBIP dependency analyzer.

Usage as a CLI:

    python main.py "C:/Projects/Procurement.pbip"
    python main.py "C:/Projects/Procurement.pbip" --output ./output
    python main.py "C:/Projects/Procurement.pbip" --table "Fact Procurement"
    python main.py "C:/Projects/Procurement.pbip" --graph

Usage as a library:

    from main import analyze_pbip
    graph = analyze_pbip("C:/Projects/Procurement.pbip")
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from parser.pbip_loader import load_pbip_project
from parser.report_parser import parse_report
from parser.tmdl_parser import parse_semantic_model
from services.dependency_engine import DependencyEngine, DependencyGraph, find_unused_entities
from services.graph_export import build_dot
from utils.exceptions import PBIPAnalyzerError
from utils.logging_config import configure_logging, get_logger

logger = get_logger("main")


def is_system_table(name: str) -> bool:
    """Helper to detect auto-generated local date/time tables."""
    return name.startswith("LocalDateTable_") or name.startswith("DateTableTemplate_")


def analyze_pbip(
    pbip_path: str,
    output_dir: str | None = None,
    verbose: bool = False,
    table_filter: str | None = None,
    write_graph: bool = False,
    exclude_system: bool = False,
    no_color: bool = False,
    output_format: str = "text",
) -> DependencyGraph:
    """Analyze a PBIP project end-to-end and write the dependency report.

    This is the primary programmatic entry point (importable from other
    Python code, and reusable as-is inside a future FastAPI endpoint).

    Args:
        pbip_path: Path to the '.pbip' project file.
        output_dir: Directory to write 'dependency_report.json' and the
            extended 'dependency_report_full.json' into. Defaults to
            './output' relative to the current working directory.
        verbose: Enable DEBUG-level logging.
        table_filter: If given, the console report only prints this one
            table (case-insensitive match) instead of every table. Has no
            effect on what gets written to the JSON files -- those always
            contain the full project.
        write_graph: If True, also write 'dependency_graph.dot' (Graphviz)
            to the output directory.
        exclude_system: If True, filter out auto-generated LocalDateTable/DateTableTemplate tables.
        no_color: Disable ANSI color formatting in terminal outputs.
        output_format: Output format for the console ('text' or 'markdown').

    Returns:
        The fully linked DependencyGraph (tables/measures/visuals/pages).

    Raises:
        PBIPAnalyzerError (or a subclass): On any expected failure such as an
            invalid path, missing semantic model/report, or corrupt files.
    """
    configure_logging(verbose=verbose)
    logger.info("Analyzing PBIP project: %s", pbip_path)

    project = load_pbip_project(pbip_path)
    semantic_model = parse_semantic_model(project.semantic_model_dir)
    report = parse_report(project.report_dir)

    logger.info(
        "Parsed %d table(s) and %d page(s) from the project.",
        len(semantic_model.tables),
        len(report.pages),
    )

    graph = DependencyEngine(semantic_model, report).build()

    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else Path.cwd() / "output"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    write_json_reports(graph, resolved_output_dir, exclude_system=exclude_system)
    if write_graph:
        write_graph_file(graph, resolved_output_dir, exclude_system=exclude_system)

    print_console_report(
        graph,
        table_filter=table_filter,
        exclude_system=exclude_system,
        no_color=no_color,
        output_format=output_format,
    )

    return graph


def build_table_summary(graph: DependencyGraph, exclude_system: bool = False) -> dict[str, dict[str, list[str]]]:
    """Build the primary table-keyed summary matching the required output shape."""
    summary = {}
    for name, table in sorted(graph.tables.items()):
        if exclude_system and is_system_table(name):
            continue
        table_dict = table.to_dict()
        if exclude_system:
            table_dict["related_tables"] = [t for t in table_dict["related_tables"] if not is_system_table(t)]
        summary[name] = table_dict
    return summary


def build_full_report(graph: DependencyGraph, exclude_system: bool = False) -> dict[str, object]:
    """Build the extended, entity-complete report."""
    tables = {}
    for name, table in sorted(graph.tables.items()):
        if exclude_system and is_system_table(name):
            continue
        table_dict = table.to_dict()
        if exclude_system:
            table_dict["related_tables"] = [t for t in table_dict["related_tables"] if not is_system_table(t)]
        tables[name] = table_dict

    measures = {}
    for name, measure in sorted(graph.measures.items()):
        if exclude_system and is_system_table(measure.table):
            continue
        measure_dict = measure.to_dict()
        if exclude_system:
            measure_dict["referenced_tables"] = [t for t in measure_dict["referenced_tables"] if not is_system_table(t)]
            measure_dict["referenced_columns"] = [c for c in measure_dict["referenced_columns"] if not is_system_table(c.partition("[")[0])]
        measures[name] = measure_dict

    visuals = {}
    for vid, visual in sorted(graph.visuals.items()):
        visual_dict = visual.to_dict()
        if exclude_system:
            visual_dict["tables"] = [t for t in visual_dict["tables"] if not is_system_table(t)]
            visual_dict["columns"] = [c for c in visual_dict["columns"] if not is_system_table(c.partition("[")[0])]
        visuals[vid] = visual_dict

    pages = {}
    for name, page in sorted(graph.pages.items()):
        page_dict = page.to_dict()
        if exclude_system:
            page_dict["tables"] = [t for t in page_dict["tables"] if not is_system_table(t)]
        pages[name] = page_dict

    relationships = []
    for rel in graph.relationships:
        if exclude_system and (is_system_table(rel.from_table) or is_system_table(rel.to_table)):
            continue
        relationships.append(rel.to_dict())

    calculated_columns = {}
    for key, calc in sorted(graph.calculated_columns.items()):
        if exclude_system and (is_system_table(calc.table) or any(is_system_table(t) for t in calc.referenced_tables)):
            continue
        calc_dict = calc.to_dict()
        if exclude_system:
            calc_dict["referenced_tables"] = [t for t in calc_dict["referenced_tables"] if not is_system_table(t)]
            calc_dict["referenced_columns"] = [c for c in calc_dict["referenced_columns"] if not is_system_table(c.partition("[")[0])]
        calculated_columns[key] = calc_dict

    unused = find_unused_entities(graph)
    if exclude_system:
        unused["unused_tables"] = [t for t in unused["unused_tables"] if not is_system_table(t)]
        unused["unused_columns"] = {t: cols for t, cols in unused["unused_columns"].items() if not is_system_table(t)}

    return {
        "tables": tables,
        "measures": measures,
        "visuals": visuals,
        "pages": pages,
        "relationships": relationships,
        "calculated_columns": calculated_columns,
        "unused_entities": unused,
    }


def write_json_reports(graph: DependencyGraph, output_dir: Path, exclude_system: bool = False) -> None:
    """Write both the primary and extended JSON reports to `output_dir`."""
    primary_path = output_dir / "dependency_report.json"
    full_path = output_dir / "dependency_report_full.json"

    primary_path.write_text(json.dumps(build_table_summary(graph, exclude_system=exclude_system), indent=2), encoding="utf-8")
    full_path.write_text(json.dumps(build_full_report(graph, exclude_system=exclude_system), indent=2), encoding="utf-8")

    logger.info("Wrote %s", primary_path)
    logger.info("Wrote %s", full_path)


def write_graph_file(graph: DependencyGraph, output_dir: Path, exclude_system: bool = False) -> None:
    """Write a Graphviz DOT visualization of the table/page dependency graph."""
    dot_path = output_dir / "dependency_graph.dot"
    dot_path.write_text(build_dot(graph, exclude_system=exclude_system), encoding="utf-8")
    logger.info("Wrote %s (render with: dot -Tpng %s -o graph.png)", dot_path, dot_path)


def _color(text: str, color_code: str, no_color: bool) -> str:
    """Wrap string with ANSI escape colors if supported and enabled."""
    if no_color or not sys.stdout.isatty():
        return text
    return f"\033[{color_code}m{text}\033[0m"


def print_console_report(
    graph: DependencyGraph,
    table_filter: str | None = None,
    exclude_system: bool = False,
    no_color: bool = False,
    output_format: str = "text",
) -> None:
    """Print the human-readable dependency report to stdout.

    Supports ANSI coloring, system table exclusion, and Markdown formatting.
    """
    total_tables = len(graph.tables)
    system_tables = sum(1 for name in graph.tables if is_system_table(name))
    active_tables = total_tables - system_tables

    total_measures = len(graph.measures)
    total_pages = len(graph.pages)
    total_visuals = len(graph.visuals)
    total_relationships = len(graph.relationships)

    # 1. Print Summary Dashboard
    if output_format == "markdown":
        print("# PBIP Dependency Report Summary")
        print()
        print("| Metric | Count |")
        print("| :--- | :--- |")
        print(f"| **Active Tables** | {active_tables} |")
        print(f"| **System Tables** | {system_tables} ({'hidden' if exclude_system else 'shown'}) |")
        print(f"| **Total Measures** | {total_measures} |")
        print(f"| **Report Pages** | {total_pages} |")
        print(f"| **Total Visuals** | {total_visuals} |")
        print(f"| **Relationships** | {total_relationships} |")
        print()
        print("---")
        print()
    else:
        # Text format
        summary_title = "PBIP PROJECT SUMMARY"
        border = "=" * 50
        print(_color(border, "1;94", no_color))  # Blue border
        print(_color(f"{summary_title:^50}", "1;94", no_color))
        print(_color(border, "1;94", no_color))
        print(f"  Active Tables:   {active_tables}")
        print(f"  System Tables:   {system_tables} ({'hidden' if exclude_system else 'shown'})")
        print(f"  Total Measures:  {total_measures}")
        print(f"  Report Pages:    {total_pages}")
        print(f"  Total Visuals:   {total_visuals}")
        print(f"  Relationships:   {total_relationships}")
        print(_color(border, "1;94", no_color))
        print()

    # 2. Print single table if filter is given
    if table_filter:
        _print_single_table(graph, table_filter, exclude_system, no_color, output_format)
        return

    # 3. Print all tables
    if output_format == "markdown":
        print("## Table Dependencies")
        print()
    for name, table in sorted(graph.tables.items()):
        if exclude_system and is_system_table(name):
            continue
        _print_table_section(name, table, exclude_system, no_color, output_format)

    # 4. Print unused entities
    _print_unused_entities_summary(graph, exclude_system, no_color, output_format)


def _print_single_table(
    graph: DependencyGraph,
    table_filter: str,
    exclude_system: bool = False,
    no_color: bool = False,
    output_format: str = "text",
) -> None:
    match = next((name for name in graph.tables if name.lower() == table_filter.lower()), None)

    if match is None:
        print(f"Table '{table_filter}' not found in this project.")
        suggestions = difflib.get_close_matches(table_filter, graph.tables.keys(), n=5)
        if suggestions:
            print("Did you mean:")
            for suggestion in suggestions:
                print(f"  - {suggestion}")
        return

    _print_table_section(match, graph.tables[match], exclude_system, no_color, output_format)


def _print_table_section(
    name: str,
    table,
    exclude_system: bool = False,
    no_color: bool = False,
    output_format: str = "text",
) -> None:
    # Filter related tables to exclude system tables if flag is set
    related_tables = sorted(table.related_tables)
    if exclude_system:
        related_tables = [t for t in related_tables if not is_system_table(t)]

    if output_format == "markdown":
        print(f"### TABLE: {name}")
        print()
        _print_section_md("Columns", sorted(table.columns))
        _print_section_md("Measures", sorted(table.measures))
        _print_section_md("Visuals", sorted(table.visuals))
        _print_section_md("Pages", sorted(table.pages))
        _print_section_md("Related Tables", related_tables)
        print()
    else:
        border = "=" * 50
        print(_color(border, "90", no_color))  # Gray border
        print(_color(f"TABLE: {name}", "1;92", no_color))  # Bold Green table name
        print()
        _print_section_text("Columns", sorted(table.columns), no_color)
        _print_section_text("Measures", sorted(table.measures), no_color)
        _print_section_text("Visuals", sorted(table.visuals), no_color)
        _print_section_text("Pages", sorted(table.pages), no_color)
        _print_section_text("Related Tables", related_tables, no_color)
        print(_color(border, "90", no_color))
        print()


def _print_unused_entities_summary(
    graph: DependencyGraph,
    exclude_system: bool = False,
    no_color: bool = False,
    output_format: str = "text",
) -> None:
    unused = find_unused_entities(graph)

    unused_tables = unused["unused_tables"]
    unused_measures = unused["unused_measures"]
    unused_columns = unused["unused_columns"]

    if exclude_system:
        unused_tables = [t for t in unused_tables if not is_system_table(t)]
        unused_columns = {t: cols for t, cols in unused_columns.items() if not is_system_table(t)}

    if not unused_tables and not unused_measures and not unused_columns:
        return

    if output_format == "markdown":
        print("## UNUSED ENTITIES (not referenced by any visual)")
        print()
        _print_section_md("Tables", unused_tables)
        _print_section_md("Measures", unused_measures)

        if unused_columns:
            print("**Columns**")
            print()
            for table_name, columns in sorted(unused_columns.items()):
                for column in columns:
                    print(f"* {table_name}[{column}]")
            print()
    else:
        border = "=" * 50
        print(_color(border, "1;93", no_color))  # Yellow border
        print(_color("UNUSED ENTITIES (not referenced by any visual)", "1;93", no_color))
        print()
        _print_section_text("Tables", unused_tables, no_color)
        _print_section_text("Measures", unused_measures, no_color)

        if unused_columns:
            print(_color("Columns:", "36", no_color))
            for table_name, columns in sorted(unused_columns.items()):
                for column in columns:
                    print(f"* {table_name}[{column}]")
            print()

        print(_color(border, "1;93", no_color))
        print()


def _print_section_text(title: str, items: list[str], no_color: bool) -> None:
    print(_color(f"{title}:", "36", no_color))  # Cyan header
    if not items:
        print("  (none)")
    for item in items:
        print(f"* {item}")
    print()


def _print_section_md(title: str, items: list[str]) -> None:
    print(f"**{title}**")
    print()
    if not items:
        print("* *None*")
    else:
        for item in items:
            print(f"* {item}")
    print()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pbip_analyzer",
        description="Analyze a Power BI PBIP project and report table/measure/visual/page dependencies.",
    )
    parser.add_argument("pbip_path", help="Path to the .pbip project file.")
    parser.add_argument(
        "--output",
        dest="output_dir",
        default=None,
        help="Directory to write dependency_report.json into (default: ./output).",
    )
    parser.add_argument(
        "--table",
        dest="table_filter",
        default=None,
        help="Only print this one table's dependency report to the console (case-insensitive).",
    )
    parser.add_argument(
        "--graph",
        dest="write_graph",
        action="store_true",
        help="Also write dependency_graph.dot (Graphviz) to the output directory.",
    )
    parser.add_argument(
        "--exclude-system",
        dest="exclude_system",
        action="store_true",
        help="Exclude auto-generated local date/time tables from the output.",
    )
    parser.add_argument(
        "--no-color",
        dest="no_color",
        action="store_true",
        help="Disable ANSI escape color formatting in console output.",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["text", "markdown"],
        default="text",
        help="Specify the console output format (text or markdown, default: text).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    args = _build_arg_parser().parse_args(argv)

    try:
        analyze_pbip(
            args.pbip_path,
            output_dir=args.output_dir,
            verbose=args.verbose,
            table_filter=args.table_filter,
            write_graph=args.write_graph,
            exclude_system=args.exclude_system,
            no_color=args.no_color,
            output_format=args.output_format,
        )
    except PBIPAnalyzerError as exc:
        logger.error(str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - final safety net for unexpected errors
        logger.exception("Unexpected error while analyzing the PBIP project.")
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
