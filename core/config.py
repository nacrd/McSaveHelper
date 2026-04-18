"""配置文件管理模块，支持自定义UUID映射规则和版本检测"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

import nbtlib


class MCConfig:
    """Minecraft配置管理类"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path.home() / ".mc_migrator" / "config.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        default_config = {
            "version_detection": True,
            "custom_uuid_mappings": {},
            "batch_processing": {
                "max_concurrent": 2,
                "preserve_structure": True
            },
            "ui_settings": {
                "theme": "dark",
                "auto_clear_log": True
            }
        }
        
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    # 合并配置，保留用户设置
                    return {**default_config, **user_config}
            except Exception:
                return default_config
        return default_config
    
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
                version_mapping = {
                    404: "1.13.2", 402: "1.13.1", 401: "1.13",
                    393: "1.13", 340: "1.12.2", 338: "1.12.1", 335: "1.12",
                    316: "1.11.2", 315: "1.11", 210: "1.10.2", 205: "1.9.4",
                    184: "1.9.2", 176: "1.9", 169: "1.8.9", 163: "1.8.3",
                    127: "1.7.10", 124: "1.7.9", 95: "1.7.2", 78: "1.6.4",
                    77: "1.6.3", 74: "1.6.2", 73: "1.6.1", 61: "1.5.2",
                    60: "1.5.1", 51: "1.5", 47: "1.4.7", 39: "1.3.2",
                    29: "1.2.5", 13: "1.1", 8: "1.0.1", 6: "1.0.0"
                }
                
                if version_id in version_mapping:
                    return version_mapping[version_id]
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


# 全局配置实例
config_manager = MCConfig()