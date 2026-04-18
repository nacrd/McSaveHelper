"""配置文件管理模块，支持自定义UUID映射规则和版本检测"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass, field
from enum import Enum

import nbtlib
from .constants import MinecraftConstants


class ConfigSchema:
    """配置schema定义"""
    
    # 基础配置schema
    BASE_SCHEMA = {
        "version": {"type": int, "default": 1, "min": 1},
        "version_detection": {"type": bool, "default": True},
        "custom_uuid_mappings": {"type": dict, "default": {}},
        "batch_processing": {
            "type": dict,
            "schema": {
                "max_concurrent": {"type": int, "default": 2, "min": 1, "max": 16},
                "preserve_structure": {"type": bool, "default": True}
            }
        },
        "ui_settings": {
            "type": dict,
            "schema": {
                "theme": {"type": str, "default": "dark", "choices": ["dark", "light"]},
                "auto_clear_log": {"type": bool, "default": True}
            }
        },
        "api_timeout": {"type": int, "default": 10, "min": 1, "max": 60},
        "cleanup_patterns": {"type": list, "default": ["*.log", "cache/", "logs/"]}
    }
    
    # 版本1到2的迁移规则
    MIGRATION_V1_TO_V2 = {
        "version": 2,
        "batch_processing": {
            "max_concurrent": 4,
            "preserve_structure": True
        },
        "api_timeout": 10,
        "cleanup_patterns": ["*.log", "cache/", "logs/"]
    }


@dataclass
class ConfigField:
    """配置字段定义"""
    name: str
    field_type: type
    default: Any = None
    required: bool = False
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    choices: Optional[List[Any]] = None
    description: str = ""
    
    def validate(self, value: Any) -> bool:
        """验证字段值"""
        if value is None and self.required:
            return False
        
        if value is not None:
            # 类型检查
            if not isinstance(value, self.field_type):
                return False
            
            # 数值范围检查
            if self.field_type in [int, float] and self.min_value is not None and value < self.min_value:
                return False
            if self.field_type in [int, float] and self.max_value is not None and value > self.max_value:
                return False
            
            # 枚举值检查
            if self.choices and value not in self.choices:
                return False
        
        return True


class EnhancedConfig:
    """增强的Minecraft配置管理类"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path.home() / ".mc_migrator" / "config.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema = ConfigSchema.BASE_SCHEMA
        self.config = self._load_with_defaults()
        self._validate_config()
    
    def _load_with_defaults(self) -> Dict[str, Any]:
        """加载配置并合并默认值"""
        default_config = self._get_default_config()
        
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    # 应用版本迁移
                    migrated_config = self._migrate_version(user_config)
                    # 合并配置，保留用户设置
                    return self._merge_configs(default_config, migrated_config)
            except Exception:
                return default_config
        return default_config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        default_config = {}
        for key, field_def in self.schema.items():
            if key == "version":
                default_config[key] = field_def["default"]
            elif "schema" in field_def:
                # 嵌套配置
                default_config[key] = {}
                for sub_key, sub_field_def in field_def["schema"].items():
                    default_config[key][sub_key] = sub_field_def["default"]
            else:
                default_config[key] = field_def["default"]
        return default_config
    
    def _merge_configs(self, default_config: Dict[str, Any], user_config: Dict[str, Any]) -> Dict[str, Any]:
        """合并默认配置和用户配置"""
        merged = default_config.copy()
        
        for key, value in user_config.items():
            if key in self.schema:
                if "schema" in self.schema[key]:
                    # 嵌套配置
                    if key not in merged:
                        merged[key] = {}
                    if isinstance(value, dict):
                        for sub_key, sub_value in value.items():
                            if sub_key in self.schema[key]["schema"]:
                                merged[key][sub_key] = sub_value
                else:
                    merged[key] = value
        
        return merged
    
    def _validate_config(self) -> None:
        """验证配置"""
        if not self.validate():
            raise ValueError("配置验证失败")
    
    def validate(self) -> bool:
        """基于schema验证配置"""
        try:
            for key, field_def in self.schema.items():
                if key not in self.config:
                    return False
                
                value = self.config[key]
                
                if "schema" in field_def:
                    # 验证嵌套配置
                    if not isinstance(value, dict):
                        return False
                    
                    for sub_key, sub_field_def in field_def["schema"].items():
                        if sub_key not in value:
                            return False
                        
                        sub_value = value[sub_key]
                        if not self._validate_field(sub_field_def, sub_value):
                            return False
                else:
                    # 验证简单字段
                    if not self._validate_field(field_def, value):
                        return False
            
            return True
        except Exception:
            return False
    
    def _validate_field(self, field_def: Dict[str, Any], value: Any) -> bool:
        """验证单个字段"""
        field_type = field_def["type"]
        
        # 类型检查
        if not isinstance(value, field_type):
            return False
        
        # 数值范围检查
        if field_type in [int, float] and "min" in field_def and value < field_def["min"]:
            return False
        if field_type in [int, float] and "max" in field_def and value > field_def["max"]:
            return False
        
        # 枚举值检查
        if "choices" in field_def and value not in field_def["choices"]:
            return False
        
        return True
    
    def _migrate_version(self, old_config: Dict[str, Any]) -> Dict[str, Any]:
        """配置版本迁移"""
        current_version = old_config.get("version", 1)
        
        if current_version == 1:
            # 从版本1迁移到版本2
            migrated = old_config.copy()
            migrated.update(ConfigSchema.MIGRATION_V1_TO_V2)
            return migrated
        
        return old_config
    
    def save_config(self) -> None:
        """保存配置文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")
    
    def get_custom_uuid_mapping(self, player_name: str) -> Optional[str]:
        """获取自定义UUID映射"""
        return self.config["custom_uuid_mappings"].get(player_name)
    
    def set_custom_uuid_mapping(self, player_name: str, uuid: str) -> None:
        """设置自定义UUID映射"""
        self.config["custom_uuid_mappings"][player_name] = uuid
        self.save_config()
    
    def remove_custom_uuid_mapping(self, player_name: str) -> None:
        """移除自定义UUID映射"""
        if player_name in self.config["custom_uuid_mappings"]:
            del self.config["custom_uuid_mappings"][player_name]
            self.save_config()
    
    def detect_minecraft_version(self, world_path: Path) -> Optional[str]:
        """检测Minecraft版本"""
        if not self.config["version_detection"]:
            return None
        
        try:
            level_dat = world_path / "level.dat"
            if not level_dat.exists():
                return None
            
            nbt_data = nbtlib.load(str(level_dat))
            data = nbt_data.get("Data", {})
            
            # 从level.dat获取版本信息
            version_data = data.get("Version", {})  # type: ignore[union-attr]
            if version_data:
                version_id = version_data.get("Id", 0)
                version_name = version_data.get("Name", "")
                
                # 将版本ID转换为版本名称
                if version_id in MinecraftConstants.VERSION_MAP:
                    return MinecraftConstants.VERSION_MAP[version_id]
                elif version_name:
                    return str(version_name)
                else:
                    return f"未知版本 ({version_id})"
            
            # 尝试从其他文件检测版本
            stats_dir = world_path / "stats"
            if stats_dir.exists():
                # 通过统计文件格式推断版本
                stats_files = list(stats_dir.glob("*.json"))
                if stats_files:
                    return "1.12+"  # JSON格式统计文件从1.12开始
            
            return "未知版本"
            
        except Exception as e:
            return f"检测失败: {str(e)}"
    
    def get_api_timeout(self) -> int:
        """获取API超时时间"""
        return self.config["api_timeout"]
    
    def get_batch_processing_config(self) -> Dict[str, Any]:
        """获取批处理配置"""
        return self.config["batch_processing"]
    
    def get_ui_settings(self) -> Dict[str, Any]:
        """获取UI设置"""
        return self.config["ui_settings"]
    
    def get_cleanup_patterns(self) -> List[str]:
        """获取清理模式"""
        return self.config["cleanup_patterns"]


# 全局配置实例
config_manager = EnhancedConfig()