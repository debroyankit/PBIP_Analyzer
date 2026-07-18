"""Data model representing a semantic model table and its dependents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Table:
    """A table defined in the semantic model.

    Attributes:
        name: Table name as defined in the semantic model.
        columns: Column names that belong to this table.
        measures: Names of measures that reference this table (either because
            it is their home table, or because their DAX expression touches
            this table).
        visuals: Titles/ids of visuals that render data from this table
            (directly, or transitively through a measure that references it).
        pages: Names of report pages that contain at least one visual using
            this table.
    """

    name: str
    columns: set[str] = field(default_factory=set)
    measures: set[str] = field(default_factory=set)
    visuals: set[str] = field(default_factory=set)
    pages: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, list[str]]:
        """Serialize to a JSON-friendly dict with deterministic ordering."""
        return {
            "columns": sorted(self.columns),
            "measures": sorted(self.measures),
            "visuals": sorted(self.visuals),
            "pages": sorted(self.pages),
        }
