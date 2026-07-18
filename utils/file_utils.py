"""Small, reusable filesystem helpers.

These wrap the standard library with consistent error handling so parser
modules do not need to repeat try/except boilerplate around every file read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.exceptions import CorruptFileError
from utils.logging_config import get_logger

logger = get_logger("file_utils")


def read_text_safe(path: Path) -> str:
    """Read a text file, raising CorruptFileError on decode failures.

    Args:
        path: Path to the file to read.

    Returns:
        File contents as a string.

    Raises:
        CorruptFileError: If the file cannot be read or decoded.
    """
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise CorruptFileError(f"Could not read file '{path}': {exc}") from exc


def read_json_safe(path: Path) -> dict[str, Any] | list[Any]:
    """Read and parse a JSON file, raising CorruptFileError on failure.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON content (dict or list).

    Raises:
        CorruptFileError: If the file is missing, unreadable, or not valid JSON.
    """
    text = read_text_safe(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptFileError(f"Invalid JSON in '{path}': {exc}") from exc


def find_dir_by_suffix(root: Path, suffix: str) -> Path | None:
    """Find the first immediate subdirectory of `root` ending with `suffix`.

    Used as a fallback discovery mechanism (e.g. locating a '*.SemanticModel'
    or '*.Report' folder) when explicit references are not available.

    Args:
        root: Directory to scan (non-recursive, immediate children only).
        suffix: Suffix to match, e.g. ".SemanticModel".

    Returns:
        The matching directory Path, or None if not found.
    """
    if not root.is_dir():
        return None
    matches = sorted(p for p in root.iterdir() if p.is_dir() and p.name.endswith(suffix))
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(
            "Multiple '%s' folders found under %s; using the first: %s",
            suffix,
            root,
            matches[0].name,
        )
    return matches[0]


def list_files(directory: Path, pattern: str) -> list[Path]:
    """Return sorted files under `directory` matching a glob `pattern`.

    Args:
        directory: Directory to search (recursively, via rglob).
        pattern: Glob pattern, e.g. "*.tmdl".

    Returns:
        Sorted list of matching file paths. Empty list if directory absent.
    """
    if not directory.is_dir():
        return []
    return sorted(directory.rglob(pattern))
