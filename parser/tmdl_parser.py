"""Parses a PBIP Semantic Model folder into raw tables/measures/relationships.

Supports the two formats Power BI Desktop can save a semantic model in:

1. Modern, folder-based **TMDL** (the default since late 2024):

    MyModel.SemanticModel/
        definition/
            model.tmdl
            relationships.tmdl
            tables/
                Sales.tmdl
                Product.tmdl

2. Legacy single-file **TMSL/JSON** (``model.bim``):

    MyModel.SemanticModel/
        model.bim

This module only extracts what's needed for dependency analysis: table
names, column names, measure names + DAX, and relationships. It does not
attempt to be a complete TMDL/TMSL grammar implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.exceptions import CorruptFileError, SemanticModelNotFoundError
from utils.file_utils import list_files, read_json_safe, read_text_safe
from utils.logging_config import get_logger

logger = get_logger("tmdl_parser")

_TMDL_TOP_LEVEL_KEYWORDS = {"column", "measure", "partition", "hierarchy", "table"}

# Known TMDL measure/column property keys. These always terminate a measure's
# DAX continuation, regardless of indentation, because in TMDL a measure's
# *own* properties (formatString, lineageTag, etc.) are conventionally
# indented one level deeper than the "measure 'Name' = ..." line itself --
# exactly like a genuine multi-line DAX continuation would be. Indentation
# alone can't disambiguate the two, so we recognize these properties by name.
_MEASURE_PROPERTY_KEYWORDS = {
    "formatString",
    "displayFolder",
    "isHidden",
    "lineageTag",
    "sourceLineageTag",
    "description",
    "annotation",
    "changedProperty",
    "dataType",
    "summarizeBy",
    "isDataTypeInferred",
    "formatStringDefinition",
    "dataCategory",
    "extendedProperty",
}


@dataclass
class RawMeasure:
    name: str
    table: str
    dax: str


@dataclass
class RawTable:
    name: str
    columns: set[str] = field(default_factory=set)
    measures: list[RawMeasure] = field(default_factory=list)


@dataclass
class RawRelationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str


@dataclass
class RawSemanticModel:
    tables: dict[str, RawTable] = field(default_factory=dict)
    relationships: list[RawRelationship] = field(default_factory=list)


def parse_semantic_model(semantic_model_dir: Path) -> RawSemanticModel:
    """Parse a semantic model folder, auto-detecting TMDL vs legacy .bim.

    Args:
        semantic_model_dir: Resolved '*.SemanticModel' directory.

    Returns:
        A RawSemanticModel with all tables, measures and relationships found.

    Raises:
        SemanticModelNotFoundError: If neither a TMDL definition nor a
            model.bim file can be found inside the folder.
    """
    definition_dir = semantic_model_dir / "definition"
    bim_path = semantic_model_dir / "model.bim"

    if definition_dir.is_dir():
        logger.info("Detected TMDL (folder-based) semantic model.")
        return _parse_tmdl(definition_dir)

    if bim_path.is_file():
        logger.info("Detected legacy TMSL/JSON semantic model (model.bim).")
        return _parse_bim(bim_path)

    raise SemanticModelNotFoundError(
        f"'{semantic_model_dir}' contains neither a 'definition/' TMDL folder "
        "nor a 'model.bim' file."
    )


# --------------------------------------------------------------------------
# TMDL (modern) parsing
# --------------------------------------------------------------------------


def _parse_tmdl(definition_dir: Path) -> RawSemanticModel:
    model = RawSemanticModel()

    tables_dir = definition_dir / "tables"
    table_files = list_files(tables_dir, "*.tmdl")
    if not table_files:
        # Some projects keep everything in a single model.tmdl file instead
        # of one file per table; fall back to scanning the whole definition
        # folder for any .tmdl file that contains a "table " declaration.
        table_files = [
            p for p in list_files(definition_dir, "*.tmdl") if p.name != "relationships.tmdl"
        ]

    for table_file in table_files:
        text = read_text_safe(table_file)
        for table in _parse_tmdl_tables(text):
            model.tables[table.name] = table

    relationships_file = definition_dir / "relationships.tmdl"
    if relationships_file.is_file():
        model.relationships = _parse_tmdl_relationships(read_text_safe(relationships_file))
    else:
        # Some model versions inline relationships inside model.tmdl.
        model_tmdl = definition_dir / "model.tmdl"
        if model_tmdl.is_file():
            model.relationships = _parse_tmdl_relationships(read_text_safe(model_tmdl))

    return model


def _indent_of(line: str) -> int:
    """Return the number of leading whitespace characters (tabs count as 1)."""
    return len(line) - len(line.lstrip())


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1].replace("''", "'")
    return name


def _parse_tmdl_tables(text: str) -> list[RawTable]:
    """Parse every ``table <Name>`` block found in a TMDL file's text."""
    lines = text.splitlines()
    tables: list[RawTable] = []
    current_table: RawTable | None = None

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("table ") and _indent_of(line) == 0:
            name = _unquote(stripped[len("table ") :])
            current_table = RawTable(name=name)
            tables.append(current_table)
            i += 1
            continue

        if current_table is not None:
            if stripped.startswith("column "):
                col_name = _unquote(stripped[len("column ") :].split("=")[0])
                current_table.columns.add(col_name)
                i += 1
                continue

            if stripped.startswith("measure "):
                measure_name, dax, next_i = _parse_measure_block(lines, i)
                current_table.measures.append(
                    RawMeasure(name=measure_name, table=current_table.name, dax=dax)
                )
                i = next_i
                continue

        i += 1

    return tables


