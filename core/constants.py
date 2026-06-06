"""Minecraft 相关常量定义

集中管理项目中所有硬编码的常量，便于维护和统一修改。
"""

from typing import Dict, Set, List


class MinecraftConstants:
    """Minecraft 相关常量类

    包含 API 端点、版本映射、清理模式、文件扩展名等所有项目使用的常量。
    """

    # ==================== API 端点 ====================
    MOJANG_API_BASE: str = "https://api.mojang.com"
    MOJANG_PROFILE_URL: str = f"{MOJANG_API_BASE}/users/profiles/minecraft/"
    MOJANG_SESSION_URL: str = f"{MOJANG_API_BASE}/session/minecraft/profile/"

    # ==================== 版本映射 ====================
    VERSION_MAP: Dict[int, str] = {
        404: "1.13.2", 402: "1.13.1", 401: "1.13",
        393: "1.13", 340: "1.12.2", 338: "1.12.1", 335: "1.12",
        316: "1.11.2", 315: "1.11", 210: "1.10.2", 205: "1.9.4",
        184: "1.9.2", 176: "1.9", 169: "1.8.9", 163: "1.8.3",
        127: "1.7.10", 124: "1.7.9", 95: "1.7.2", 78: "1.6.4",
        77: "1.6.3", 74: "1.6.2", 73: "1.6.1", 61: "1.5.2",
        60: "1.5.1", 51: "1.5", 47: "1.4.7", 39: "1.3.2",
        29: "1.2.5", 13: "1.1", 8: "1.0.1", 6: "1.0.0"
    }

    VERSION_REVERSE_MAP: Dict[str, int] = {
        version_name: version_id
        for version_id, version_name in VERSION_MAP.items()
    }

    # ==================== 清理模式 ====================
    CLEAN_PATTERNS: Set[str] = {
        "logs", "crash-reports", "session.lock", ".ds_store", "thumbs.db",
        "server-resource-packs", "downloads", "journeymap", "xaero", "voxelmap"
    }

    CLEAN_EXTENSIONS: Set[str] = {
        ".clientcache",
        ".log"
    }

    CLEANUP_PATTERNS_DEFAULT: List[str] = [
        "*.log", "cache/", "logs/"
    ]

    # ==================== 文件扩展名 ====================
    NBT_EXTENSIONS: Set[str] = {".dat", ".mca", ".mcr"}
    REGION_FILE_PATTERN: str = "r.*.*.mca"

    # ==================== 其他常量 ====================
    API_TIMEOUT_DEFAULT: int = 10
    BATCH_PROCESSING_MAX_CONCURRENT_DEFAULT: int = 4
    VERSION_DETECTION_DEFAULT: bool = True
    UI_THEME_DEFAULT: str = "dark"
    UI_AUTO_CLEAR_LOG_DEFAULT: bool = True


# 导出常用别名
MOJANG_PROFILE_URL: str = MinecraftConstants.MOJANG_PROFILE_URL
MOJANG_SESSION_URL: str = MinecraftConstants.MOJANG_SESSION_URL
VERSION_MAP: Dict[int, str] = MinecraftConstants.VERSION_MAP
CLEAN_PATTERNS: Set[str] = MinecraftConstants.CLEAN_PATTERNS
CLEAN_EXTENSIONS: Set[str] = MinecraftConstants.CLEAN_EXTENSIONS
CLEANUP_PATTERNS_DEFAULT: List[str] = MinecraftConstants.CLEANUP_PATTERNS_DEFAULT
NBT_EXTENSIONS: Set[str] = MinecraftConstants.NBT_EXTENSIONS
REGION_FILE_PATTERN: str = MinecraftConstants.REGION_FILE_PATTERN
