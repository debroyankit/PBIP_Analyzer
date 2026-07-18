"""Lightweight, regex-based DAX reference extractor.

Full DAX parsing requires a real grammar (functions, nested parens, string
literals, etc.). For dependency analysis we only need to know which
tables/columns a measure *touches*, so a tolerant regex-based scanner over
the two forms of field reference used in essentially all real-world DAX is
sufficient and far more maintainable than a full parser:

    Table[Column]           SUM(Sales[Amount])
    'Table Name'[Column]    SUM('Fact Sales'[Amount])
    [Measure]               [Total Sales] * 1.1   (implicit / same-context
                                                    reference to a measure)

This module intentionally does not try to resolve bare "[Name]" references
to a table -- that requires model-wide knowledge and is done later by
`services.dependency_engine`, which knows every measure name in the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 'Quoted Table Name'[Column]  OR  UnquotedTable[Column]
# The quoted-name group is tried first since it can contain spaces/punctuation.
_QUALIFIED_REF = re.compile(
    r"(?:'(?P<quoted_table>(?:[^']|'')+)'|(?P<table>[A-Za-z_][A-Za-z0-9_]*))"
    r"\[(?P<field>[^\[\]]+)\]"
)

# A bracketed reference with nothing but whitespace/operators before it (i.e.
# NOT immediately preceded by an identifier char, a quote, or another `]`),
# which in DAX means "measure (or column in row context) in the current
# context" rather than an explicit table-qualified reference.
_BARE_REF = re.compile(r"(?<![\w'\]])\[(?P<field>[^\[\]]+)\]")


@dataclass
class DaxReferences:
    """Result of scanning a DAX expression for field references."""

    tables: set[str] = field(default_factory=set)
    qualified_columns: set[str] = field(default_factory=set)  # "Table[Column]"
    bare_names: set[str] = field(default_factory=set)  # unqualified "[Name]"


def extract_references(dax_expression: str) -> DaxReferences:
    """Extract table/column/measure references from a DAX expression.

    Args:
        dax_expression: Raw DAX text (single or multi-line).

    Returns:
        A DaxReferences with tables touched, "Table[Column]" strings found,
        and any unqualified "[Name]" references (candidate measure names,
        resolved later against the full model).
    """
    result = DaxReferences()
    if not dax_expression:
        return result

    qualified_spans: list[tuple[int, int]] = []
    for match in _QUALIFIED_REF.finditer(dax_expression):
        table_name = match.group("quoted_table") or match.group("table")
        table_name = table_name.replace("''", "'") if table_name else table_name
        field_name = match.group("field").strip()
        result.tables.add(table_name)
        result.qualified_columns.add(f"{table_name}[{field_name}]")
        qualified_spans.append(match.span())

    for match in _BARE_REF.finditer(dax_expression):
        # Skip any bracket that was already captured as part of a qualified
        # Table[Column] reference above.
        if any(start <= match.start() < end for start, end in qualified_spans):
            continue
        result.bare_names.add(match.group("field").strip())

    return result
