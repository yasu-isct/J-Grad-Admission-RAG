"""Message-only CLI diagnostics without changing an embedding application's logging."""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def cli_diagnostics(logger: logging.Logger) -> Iterator[None]:
    """Temporarily route this command's warnings/errors to the current stderr.

    JSON responses and normal CLI output are not diagnostics and use their
    existing streams directly. Restore configuration for repeated in-process use.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))
    previous_level, previous_propagate = logger.level, logger.propagate
    previous_handlers = logger.handlers[:]
    logger.handlers = [handler]
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        yield
    finally:
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        handler.close()
