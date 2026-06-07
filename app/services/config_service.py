"""配置服务 —— 统一管理持久化配置和运行时迁移参数"""
import json
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from app.models.config import AppConfig, BatchSettings, UISettings, MigrationConfig
from core.constants import MinecraftConstants


class ConfigService:
    """配置管理服务

    职责：
      - 从 ~/.mcsavehelper/config.json 加载/保存持久化配置
      - 提供运行时迁移参数（MigrationConfig）
      - 自动修复无效配置字段
      - 提供 Minecraft 版本检测功能
      - 提供自定义 UUID 映射管理
    """

    CONFIG_FILENAME: str = "config.json"
    """配置文件名称"""
    
    _instance: Optional['ConfigService'] = None
    """单例实例"""

    def __new__(cls, config_dir: Optional[Path] = None) -> 'ConfigService':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        if getattr(self, '_initialized', False):
            return
        self._config_dir: Path = config_dir or (Path.home() / ".mcsavehelper")
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config: Dict[str, Any] = {}
        self._migration: MigrationConfig = MigrationConfig()
        self._lock = threading.Lock()
        self._load()
        self._initialized: bool = True

    # ─── 持久化配置 ────────────────────────────────

    def _load(self) -> None:
        """加载配置文件"""
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
        """保存配置到磁盘（线程安全）"""
        config_path = self._config_dir / self.CONFIG_FILENAME
        with self._lock:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _defaults() -> Dict[str, Any]:
        """获取默认配置字典
        
        Returns:
            Dict[str, Any]: 默认配置字典
        """
        return {
            "version": 2,
            "version_detection": True,
            "use_custom_mapping": False,
            "custom_uuid_mappings": {},
            "batch_processing": {"max_concurrent": 2, "preserve_structure": True},
            "ui_settings": {"theme": "dark", "auto_clear_log": True, "language": "zh_CN", "show_log_panel": True},
            "api_timeout": 10,
            "cleanup_patterns": ["*.log", "cache/", "logs/"],
        }

    @staticmethod
    def _merge(defaults: Dict, user: Dict) -> Dict:
        """合并默认配置和用户配置
        
        Args:
            defaults: 默认配置字典
            user: 用户配置字典
            
        Returns:
            Dict: 合并后的配置字典
        """
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
    def config(self) -> Dict[str, Any]:
        """获取完整配置字典
        
        Returns:
            Dict[str, Any]: 完整配置字典
        """
        return self._config

    @property
    def version_detection(self) -> bool:
        """是否启用版本检测
        
        Returns:
            bool: 是否启用版本检测
        """
        return self._config.get("version_detection", True)

    @property
    def use_custom_mapping(self) -> bool:
        """是否使用自定义UUID映射
        
        Returns:
            bool: 是否使用自定义UUID映射
        """
        return self._config.get("use_custom_mapping", False)

    @use_custom_mapping.setter
    def use_custom_mapping(self, value: bool) -> None:
        with self._lock:
            self._config["use_custom_mapping"] = value

    @property
    def custom_uuid_mappings(self) -> Dict[str, str]:
        """获取自定义UUID映射字典
        
        Returns:
            Dict[str, str]: 自定义UUID映射字典
        """
        with self._lock:
            return dict(self._config.get("custom_uuid_mappings", {}))

    @custom_uuid_mappings.setter
    def custom_uuid_mappings(self, value: Dict[str, str]) -> None:
        with self._lock:
            self._config["custom_uuid_mappings"] = value

    def get_custom_uuid_mapping(self, player_name: str) -> Optional[str]:
        """获取自定义UUID映射
        
        Args:
            player_name: 玩家名称
            
        Returns:
            Optional[str]: 对应的UUID，如果不存在则返回None
        """
        return self.custom_uuid_mappings.get(player_name)

    def set_custom_uuid_mapping(self, player_name: str, uuid: str) -> None:
        """设置自定义UUID映射
        
        Args:
            player_name: 玩家名称
            uuid: 玩家UUID字符串
        """
        with self._lock:
            mappings = self._config.get("custom_uuid_mappings", {})
            mappings[player_name] = uuid
            self._config["custom_uuid_mappings"] = mappings
        self.save()

    def remove_custom_uuid_mapping(self, player_name: str) -> None:
        """移除自定义UUID映射
        
        Args:
            player_name: 要移除的玩家名称
        """
        with self._lock:
            mappings = self._config.get("custom_uuid_mappings", {})
            if player_name in mappings:
                del mappings[player_name]
                self._config["custom_uuid_mappings"] = mappings
        self.save()

    @property
    def max_concurrent(self) -> int:
        """最大并发处理数量
        
        Returns:
            int: 最大并发处理数量
        """
        return self._config.get("batch_processing", {}).get("max_concurrent", 2)

    @property
    def api_timeout(self) -> int:
        """API请求超时时间（秒）
        
        Returns:
            int: 超时时间（秒）
        """
        return self._config.get("api_timeout", 10)

    @property
    def ui_settings(self) -> dict:
        """界面设置
        
        Returns:
            dict: 界面设置字典
        """
        return self._config.get("ui_settings", {})

    @property
    def language(self) -> str:
        """当前界面语言
        
        Returns:
            str: 语言代码
        """
        return self.ui_settings.get("language", "zh_CN")

    @language.setter
    def language(self, value: str) -> None:
        with self._lock:
            ui_settings = self._config.get("ui_settings", {})
            ui_settings["language"] = value
            self._config["ui_settings"] = ui_settings

    @property
    def theme(self) -> str:
        """当前界面主题
        
        Returns:
            str: 主题名称
        """
        return self.ui_settings.get("theme", "dark")

    @property
    def cleanup_patterns(self) -> list:
        """清理模式下的文件/目录模式列表
        
        Returns:
            list: 模式列表
        """
        return self._config.get("cleanup_patterns", [])

    @cleanup_patterns.setter
    def cleanup_patterns(self, value: list) -> None:
        with self._lock:
            self._config["cleanup_patterns"] = value

    @property
    def batch_processing(self) -> dict:
        """批量处理设置
        
        Returns:
            dict: 批量处理设置字典
        """
        return self._config.get("batch_processing", {})

    def get_config_dict(self) -> Dict[str, Any]:
        """获取完整配置字典（用于视图展示）
        
        Returns:
            Dict[str, Any]: 完整配置字典的副本
        """
        with self._lock:
            return dict(self._config)

    # ─── 运行时迁移配置 ────────────────────────────

    @property
    def migration(self) -> MigrationConfig:
        """运行时迁移配置
        
        Returns:
            MigrationConfig: 迁移配置对象
        """
        return self._migration

    def reset_config(self) -> None:
        """重置所有配置为默认值"""
        with self._lock:
            self._config = self._defaults()
        self.save()

    def update_batch_config(
        self,
        version_detection: Optional[bool] = None,
        max_concurrent: Optional[int] = None,
        custom_uuid_mappings: Optional[Dict[str, str]] = None,
        use_custom_mapping: Optional[bool] = None,
    ) -> None:
        """批量更新配置（线程安全）
        
        Args:
            version_detection: 版本检测开关
            max_concurrent: 最大并发数
            custom_uuid_mappings: 自定义UUID映射
            use_custom_mapping: 是否使用自定义映射
        """
        with self._lock:
            if version_detection is not None:
                self._config["version_detection"] = version_detection
            if max_concurrent is not None:
                batch_processing = self._config.get("batch_processing", {})
                batch_processing["max_concurrent"] = max_concurrent
                self._config["batch_processing"] = batch_processing
            if custom_uuid_mappings is not None:
                self._config["custom_uuid_mappings"] = custom_uuid_mappings
            if use_custom_mapping is not None:
                self._config["use_custom_mapping"] = use_custom_mapping
        self.save()

    # ─── Minecraft 版本检测 ────────────────────────────

    def detect_minecraft_version(self, world_path: Path) -> Optional[str]:
        """检测Minecraft版本
        
        Args:
            world_path: 世界存档目录路径
            
        Returns:
            Optional[str]: 检测到的版本号或名称，如果检测失败则返回None
        """
        if not self.version_detection:
            return None

        try:
            import nbtlib
            level_dat = world_path / "level.dat"
            if not level_dat.exists():
                return None

            nbt_data = nbtlib.load(str(level_dat))
            data = nbt_data.get("Data", {})

            # 从level.dat获取版本信息
            version_data = data.get("Version", {})
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
