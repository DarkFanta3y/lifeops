from __future__ import annotations

import logging

from rich.logging import RichHandler


def setup_logger(name: str = "lifeops", level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        handler = RichHandler(show_time=True, show_path=False, markup=True)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


def get_logger(name: str = "lifeops") -> logging.Logger:
    return logging.getLogger(name)