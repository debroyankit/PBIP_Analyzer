"""Data model representing a report page."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Page:
    """A single report page.

    Attributes:
        name: Display name of the page (falls back to internal id if no
            display name is set).
        visuals: Unique visual IDs of the visuals placed on this page.
        tables: Union of all tables referenced by visuals on this page.
    """

    name: str
    visuals: set[str] = field(default_factory=set)
    tables: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, list[str]]:
        """Serialize to a JSON-friendly dict with deterministic ordering."""
        return {
            "visuals": sorted(self.visuals),
            "tables": sorted(self.tables),
        }
