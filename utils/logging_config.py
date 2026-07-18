"""Central logging configuration for the analyzer.

Using a single ``configure_logging`` entry point keeps log formatting
consistent whether the package is run as a CLI or imported into another
application (e.g. a FastAPI service), where the host application may want to
control verbosity independently.
"""

from __future__ import annotations

import logging
import sys


def configure_logging(verbose: bool = False) -> logging.Logger:
    """Configure and return the package's root logger.

    Args:
        verbose: When True, sets DEBUG level; otherwise INFO.

    Returns:
        The configured logger named "pbip_analyzer".
    """
    logger = logging.getLogger("pbip_analyzer")

    # Avoid attaching duplicate handlers if configure_logging is called
    # multiple times (e.g. repeated calls to analyze_pbip in a long-lived
    # process such as a web server).
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def get_logger(module_name: str) -> logging.Logger:
    """Return a child logger namespaced under 'pbip_analyzer'."""
    return logging.getLogger(f"pbip_analyzer.{module_name}")
