"""Data model representing a report visual and its dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Visual:
    """A single visual container inside a report page.

    Attributes:
        id: The internal visual/container id (folder name in PBIR, or a
            generated id for legacy reports).
        title: Human-readable title if one could be resolved, otherwise a
            fallback such as "<type> (<id>)".
        type: The Power BI visual type (e.g. "columnChart", "card").
        page: Name of the page this visual belongs to.
        tables: Tables referenced by this visual, including tables pulled in
            transitively through measures used by the visual.
        columns: Fully qualified "Table[Column]" fields used by this visual.
        measures: Measure names used by this visual.
        raw_field_refs: Internal, unresolved (table, field) pairs collected
            directly from the visual JSON before columns/measures are
            disambiguated against the semantic model. Not part of the public
            output contract, kept for extensibility/debugging.
    """

    id: str
    title: str
    type: str
    page: str
    tables: set[str] = field(default_factory=set)
    columns: set[str] = field(default_factory=set)
    measures: set[str] = field(default_factory=set)
    raw_field_refs: set[tuple[str, str]] = field(default_factory=set, repr=False)

    def to_dict(self) -> dict[str, object]:
        """Serialize to a JSON-friendly dict with deterministic ordering."""
        return {
            "title": self.title,
            "type": self.type,
            "page": self.page,
            "tables": sorted(self.tables),
            "columns": sorted(self.columns),
            "measures": sorted(self.measures),
        }
