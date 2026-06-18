"""中心化日志管理系统（门面模式）

向后兼容：保留原导入路径
    from core.logger import logger, LogLevel, setup_default_logging, LogRecord
"""
from core.logging import logger, setup_default_logging
from core.logging.models import LogLevel, LogRecord
from core.logging.handlers import ConsoleHandler, FileHandler, LogHandler, UIHandler
from core.logging.manager import LogManager

__all__ = [
    "logger", "LogLevel", "LogRecord", "LogHandler", "LogManager",
    "ConsoleHandler", "FileHandler", "UIHandler", "setup_default_logging",
]
