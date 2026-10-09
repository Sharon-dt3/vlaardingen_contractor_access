"""Logging configuration for the API process."""

from __future__ import annotations

import logging
from logging.config import dictConfig


# PUBLIC_INTERFACE
def configure_logging(log_level: str) -> None:
    """Configure consistent process and Uvicorn logging.

    Args:
        log_level: The configured logging threshold name.
    """

    level = log_level.upper()
    if level not in logging.getLevelNamesMapping():
        level = "INFO"

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                "uvicorn": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )
