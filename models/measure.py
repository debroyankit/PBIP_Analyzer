"""Data model representing a DAX measure and its dependents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Measure:
    """A DAX measure defined in the semantic model.

    Attributes:
        name: Measure name.
        table: The "home" table the measure is defined on.
        dax: Raw DAX expression text.
        referenced_tables: Tables referenced by the DAX expression (includes
            the home table).
        referenced_columns: Fully qualified "Table[Column]" references found
            in the DAX expression.
        visuals: Unique visual IDs of visuals that use this measure.
        pages: Names of pages that contain a visual using this measure.
        depends_on_measures: Other measures this measure's DAX references
            via a bare "[Measure Name]" expression.
        used_by_measures: Other measures whose DAX references this measure
            (the reverse of depends_on_measures).
    """

    name: str
    table: str
    dax: str = ""
    referenced_tables: set[str] = field(default_factory=set)
    referenced_columns: set[str] = field(default_factory=set)
    visuals: set[str] = field(default_factory=set)
    pages: set[str] = field(default_factory=set)
    depends_on_measures: set[str] = field(default_factory=set)
    used_by_measures: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, object]:
        """Serialize to a JSON-friendly dict with deterministic ordering."""
        return {
            "table": self.table,
            "dax": self.dax,
            "referenced_tables": sorted(self.referenced_tables),
            "referenced_columns": sorted(self.referenced_columns),
            "visuals": sorted(self.visuals),
            "pages": sorted(self.pages),
            "depends_on_measures": sorted(self.depends_on_measures),
            "used_by_measures": sorted(self.used_by_measures),
        }
