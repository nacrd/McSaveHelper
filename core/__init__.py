"""Core Module —— 核心业务逻辑层

提供 Minecraft 存档转换的核心功能模块。
"""

from core.types import (
    LogCallback,
    ProgressCallback,
    UUIDMapping,
    ProcessResult,
    BatchResult,
    RegionProcessResult,
)

from core.constants import (
    MinecraftConstants,
    MOJANG_PROFILE_URL,
    MOJANG_SESSION_URL,
    VERSION_MAP,
    CLEAN_PATTERNS,
    CLEAN_EXTENSIONS,
    NBT_EXTENSIONS,
)

from core.logger import logger, LogLevel, setup_default_logging

# 延迟导入，避免循环依赖
# from core import i18n
# from core import converter

__all__ = [
    # types
    "LogCallback",
    "ProgressCallback",
    "UUIDMapping",
    "ProcessResult",
    "BatchResult",
    "RegionProcessResult",
    # constants
    "MinecraftConstants",
    "MOJANG_PROFILE_URL",
    "MOJANG_SESSION_URL",
    "VERSION_MAP",
    "CLEAN_PATTERNS",
    "CLEAN_EXTENSIONS",
    "NBT_EXTENSIONS",
    # logger
    "logger",
    "LogLevel",
    "setup_default_logging",
]
