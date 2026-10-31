"""One logger for the whole package: INFO on the console, DEBUG in a rotating file."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src import settings

LOGGER_NAME = "refund_agent"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: str = "INFO", log_dir: Path | None = None, force: bool = False) -> logging.Logger:
    """Configure and return the package logger. Safe to call many times; `force` reconfigures (tests, new log dir)."""
    log_dir = Path(log_dir or settings.LOG_DIR)
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_refund_agent_configured", False):
        if not force:
            return logger
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(console)

    file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=1_000_000, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(file_handler)

    logger._refund_agent_configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Child logger under the package logger, e.g. get_logger('engine')."""
    base = logging.getLogger(LOGGER_NAME)
    return base.getChild(name) if name else base
