"""Locates the Semantic Model and Report artifacts for a given .pbip file.

A .pbip file is a small JSON pointer file that sits next to two sibling
folders:

    MyProject.pbip
    MyProject.Report/
        definition.pbir        <- points back to the semantic model
        definition/...          (modern PBIR folder-based report)
        report.json             (legacy single-file report, if not PBIR)
    MyProject.SemanticModel/
        definition/             (modern TMDL folder-based model)
        model.bim               (legacy TMSL/JSON model, if not TMDL)

This module never hardcodes folder names beyond the well-known ".pbip",
".Report" and ".SemanticModel" suffixes used by Power BI Desktop itself, and
resolves the actual project-specific names dynamically.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from utils.exceptions import (
    InvalidPBIPFileError,
    ReportNotFoundError,
    SemanticModelNotFoundError,
)
from utils.file_utils import find_dir_by_suffix, read_json_safe
from utils.logging_config import get_logger

logger = get_logger("pbip_loader")


@dataclass
class PBIPProject:
    """Resolved paths for a loaded PBIP project."""

    pbip_path: Path
    project_root: Path
    report_dir: Path
    semantic_model_dir: Path


def load_pbip_project(pbip_path_str: str) -> PBIPProject:
    """Validate a .pbip path and resolve its Report/SemanticModel folders.

    Args:
        pbip_path_str: Path to the .pbip file (as given on the CLI or API).

    Returns:
        A populated PBIPProject with resolved, existing directories.

    Raises:
        InvalidPBIPFileError: If the path doesn't exist, isn't a .pbip file,
            or the pointer file is corrupt.
        ReportNotFoundError: If the report folder can't be located.
        SemanticModelNotFoundError: If the semantic model folder can't be
            located.
    """
    pbip_path = Path(pbip_path_str).expanduser().resolve()

    if pbip_path.suffix.lower() != ".pbip":
        raise InvalidPBIPFileError(
            f"Expected a '.pbip' file, got: '{pbip_path}'. "
            "PBIX files are not supported by this tool."
        )
    if not pbip_path.is_file():
        raise InvalidPBIPFileError(f".pbip file not found: '{pbip_path}'")

    project_root = pbip_path.parent
    pbip_content = read_json_safe(pbip_path)
    if not isinstance(pbip_content, dict):
        raise InvalidPBIPFileError(f"'{pbip_path}' does not contain a JSON object.")

    report_dir = _resolve_report_dir(pbip_content, project_root)
    semantic_model_dir = _resolve_semantic_model_dir(report_dir, project_root)

    logger.info("Resolved report folder: %s", report_dir)
    logger.info("Resolved semantic model folder: %s", semantic_model_dir)

    return PBIPProject(
        pbip_path=pbip_path,
        project_root=project_root,
        report_dir=report_dir,
        semantic_model_dir=semantic_model_dir,
    )


def _resolve_report_dir(pbip_content: dict, project_root: Path) -> Path:
    """Resolve the report folder from the .pbip 'artifacts' section.

    Falls back to scanning for a sibling '*.Report' folder if the pointer
    JSON doesn't have the expected shape (keeps the loader resilient to
    minor format variations across Power BI Desktop versions).
    """
    report_dir: Path | None = None

    artifacts = pbip_content.get("artifacts", [])
    for artifact in artifacts:
        report_ref = artifact.get("report") if isinstance(artifact, dict) else None
        if report_ref and report_ref.get("path"):
            candidate = (project_root / report_ref["path"]).resolve()
            if candidate.is_dir():
                report_dir = candidate
                break

    if report_dir is None:
        logger.debug("No usable 'artifacts.report.path' in .pbip; scanning siblings.")
        report_dir = find_dir_by_suffix(project_root, ".Report")

    if report_dir is None or not report_dir.is_dir():
        raise ReportNotFoundError(
            f"Could not locate a '*.Report' folder next to '{project_root}'."
        )
    return report_dir


def _resolve_semantic_model_dir(report_dir: Path, project_root: Path) -> Path:
    """Resolve the semantic model folder.

    Preferred path: read 'definition.pbir' inside the report folder, which
    contains a datasetReference pointing at the semantic model folder
    (relative path). Falls back to scanning for a sibling '*.SemanticModel'
    folder.
    """
    semantic_model_dir: Path | None = None
    pbir_path = report_dir / "definition.pbir"

    if pbir_path.is_file():
        try:
            pbir_content = read_json_safe(pbir_path)
        except Exception as exc:  # noqa: BLE001 - degrade to fallback search
            logger.warning("Could not parse '%s': %s", pbir_path, exc)
            pbir_content = {}

        if isinstance(pbir_content, dict):
            dataset_ref = pbir_content.get("datasetReference", {})
            by_path = dataset_ref.get("byPath") if isinstance(dataset_ref, dict) else None
            rel_path = by_path.get("path") if isinstance(by_path, dict) else None
            if rel_path:
                candidate = (report_dir / rel_path).resolve()
                if candidate.is_dir():
                    semantic_model_dir = candidate

    if semantic_model_dir is None:
        logger.debug("Falling back to sibling-folder scan for the semantic model.")
        semantic_model_dir = find_dir_by_suffix(project_root, ".SemanticModel")

    if semantic_model_dir is None or not semantic_model_dir.is_dir():
        raise SemanticModelNotFoundError(
            f"Could not locate a '*.SemanticModel' folder for report '{report_dir}'."
        )
    return semantic_model_dir
