"""配置服务 —— 统一管理持久化配置和运行时迁移参数"""
import json
import shutil
import threading
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any, Optional

from app.models.config import ApplicationSettings, MigrationConfig
from core.constants import MinecraftConstants
from core.io_atomic import atomic_write_text
from core.logger import logger


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

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._config_dir: Path = config_dir or (Path.home() / ".mcsavehelper")
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config: Dict[str, Any] = {}
        self._migration: MigrationConfig = MigrationConfig()
        self._lock = threading.Lock()
        self._load()

    # ─── 持久化配置 ────────────────────────────────

    def _load(self) -> None:
        """加载配置文件"""
        config_path = self._config_dir / self.CONFIG_FILENAME
        defaults = self._defaults()
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    user = json.load(f)
                if not isinstance(user, dict):
                    raise ValueError("配置文件根节点必须是对象")
                merged = self._merge(defaults, user)
                self._config = merged
            except json.JSONDecodeError as e:
                self._backup_invalid_config(config_path)
                logger.warning(
                    f"配置文件格式无效，已恢复默认配置: {e}",
                    module="ConfigService")
                self._config = defaults
            except OSError as e:
                logger.warning(
                    f"读取配置文件失败，已恢复默认配置: {e}",
                    module="ConfigService")
                self._config = defaults
            except ValueError as e:
                self._backup_invalid_config(config_path)
                logger.warning(f"配置内容无效，已恢复默认配置: {e}", module="ConfigService")
                self._config = defaults
        else:
            self._config = defaults
        self._auto_fix()

    @staticmethod
    def _backup_invalid_config(config_path: Path) -> None:
        """备份无法解析的配置文件"""
        backup_path = config_path.with_suffix(f"{config_path.suffix}.bak")
        try:
            shutil.copy2(config_path, backup_path)
        except OSError as e:
            logger.warning(f"备份无效配置文件失败: {e}", module="ConfigService")

    def save(self) -> None:
        """保存配置到磁盘（线程安全）"""
        config_path = self._config_dir / self.CONFIG_FILENAME
        with self._lock:
            content = json.dumps(self._config, indent=2, ensure_ascii=False)
            atomic_write_text(config_path, content)

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
            "batch_processing": {
                "max_concurrent": 2,
                "preserve_structure": True},
            "ui_settings": {
                "theme": "dark",
                "auto_clear_log": True,
                "language": "zh_CN",
                "sidebar_mode": "auto",
                "show_log_panel": True,
                "enable_performance_monitor": False,
                "performance_print_interval": 60},
            "api_timeout": 10,
            "recent_saves": [],
            "cleanup_patterns": [
                "*.log",
                "cache/",
                "logs/"],
            "minecraft_dir": "",
            "auto_import_mc_lang": True,
        }

    @staticmethod
    def _merge(
        defaults: Dict[str, Any],
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        """递归合并默认配置与用户配置。

        仅接受与默认值同类型的用户字段；嵌套 dict 递归合并。

        Args:
            defaults: 默认配置字典。
            user: 用户配置字典。

        Returns:
            Dict[str, Any]: 合并后的新字典（不修改入参）。
        """
        merged = deepcopy(defaults)
        for key, default_value in defaults.items():
            if key not in user:
                continue
            value = user[key]
            if isinstance(default_value, dict):
                if isinstance(value, dict):
                    merged[key] = ConfigService._merge(default_value, value)
            elif type(value) is type(default_value):
                merged[key] = deepcopy(value)
        return merged

    def _auto_fix(self) -> None:
        """自动修复缺失或类型错误的配置字段。

        用默认值补齐缺失键；嵌套 dict 中类型不匹配的子键也会被替换。
        """
        defaults = self._defaults()
        for key, default_val in defaults.items():
            if key not in self._config:
                self._config[key] = default_val
                continue
            if not (
                isinstance(default_val, dict)
                and isinstance(self._config[key], dict)
            ):
                continue
            for sub_key, sub_default in default_val.items():
                current = self._config[key]
                if sub_key not in current or type(
                    current[sub_key]
                ) is not type(sub_default):
                    current[sub_key] = sub_default

    # ─── 快捷访问 ──────────────────────────────────

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
        return self._config.get(
            "batch_processing", {}).get(
            "max_concurrent", 2)

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
        with self._lock:
            return deepcopy(self._config.get("ui_settings", {}))

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
        with self._lock:
            return list(self._config.get("cleanup_patterns", []))

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
        with self._lock:
            return deepcopy(self._config.get("batch_processing", {}))

    def get_config_dict(self) -> Dict[str, Any]:
        """获取完整配置字典（用于视图展示）

        Returns:
            Dict[str, Any]: 完整配置字典的副本
        """
        with self._lock:
            return deepcopy(self._config)

    def get_recent_saves(self) -> list[Dict[str, str]]:
        """返回最近存档列表的隔离副本。"""
        with self._lock:
            raw_saves = self._config.get("recent_saves", [])
            if not isinstance(raw_saves, list):
                return []
            return [
                {
                    "path": str(item.get("path", "")),
                    "name": str(item.get("name", "")),
                }
                for item in raw_saves
                if isinstance(item, dict) and item.get("path")
            ]

    def set_recent_saves(self, saves: list[Dict[str, str]]) -> None:
        """替换并持久化最近存档列表。"""
        with self._lock:
            self._config["recent_saves"] = deepcopy(saves)
        self.save()

    def get_settings(self) -> ApplicationSettings:
        """返回设置页可安全消费的不可变快照。"""
        with self._lock:
            ui = self._config.get("ui_settings", {})
            batch = self._config.get("batch_processing", {})
            patterns = self._config.get("cleanup_patterns", [])
            return ApplicationSettings(
                version_detection=bool(
                    self._config.get("version_detection", True)
                ),
                api_timeout=int(self._config.get("api_timeout", 10)),
                theme=str(ui.get("theme", "dark")),
                language=str(ui.get("language", "zh_CN")),
                sidebar_mode=str(ui.get("sidebar_mode", "auto")),
                auto_clear_log=bool(ui.get("auto_clear_log", True)),
                show_log_panel=bool(ui.get("show_log_panel", True)),
                enable_performance_monitor=bool(
                    ui.get("enable_performance_monitor", False)
                ),
                performance_print_interval=int(
                    ui.get("performance_print_interval", 60)
                ),
                max_concurrent=int(batch.get("max_concurrent", 2)),
                preserve_structure=bool(
                    batch.get("preserve_structure", True)
                ),
                cleanup_patterns=tuple(str(item) for item in patterns),
                minecraft_dir=str(self._config.get("minecraft_dir", "") or ""),
                auto_import_mc_lang=bool(
                    self._config.get("auto_import_mc_lang", True)
                ),
            )

    def update_settings(self, settings: ApplicationSettings) -> None:
        """原子更新设置页负责的配置并持久化。"""
        with self._lock:
            self._config["version_detection"] = settings.version_detection
            self._config["api_timeout"] = settings.api_timeout
            self._config["minecraft_dir"] = str(settings.minecraft_dir or "")
            self._config["auto_import_mc_lang"] = bool(
                settings.auto_import_mc_lang
            )

            ui = dict(self._config.get("ui_settings", {}))
            ui.update({
                "theme": settings.theme,
                "language": settings.language,
                "sidebar_mode": settings.sidebar_mode,
                "auto_clear_log": settings.auto_clear_log,
                "show_log_panel": settings.show_log_panel,
                "enable_performance_monitor": (
                    settings.enable_performance_monitor
                ),
                "performance_print_interval": (
                    settings.performance_print_interval
                ),
            })
            self._config["ui_settings"] = ui

            batch = dict(self._config.get("batch_processing", {}))
            batch.update({
                "max_concurrent": settings.max_concurrent,
                "preserve_structure": settings.preserve_structure,
            })
            self._config["batch_processing"] = batch
            self._config["cleanup_patterns"] = list(
                settings.cleanup_patterns
            )
            self._migration.version_detection = settings.version_detection
        self.save()

    def get_minecraft_dir(self) -> str:
        """返回配置的 Minecraft 数据目录。

        Returns:
            str: 已配置路径；未设置时为空字符串。
        """
        with self._lock:
            return str(self._config.get("minecraft_dir", "") or "").strip()

    def set_minecraft_dir(self, path: str) -> None:
        """持久化自定义 Minecraft 数据目录。

        Args:
            path: 目录路径；空白值会保存为空字符串表示自动推断。
        """
        with self._lock:
            self._config["minecraft_dir"] = str(path or "").strip()
        self.save()

    def is_auto_import_mc_lang_enabled(self) -> bool:
        """是否在选择存档后自动导入 Minecraft 原版语言。

        Returns:
            bool: 配置开启时为 True；缺省键视为开启。
        """
        with self._lock:
            return bool(self._config.get("auto_import_mc_lang", True))

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
            self._migration.version_detection = True
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
            data = nbt_data.get("Data", {}) or {}

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