def _parse_measure_block(lines: list[str], start_index: int) -> tuple[str, str, int]:
    """Parse a ``measure 'Name' = <expr>`` block, including continuation lines.

    Returns:
        (measure_name, dax_expression, index_of_next_unconsumed_line)
    """
    header = lines[start_index]
    header_indent = _indent_of(header)
    header_body = header.strip()[len("measure ") :]

    if "=" in header_body:
        name_part, _, expr_part = header_body.partition("=")
    else:
        name_part, expr_part = header_body, ""

    name = _unquote(name_part)
    dax_lines = [expr_part.strip()] if expr_part.strip() else []

    j = start_index + 1
    while j < len(lines):
        line = lines[j]
        if not line.strip():
            j += 1
            continue

        indent = _indent_of(line)
        stripped = line.strip()
        first_token = stripped.split(" ", 1)[0].split(":", 1)[0]

        # A new sibling/child structural block (table/column/measure/
        # partition/hierarchy) at or above the measure's own indent ends
        # the DAX continuation.
        if indent <= header_indent and first_token in _TMDL_TOP_LEVEL_KEYWORDS:
            break

        # A known measure property (formatString, lineageTag, ...) ends the
        # DAX continuation regardless of indentation -- see the comment on
        # _MEASURE_PROPERTY_KEYWORDS for why indentation alone is ambiguous.
        if first_token in _MEASURE_PROPERTY_KEYWORDS:
            break

        dax_lines.append(stripped)
        j += 1

    dax_expression = "\n".join(line for line in dax_lines if line)
    return name, dax_expression, j


def _parse_tmdl_relationships(text: str) -> list[RawRelationship]:
    """Parse ``relationship`` blocks for fromColumn/toColumn pairs."""
    relationships: list[RawRelationship] = []
    lines = text.splitlines()

    current_from: str | None = None
    current_to: str | None = None
    in_relationship = False

    def _flush() -> None:
        nonlocal current_from, current_to
        if current_from and current_to:
            from_table, _, from_col = current_from.partition(".")
            to_table, _, to_col = current_to.partition(".")
            relationships.append(
                RawRelationship(
                    from_table=_unquote(from_table),
                    from_column=_unquote(from_col),
                    to_table=_unquote(to_table),
                    to_column=_unquote(to_col),
                )
            )
        current_from, current_to = None, None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("relationship "):
            if in_relationship:
                _flush()
            in_relationship = True
            continue
        if in_relationship and stripped.startswith("fromColumn:"):
            current_from = stripped[len("fromColumn:") :].strip()
        elif in_relationship and stripped.startswith("toColumn:"):
            current_to = stripped[len("toColumn:") :].strip()

    if in_relationship:
        _flush()

    return relationships


# --------------------------------------------------------------------------
# Legacy TMSL/JSON (.bim) parsing
# --------------------------------------------------------------------------


def _parse_bim(bim_path: Path) -> RawSemanticModel:
    content = read_json_safe(bim_path)
    if not isinstance(content, dict):
        raise CorruptFileError(f"'{bim_path}' does not contain a JSON object.")

    model = RawSemanticModel()
    model_section = content.get("model", content)
    tables = model_section.get("tables", [])

    for table_json in tables:
        name = table_json.get("name", "")
        if not name:
            continue
        raw_table = RawTable(name=name)

        for col in table_json.get("columns", []):
            col_name = col.get("name")
            if col_name:
                raw_table.columns.add(col_name)

        for meas in table_json.get("measures", []):
            meas_name = meas.get("name")
            expr = meas.get("expression", "")
            if isinstance(expr, list):
                expr = "\n".join(expr)
            if meas_name:
                raw_table.measures.append(RawMeasure(name=meas_name, table=name, dax=expr))

        model.tables[name] = raw_table

    for rel in model_section.get("relationships", []):
        model.relationships.append(
            RawRelationship(
                from_table=rel.get("fromTable", ""),
                from_column=rel.get("fromColumn", ""),
                to_table=rel.get("toTable", ""),
                to_column=rel.get("toColumn", ""),
            )
        )

    return model
