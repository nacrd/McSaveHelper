"""配置数据模型"""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class BatchSettings:
    """批量处理设置类
    
    用于配置批量处理时的并发数量和结构保留选项。
    """
    max_concurrent: int = 2
    """最大并发处理数量，默认为2"""
    
    preserve_structure: bool = True
    """是否保留目录结构，默认为True"""


@dataclass
class UISettings:
    """界面设置类
    
    用于配置应用程序的界面显示选项。
    """
    theme: str = "dark"
    """界面主题，默认为深色主题"""
    
    auto_clear_log: bool = True
    """是否自动清除日志，默认为True"""
    
    language: str = "zh_CN"
    """界面语言，默认为简体中文"""


@dataclass
class MigrationConfig:
    """迁移任务配置（运行时状态）
    
    用于存储当前迁移任务的所有参数配置。
    """
    mode: str = "fast"
    """迁移模式，可选值为 "fast"（快速模式）或 "full"（完整模式）"""
    
    src_path: str = ""
    """源存档目录路径"""
    
    dest_path: str = ""
    """目标输出目录路径"""
    
    world_name: str = "world"
    """世界存档名称，默认为 "world" """
    
    offline_mode: bool = False
    """是否启用离线模式，默认为False"""
    
    clean_mode: bool = True
    """是否启用清理模式，默认为True"""
    
    pure_clean_mode: bool = False
    """是否启用纯清理模式，默认为False"""
    
    version_detection: bool = True
    """是否启用版本检测，默认为True"""
    
    batch_mode: bool = False
    """是否启用批量模式，默认为False"""
    
    batch_dir_path: str = ""
    """批量处理目录路径"""
    
    manual_names: str = ""
    """逗号分隔的手动指定玩家名称列表"""
    
    query_name: str = ""
    """查询用的玩家名称"""

    target_platform: str = "java"
    """目标平台，可选值为 "java" 或 "bedrock"""

    target_version: str = ""
    """目标 Minecraft 数据版本 ID，留空表示不做版本降级"""


@dataclass
class AppConfig:
    """应用完整配置（持久化到 ~/.mcsavehelper/config.json）
    
    用于存储应用程序的所有持久化配置项。
    """
    version: int = 2
    """配置文件版本号，默认为2"""
    
    version_detection: bool = True
    """是否启用版本检测功能，默认为True"""
    
    use_custom_mapping: bool = False
    """是否使用自定义UUID映射，默认为False"""
    
    custom_uuid_mappings: Dict[str, str] = field(default_factory=dict)
    """自定义UUID映射字典，键为玩家名，值为UUID字符串"""
    
    batch_processing: BatchSettings = field(default_factory=BatchSettings)
    """批量处理设置"""
    
    ui_settings: UISettings = field(default_factory=UISettings)
    """界面设置"""
    
    api_timeout: int = 10
    """API请求超时时间（秒），默认为10秒"""
    
    cleanup_patterns: List[str] = field(
        default_factory=lambda: ["*.log", "cache/", "logs/"]
    )
    """清理模式下要删除的文件/目录模式列表"""
