import logging
import os
import sys
from pathlib import Path

import colorlog

from data.config import path_logs
from utils.datetime_tools import DateTime


def _resolve_level() -> int:
    configured_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
    return getattr(logging, configured_level, logging.DEBUG)


def _apply_level(logger: logging.Logger, level: int) -> None:
    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("gemini_message_manager")
    level = _resolve_level()

    if logger.handlers:
        _apply_level(logger, level)
        return logger

    log_path = Path(path_logs.format(d=DateTime().time_strftime("%d.%m.%Y")))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_log = logging.FileHandler(log_path, "a+", "utf-8")
    # Use stdout to make logs visible in IDE run consoles that do not show stderr by default.
    console_out = logging.StreamHandler(sys.stdout)

    formatter = colorlog.ColoredFormatter(
        "%(log_color)s[%(asctime)s | %(levelname)s]%(reset)s%(blue)s: %(filename)s | %(funcName)s:%(lineno)d - %(white)s%(message)s",
        datefmt="%d.%m.%Y %H:%M:%S",
        reset=True,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )

    console_out.setFormatter(formatter)
    file_log.setFormatter(
        logging.Formatter(
            "[%(asctime)s | %(levelname)s]: %(filename)s | %(funcName)s:%(lineno)d - %(message)s",
            datefmt="%m.%d.%Y %H:%M:%S",
        )
    )

    logger.addHandler(file_log)
    logger.addHandler(console_out)
    logger.propagate = False
    _apply_level(logger, level)

    logging.getLogger("aiogram").setLevel(logging.ERROR)
    logging.getLogger("apscheduler").setLevel(logging.ERROR)
    logging.getLogger("aiomysql").setLevel(logging.ERROR)
    logging.getLogger("asyncio").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("pyrogram").setLevel(logging.INFO)
    logging.getLogger("pyrotgfork").setLevel(logging.INFO)
    logging.getLogger("aiohttp").setLevel(logging.INFO)
    logging.getLogger("requests").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logger.info(f"Logger initialized with level: {logging.getLevelName(level)}")
    return logger


def error_handler(exc_type, value, tb):
    bot_logger.critical(
        f"Exception '{exc_type.__name__}': {value}. File: '{tb.tb_frame.f_code.co_filename}'. Line: {tb.tb_lineno}"
    )


bot_logger = _build_logger()
