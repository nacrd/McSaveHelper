"""Minecraft 相关常量定义

集中管理项目中所有硬编码的常量，便于维护和统一修改。
"""

from typing import Dict, Set, List


class MinecraftConstants:
    """Minecraft 相关常量"""
    
    # ==================== API 端点 ====================
    MOJANG_API_BASE = "https://api.mojang.com"
    MOJANG_PROFILE_URL = f"{MOJANG_API_BASE}/users/profiles/minecraft/"
    MOJANG_SESSION_URL = f"{MOJANG_API_BASE}/session/minecraft/profile/"
    
    # ==================== 版本映射 ====================
    # 版本ID到版本名称的映射（用于检测Minecraft版本）
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
    
    # 版本名称到版本ID的映射（反向映射，按需使用）
    VERSION_REVERSE_MAP: Dict[str, int] = {
        version_name: version_id
        for version_id, version_name in VERSION_MAP.items()
    }
    
    # ==================== 清理模式 ====================
    # 清理器使用的文件名/目录名模式（小写）
    CLEAN_PATTERNS: Set[str] = {
        "logs", "crash-reports", "session.lock", ".ds_store", "thumbs.db",
        "server-resource-packs", "downloads", "journeymap", "xaero", "voxelmap"
    }
    
    # 清理器使用的文件扩展名模式（小写）
    CLEAN_EXTENSIONS: Set[str] = {
        ".clientcache",
        ".log"
    }
    
    # 配置中使用的默认清理模式（glob模式）
    CLEANUP_PATTERNS_DEFAULT: List[str] = [
        "*.log", "cache/", "logs/"
    ]
    
    # ==================== 文件扩展名 ====================
    # NBT 文件扩展名
    NBT_EXTENSIONS: Set[str] = {".dat", ".mca", ".mcr"}
    
    # 区域文件模式
    REGION_FILE_PATTERN = "r.*.*.mca"
    
    # ==================== 其他常量 ====================
    # 默认API超时时间（秒）
    API_TIMEOUT_DEFAULT = 10
    
    # 默认批量处理最大并发数
    BATCH_PROCESSING_MAX_CONCURRENT_DEFAULT = 4
    
    # 默认版本检测开关
    VERSION_DETECTION_DEFAULT = True
    
    # 默认UI主题
    UI_THEME_DEFAULT = "dark"
    
    # 默认自动清理日志开关
    UI_AUTO_CLEAR_LOG_DEFAULT = True


# 导出常用别名
MOJANG_PROFILE_URL = MinecraftConstants.MOJANG_PROFILE_URL
MOJANG_SESSION_URL = MinecraftConstants.MOJANG_SESSION_URL
VERSION_MAP = MinecraftConstants.VERSION_MAP
CLEAN_PATTERNS = MinecraftConstants.CLEAN_PATTERNS
CLEAN_EXTENSIONS = MinecraftConstants.CLEAN_EXTENSIONS
CLEANUP_PATTERNS_DEFAULT = MinecraftConstants.CLEANUP_PATTERNS_DEFAULT
NBT_EXTENSIONS = MinecraftConstants.NBT_EXTENSIONS
REGION_FILE_PATTERN = MinecraftConstants.REGION_FILE_PATTERN