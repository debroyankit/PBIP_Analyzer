"""Parses a PBIP Report folder into raw pages and visuals.

Supports both report formats Power BI Desktop can save:

1. Modern, folder-based **PBIR** (the default since late 2024):

    MyReport.Report/
        definition.pbir
        definition/
            report.json
            pages/
                pages.json
                <pageId>/
                    page.json
                    visuals/
                        <visualId>/
                            visual.json

2. Legacy single-file report:

    MyReport.Report/
        report.json      (contains "sections": [{"visualContainers": [...]}])
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from parser.visual_parser import RawVisual, parse_visual
from utils.exceptions import CorruptFileError, ReportNotFoundError
from utils.file_utils import read_json_safe
from utils.logging_config import get_logger

logger = get_logger("report_parser")


@dataclass
class RawPage:
    name: str
    visual_ids: list[str] = field(default_factory=list)


@dataclass
class RawReport:
    pages: list[RawPage] = field(default_factory=list)
    visuals: dict[str, RawVisual] = field(default_factory=dict)  # keyed by visual id


def parse_report(report_dir: Path) -> RawReport:
    """Parse a report folder, auto-detecting PBIR vs legacy format.

    Args:
        report_dir: Resolved '*.Report' directory.

    Returns:
        A RawReport containing every page and every visual found.

    Raises:
        ReportNotFoundError: If neither a PBIR 'definition/pages' folder nor
            a legacy 'report.json' can be found.
    """
    pages_dir = report_dir / "definition" / "pages"
    legacy_report_json = report_dir / "report.json"

    if pages_dir.is_dir():
        logger.info("Detected PBIR (folder-based) report format.")
        return _parse_pbir_report(pages_dir)

    if legacy_report_json.is_file():
        logger.info("Detected legacy single-file report format.")
        return _parse_legacy_report(legacy_report_json)

    raise ReportNotFoundError(
        f"'{report_dir}' contains neither 'definition/pages/' (PBIR) nor "
        "'report.json' (legacy)."
    )


# --------------------------------------------------------------------------
# Modern PBIR parsing
# --------------------------------------------------------------------------


def _parse_pbir_report(pages_dir: Path) -> RawReport:
    report = RawReport()

    page_dirs = sorted(p for p in pages_dir.iterdir() if p.is_dir())
    for page_dir in page_dirs:
        page_json_path = page_dir / "page.json"
        if not page_json_path.is_file():
            logger.warning("Skipping '%s': no page.json found.", page_dir)
            continue

        page_content = read_json_safe(page_json_path)
        if not isinstance(page_content, dict):
            raise CorruptFileError(f"'{page_json_path}' does not contain a JSON object.")

        page_name = page_content.get("displayName") or page_content.get("name") or page_dir.name
        raw_page = RawPage(name=page_name)

        visuals_dir = page_dir / "visuals"
        if visuals_dir.is_dir():
            for visual_dir in sorted(p for p in visuals_dir.iterdir() if p.is_dir()):
                visual_json_path = visual_dir / "visual.json"
                if not visual_json_path.is_file():
                    continue
                visual_content = read_json_safe(visual_json_path)
                if not isinstance(visual_content, dict):
                    logger.warning("Skipping non-object visual.json at '%s'.", visual_json_path)
                    continue

                raw_visual = parse_visual(visual_content, visual_id=f"{page_dir.name}::{visual_dir.name}")
                report.visuals[raw_visual.id] = raw_visual
                raw_page.visual_ids.append(raw_visual.id)

        report.pages.append(raw_page)

    return report


# --------------------------------------------------------------------------
# Legacy single-file report parsing
# --------------------------------------------------------------------------


def _parse_legacy_report(report_json_path: Path) -> RawReport:
    content = read_json_safe(report_json_path)
    if not isinstance(content, dict):
        raise CorruptFileError(f"'{report_json_path}' does not contain a JSON object.")

    report = RawReport()
    sections = content.get("sections", [])

    for section_index, section in enumerate(sections):
        page_name = section.get("displayName") or section.get("name") or f"Page {section_index + 1}"
        raw_page = RawPage(name=page_name)

        for vc_index, visual_container in enumerate(section.get("visualContainers", [])):
            visual_id = f"{page_name}::visual{vc_index}"
            config_raw = visual_container.get("config")
            visual_content: dict[str, Any] = {}

            if isinstance(config_raw, str):
                try:
                    visual_content = json.loads(config_raw)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Could not parse visualContainer config JSON in '%s' (%s): %s",
                        report_json_path,
                        visual_id,
                        exc,
                    )
            elif isinstance(config_raw, dict):
                visual_content = config_raw

            raw_visual = parse_visual(visual_content, visual_id=visual_id)
            report.visuals[raw_visual.id] = raw_visual
            raw_page.visual_ids.append(raw_visual.id)

        report.pages.append(raw_page)

    return report
