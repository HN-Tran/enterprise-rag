"""Logging utilities."""

from __future__ import annotations

import logging
import sys


def setup_logging() -> None:
    """Configure structured-ish logging suitable for services and CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stdout,
    )
