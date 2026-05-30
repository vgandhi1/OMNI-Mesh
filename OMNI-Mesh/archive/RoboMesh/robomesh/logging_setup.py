"""Structured logging for RoboMesh.

We intentionally restrict what gets logged: only event names, correlation IDs,
counts, and non-sensitive metadata. Per the workspace logging rules we never
emit raw rows, PII, secrets, or full payloads.
"""
from __future__ import annotations

import logging
import os
import sys
from logging import Logger

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def get_logger(name: str) -> Logger:
    """Return a configured logger.

    Calling this multiple times is safe — the handler is attached only once.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(os.environ.get("ROBOMESH_LOG_LEVEL", "INFO").upper())
        logger.propagate = False
    return logger
