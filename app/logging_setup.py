"""
logging_setup.py — налаштування логування для всього застосунку.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_file: str | None = None) -> None:
    """
    Ініціалізує кореневий логер з форматом та рівнем.

    Args:
        log_level: Рівень логування (DEBUG, INFO, WARNING, ERROR).
        log_file:  Якщо задано — також пише у файл.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    root = logging.getLogger()
    root.setLevel(level)

    # Консоль
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        root.addHandler(sh)

    # Файл (опційно)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # Приглушуємо зайвий шум від бібліотек
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("telebot").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Зручна обгортка для отримання логера."""
    return logging.getLogger(name)
