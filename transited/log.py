"""
Logging configuration for transited.

Provides a module-level logger and a one-call setup function.
"""
from __future__ import annotations

import logging
import sys

LOG = logging.getLogger('transited')


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the transited logger with a simple console handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    ))
    LOG.addHandler(handler)
    LOG.setLevel(level)
