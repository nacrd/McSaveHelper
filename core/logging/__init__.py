"""Logging package."""
from pathlib import Path
from typing import Optional

from core.types import LogCallback
from .models import LogLevel, LogRecord
from .handlers import ConsoleHandler, FileHandler, LogHandler, UIHandler
from .manager import LogManager

__all__ = [
    "ConsoleHandler",
    "FileHandler",
    "LogHandler",
    "LogLevel",
    "LogManager",
    "LogRecord",
    "UIHandler",
    "logger",
    "setup_default_logging",
]

logger: LogManager = LogManager()


def setup_default_logging(
    enable_console: bool = True,
    enable_file: bool = True,
    file_path: Optional[Path] = None,
    enable_ui: bool = False,
    ui_callback: Optional[LogCallback] = None,
    level: LogLevel = LogLevel.INFO
) -> None:
    """设置默认日志配置"""
    for handler in logger.handlers[:]:
        logger.remove_handler(handler)
    logger.set_level(level)
    if enable_console:
        logger.add_handler(ConsoleHandler(level=level))
    if enable_file:
        if file_path is None:
            file_path = Path.home() / ".mcsavehelper" / "logs" / "app.log"
        logger.add_handler(FileHandler(
            filepath=file_path,
            level=level,
            max_size=10 * 1024 * 1024,
            backup_count=5,
        ))
    if enable_ui and ui_callback:
        logger.add_handler(UIHandler(ui_callback, level=level))
