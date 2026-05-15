"""配置服务 —— 统一管理持久化配置和运行时迁移参数"""
import json
from pathlib import Path
from typing import Dict, Any, Optional

from app.models.config import AppConfig, BatchSettings, UISettings, MigrationConfig


class ConfigService:
    """配置管理服务

    职责：
      - 从 ~/.mcsavehelper/config.json 加载/保存持久化配置
      - 提供运行时迁移参数（MigrationConfig）
      - 自动修复无效配置字段
    """

    CONFIG_FILENAME = "config.json"

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._config_dir = config_dir or (Path.home() / ".mcsavehelper")
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config: Dict[str, Any] = {}
        self._migration: MigrationConfig = MigrationConfig()
        self._load()

    # ─── 持久化配置 ───────────────────────────────

    def _load(self) -> None:
        config_path = self._config_dir / self.CONFIG_FILENAME
        defaults = self._defaults()
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    user = json.load(f)
                merged = self._merge(defaults, user)
                self._config = merged
            except Exception:
                self._config = defaults
        else:
            self._config = defaults
        self._auto_fix()

    def save(self) -> None:
        """保存配置到磁盘"""
        config_path = self._config_dir / self.CONFIG_FILENAME
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _defaults() -> Dict[str, Any]:
        return {
            "version": 2,
            "version_detection": True,
            "use_custom_mapping": False,
            "custom_uuid_mappings": {},
            "batch_processing": {"max_concurrent": 2, "preserve_structure": True},
            "ui_settings": {"theme": "dark", "auto_clear_log": True, "language": "zh_CN"},
            "api_timeout": 10,
            "cleanup_patterns": ["*.log", "cache/", "logs/"],
        }

    @staticmethod
    def _merge(defaults: Dict, user: Dict) -> Dict:
        merged = defaults.copy()
        for key, value in user.items():
            if key in merged:
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
        return merged

    def _auto_fix(self) -> None:
        """自动修复无效配置字段，用默认值替换"""
        defaults = self._defaults()
        for key, default_val in defaults.items():
            if key not in self._config:
                self._config[key] = default_val
            elif isinstance(default_val, dict) and isinstance(self._config[key], dict):
                for sub_key, sub_default in default_val.items():
                    if sub_key not in self._config[key] or type(self._config[key][sub_key]) is not type(sub_default):
                        self._config[key][sub_key] = sub_default

    # ─── 快捷访问 ──────────────────────────────────

    @property
    def version_detection(self) -> bool:
        return self._config.get("version_detection", True)

    @property
    def use_custom_mapping(self) -> bool:
        return self._config.get("use_custom_mapping", False)

    @use_custom_mapping.setter
    def use_custom_mapping(self, value: bool) -> None:
        self._config["use_custom_mapping"] = value

    @property
    def custom_uuid_mappings(self) -> Dict[str, str]:
        return self._config.get("custom_uuid_mappings", {})

    @custom_uuid_mappings.setter
    def custom_uuid_mappings(self, value: Dict[str, str]) -> None:
        self._config["custom_uuid_mappings"] = value

    @property
    def max_concurrent(self) -> int:
        return self._config.get("batch_processing", {}).get("max_concurrent", 2)

    @property
    def api_timeout(self) -> int:
        return self._config.get("api_timeout", 10)

    @property
    def ui_settings(self) -> dict:
        return self._config.get("ui_settings", {})

    @property
    def language(self) -> str:
        return self.ui_settings.get("language", "zh_CN")

    @property
    def theme(self) -> str:
        return self.ui_settings.get("theme", "dark")

    @property
    def cleanup_patterns(self) -> list:
        return self._config.get("cleanup_patterns", [])

    @cleanup_patterns.setter
    def cleanup_patterns(self, value: list) -> None:
        self._config["cleanup_patterns"] = value

    @property
    def batch_processing(self) -> dict:
        return self._config.get("batch_processing", {})

    def get_config_dict(self) -> Dict[str, Any]:
        """获取完整配置字典（用于视图展示）"""
        return dict(self._config)

    # ─── 运行时迁移配置 ───────────────────────────

    @property
    def migration(self) -> MigrationConfig:
        return self._migration

    def reset_config(self) -> None:
        """重置所有配置为默认值"""
        self._config = self._defaults()
        self.save()
