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


def analyze_pbip(
    pbip_path: str,
    output_dir: str | None = None,
    verbose: bool = False,
    table_filter: str | None = None,
    write_graph: bool = False,
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

    write_json_reports(graph, resolved_output_dir)
    if write_graph:
        write_graph_file(graph, resolved_output_dir)

    print_console_report(graph, table_filter=table_filter)

    return graph


def build_table_summary(graph: DependencyGraph) -> dict[str, dict[str, list[str]]]:
    """Build the primary table-keyed summary matching the required output shape."""
    return {name: table.to_dict() for name, table in sorted(graph.tables.items())}


def build_full_report(graph: DependencyGraph) -> dict[str, object]:
    """Build the extended, entity-complete report.

    This is additive detail beyond the minimum required
    'dependency_report.json' shape, kept in a separate file so the primary
    report's schema stays exactly as specified while still giving downstream
    consumers (e.g. a future API) full access to every entity's detail,
    including relationships, calculated-column formulas, and unused-entity
    hygiene checks.
    """
    return {
        "tables": {name: table.to_dict() for name, table in sorted(graph.tables.items())},
        "measures": {name: measure.to_dict() for name, measure in sorted(graph.measures.items())},
        "visuals": {vid: visual.to_dict() for vid, visual in sorted(graph.visuals.items())},
        "pages": {name: page.to_dict() for name, page in sorted(graph.pages.items())},
        "relationships": [rel.to_dict() for rel in graph.relationships],
        "calculated_columns": {
            key: calc.to_dict() for key, calc in sorted(graph.calculated_columns.items()) if calc.referenced_tables
        },
        "unused_entities": find_unused_entities(graph),
    }


def write_json_reports(graph: DependencyGraph, output_dir: Path) -> None:
    """Write both the primary and extended JSON reports to `output_dir`."""
    primary_path = output_dir / "dependency_report.json"
    full_path = output_dir / "dependency_report_full.json"

    primary_path.write_text(json.dumps(build_table_summary(graph), indent=2), encoding="utf-8")
    full_path.write_text(json.dumps(build_full_report(graph), indent=2), encoding="utf-8")

    logger.info("Wrote %s", primary_path)
    logger.info("Wrote %s", full_path)


def write_graph_file(graph: DependencyGraph, output_dir: Path) -> None:
    """Write a Graphviz DOT visualization of the table/page dependency graph."""
    dot_path = output_dir / "dependency_graph.dot"
    dot_path.write_text(build_dot(graph), encoding="utf-8")
    logger.info("Wrote %s (render with: dot -Tpng %s -o graph.png)", dot_path, dot_path)


def print_console_report(graph: DependencyGraph, table_filter: str | None = None) -> None:
    """Print the human-readable, per-table dependency report to stdout.

    Args:
        graph: The built dependency graph.
        table_filter: If given, only print the single matching table
            (case-insensitive). If no exact match is found, prints the
            closest name suggestions instead of silently printing nothing.
    """
    if table_filter:
        _print_single_table(graph, table_filter)
        return

    for name, table in sorted(graph.tables.items()):
        _print_table_section(name, table)

    _print_unused_entities_summary(graph)


def _print_single_table(graph: DependencyGraph, table_filter: str) -> None:
    match = next((name for name in graph.tables if name.lower() == table_filter.lower()), None)

    if match is None:
        print(f"Table '{table_filter}' not found in this project.")
        suggestions = difflib.get_close_matches(table_filter, graph.tables.keys(), n=5)
        if suggestions:
            print("Did you mean:")
            for suggestion in suggestions:
                print(f"  - {suggestion}")
        return

    _print_table_section(match, graph.tables[match])


def _print_table_section(name: str, table) -> None:  # noqa: ANN001 - Table type, avoids circular import hint noise
    separator = "=" * 50
    print(separator)
    print(f"TABLE: {name}")
    print()
    _print_section("Columns", sorted(table.columns))
    _print_section("Measures", sorted(table.measures))
    _print_section("Visuals", sorted(table.visuals))
    _print_section("Pages", sorted(table.pages))
    _print_section("Related Tables", sorted(table.related_tables))
    print(separator)
    print()


def _print_unused_entities_summary(graph: DependencyGraph) -> None:
    unused = find_unused_entities(graph)
    if not any(unused.values()):
        return

    print("=" * 50)
    print("UNUSED ENTITIES (not referenced by any visual)")
    print()
    _print_section("Tables", unused["unused_tables"])
    _print_section("Measures", unused["unused_measures"])

    if unused["unused_columns"]:
        print("Columns:")
        for table_name, columns in sorted(unused["unused_columns"].items()):
            for column in columns:
                print(f"* {table_name}[{column}]")
        print()

    print("=" * 50)


def _print_section(title: str, items: list[str]) -> None:
    print(f"{title}:")
    if not items:
        print("  (none)")
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
