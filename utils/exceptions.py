"""Custom exception hierarchy used throughout the analyzer.

Keeping a dedicated exception hierarchy lets ``main.py`` catch a single base
class for a clean CLI error message, while callers embedding this package
(e.g. a future FastAPI service) can catch specific subclasses to return
targeted HTTP error codes.
"""

from __future__ import annotations


class PBIPAnalyzerError(Exception):
    """Base class for all expected/handled errors raised by this package."""


class InvalidPBIPFileError(PBIPAnalyzerError):
    """Raised when the given path is not a valid .pbip project file."""


class SemanticModelNotFoundError(PBIPAnalyzerError):
    """Raised when the semantic model folder/definition cannot be located."""


class ReportNotFoundError(PBIPAnalyzerError):
    """Raised when the report folder/definition cannot be located."""


class CorruptFileError(PBIPAnalyzerError):
    """Raised when a JSON/TMDL file exists but cannot be parsed."""
