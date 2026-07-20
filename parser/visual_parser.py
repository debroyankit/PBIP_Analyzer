"""Parses an individual visual's JSON definition.

Handles both the modern PBIR ``visual.json`` shape:

    {"visual": {"visualType": "columnChart", "query": {"queryState": {...}}}}

and the legacy single-file report shape, where each visualContainer's
``config`` string (itself JSON) contains:

    {"singleVisual": {"visualType": "columnChart", "prototypeQuery": {...}}}

Rather than hand-coding every nesting shape Power BI uses for field
references (Column / Measure / Aggregation / HierarchyLevel wrappers, which
vary across visual types and versions), this module walks the JSON tree
generically: any dict with sibling ``"Property"`` and ``"Expression"`` keys
is treated as a field reference, and the owning table is found by searching
inside ``"Expression"`` for a nested ``SourceRef.Entity``. This is more
resilient to schema variations than hardcoding paths per visual type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.logging_config import get_logger

logger = get_logger("visual_parser")


@dataclass
class RawVisual:
    """Raw, unresolved data extracted from a single visual's JSON."""

    id: str
    title: str
    type: str
    raw_field_refs: set[tuple[str, str]] = field(default_factory=set)


def parse_visual(visual_json: dict[str, Any], visual_id: str) -> RawVisual:
    """Parse a single visual's JSON (either PBIR or legacy shape).

    Args:
        visual_json: Parsed JSON for one visual/visualContainer.
        visual_id: Internal id (PBIR folder name, or a generated index for
            legacy reports) used as a fallback title and for uniqueness.

    Returns:
        A RawVisual with type, best-effort title, and raw (table, field)
        reference pairs.
    """
    visual_type = _extract_visual_type(visual_json)
    title = _extract_title(visual_json) or (visual_type or "visual")
    field_refs = set(_extract_field_refs(visual_json))

    return RawVisual(id=visual_id, title=title, type=visual_type or "unknown", raw_field_refs=field_refs)


def _extract_visual_type(visual_json: dict[str, Any]) -> str | None:
    """Find the visual type string across known PBIR/legacy locations."""
    modern = visual_json.get("visual")
    if isinstance(modern, dict) and modern.get("visualType"):
        return str(modern["visualType"])

    legacy = visual_json.get("singleVisual")
    if isinstance(legacy, dict) and legacy.get("visualType"):
        return str(legacy["visualType"])

    if visual_json.get("visualType"):
        return str(visual_json["visualType"])

    return None


def _extract_title(visual_json: dict[str, Any]) -> str | None:
    """Best-effort search for a user-set visual title.

    Power BI stores title text as a DAX-literal string buried inside
    ``objects.title[*].properties.text.expr.Literal.Value`` or
    ``visualContainerObjects.title[*].properties.text.expr.Literal.Value``
    (format varies slightly by version). We search generically for any
    "Literal" -> "Value" pair or direct string property that sits underneath
    a "title" key in either container, rather than hardcoding the full path.
    """
    containers = []
    visual = visual_json.get("visual")
    if isinstance(visual, dict):
        containers.append(visual.get("objects"))
        containers.append(visual.get("visualContainerObjects"))
        containers.append(visual.get("vcObjects"))
    containers.append(visual_json.get("objects"))
    containers.append(visual_json.get("visualContainerObjects"))
    containers.append(visual_json.get("vcObjects"))

    for container in containers:
        if not isinstance(container, dict):
            continue
        title_objects = container.get("title")
        if not isinstance(title_objects, list):
            continue

        for title_obj in title_objects:
            if not isinstance(title_obj, dict):
                continue
            properties = title_obj.get("properties")
            if not isinstance(properties, dict):
                continue
            text_node = properties.get("text")
            if text_node is not None:
                literal_value = _find_first_literal_value(text_node)
                if literal_value is not None:
                    # Literal string values are stored quoted, e.g. "'My Title'".
                    return literal_value.strip("'\"")

    return None


def _find_first_literal_value(node: Any) -> str | None:
    if isinstance(node, dict):
        # 1. Check for standard Literal Value structure
        literal = node.get("Literal")
        if isinstance(literal, dict) and isinstance(literal.get("Value"), str):
            return literal["Value"]

        # 2. Check for direct "text", "Value", "value", or "staticValue" strings
        for key in ["text", "Value", "value", "staticValue"]:
            val = node.get(key)
            if isinstance(val, str):
                return val
            if isinstance(val, dict):
                res = _find_first_literal_value(val)
                if res is not None:
                    return res

        # 3. Recursively search other keys
        for k, v in node.items():
            if k not in ["text", "Value", "value", "staticValue"]:
                res = _find_first_literal_value(v)
                if res is not None:
                    return res
    elif isinstance(node, list):
        for item in node:
            result = _find_first_literal_value(item)
            if result is not None:
                return result
    return None


def _extract_field_refs(node: Any) -> list[tuple[str, str]]:
    """Recursively collect (table, field_name) pairs from a JSON subtree."""
    refs: list[tuple[str, str]] = []

    if isinstance(node, dict):
        if "Property" in node and "Expression" in node and isinstance(node["Property"], str):
            entity = _find_entity(node["Expression"])
            if entity:
                refs.append((entity, node["Property"]))
        for value in node.values():
            refs.extend(_extract_field_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_extract_field_refs(item))

    return refs


def _find_entity(node: Any) -> str | None:
    """Recursively search for the nearest 'SourceRef': {'Entity': ...}."""
    if isinstance(node, dict):
        source_ref = node.get("SourceRef")
        if isinstance(source_ref, dict) and isinstance(source_ref.get("Entity"), str):
            return source_ref["Entity"]
        for value in node.values():
            result = _find_entity(value)
            if result is not None:
                return result
    elif isinstance(node, list):
        for item in node:
            result = _find_entity(item)
            if result is not None:
                return result
    return None
