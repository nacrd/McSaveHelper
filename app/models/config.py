"""配置数据模型"""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class BatchSettings:
    """批量处理设置"""
    max_concurrent: int = 2
    preserve_structure: bool = True


@dataclass
class UISettings:
    """界面设置"""
    theme: str = "dark"
    auto_clear_log: bool = True
    language: str = "zh_CN"


@dataclass
class MigrationConfig:
    """迁移任务配置（运行时状态）"""
    mode: str = "fast"          # "fast" | "full"
    src_path: str = ""
    dest_path: str = ""
    world_name: str = "world"
    offline_mode: bool = False
    clean_mode: bool = True
    pure_clean_mode: bool = False
    version_detection: bool = True
    batch_mode: bool = False
    batch_dir_path: str = ""
    manual_names: str = ""       # 逗号分隔的玩家名
    query_name: str = ""


@dataclass
class AppConfig:
    """应用完整配置（持久化到 ~/.mcsavehelper/config.json）"""
    version: int = 2
    version_detection: bool = True
    use_custom_mapping: bool = False
    custom_uuid_mappings: Dict[str, str] = field(default_factory=dict)
    batch_processing: BatchSettings = field(default_factory=BatchSettings)
    ui_settings: UISettings = field(default_factory=UISettings)
    api_timeout: int = 10
    cleanup_patterns: List[str] = field(
        default_factory=lambda: ["*.log", "cache/", "logs/"]
    )
