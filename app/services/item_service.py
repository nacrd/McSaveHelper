"""物品服务 - 处理物品名称映射和属性解析（门面模式）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .item.constants import (
    _ENCHANTMENT_NAMES,
    _MAX_DURABILITY,
    _VANILLA_ITEM_NAMES,
)
from .item.language_loader import (
    LanguageImportResult,
    extract_language_from_jar as _extract_jar,
    extract_language_from_local_minecraft as _extract_local_mc,
    load_custom_mapping as _load_custom,
    load_language_file as _load_lang,
    locale_fallbacks as _locale_fallbacks,
    normalize_locale as _normalize_locale,
    save_custom_mapping as _save_custom,
)
from .item.models import ItemInfo
from .item.parser import (
    format_item_tooltip as _format_tooltip,
    parse_item as _parse_item,
)


class ItemService:
    """物品服务门面：名称映射、语言导入与属性解析。

    内部委托 ``app.services.item`` 子模块；本类持有可变名称表状态，
    供 UI 与自动导入共享同一份映射。
    """

    def __init__(self) -> None:
        """用内置原版表初始化名称与耐久缓存。"""
        self._name_map: Dict[str, str] = _VANILLA_ITEM_NAMES.copy()
        self._enchantment_names: Dict[str, str] = _ENCHANTMENT_NAMES.copy()
        self._max_durability: Dict[str, Optional[int]] = _MAX_DURABILITY.copy()
        self._custom_slots: Dict[int, str] = {}

    def load_language_file(
        self,
        path: Path,
        namespace: str = "minecraft",
    ) -> int:
        """加载 Minecraft 语言 JSON 并合并到当前名称表。

        Args:
            path: 语言文件路径（``*.json``）。
            namespace: 默认命名空间前缀，用于无命名空间的键。

        Returns:
            int: 成功导入的条目数；文件无效时为 0。
        """
        return _load_lang(
            path,
            self._name_map,
            self._enchantment_names,
            namespace,
        )

    def load_custom_mapping_file(self, path: Path) -> int:
        """加载外部 JSON 物品/附魔映射。

        Args:
            path: 自定义映射文件路径。

        Returns:
            int: 成功导入的条目数；文件无效时为 0。
        """
        return _load_custom(path, self._name_map, self._enchantment_names)

    def save_custom_mapping_file(self, path: Path) -> None:
        """导出当前非内置物品/附魔映射。

        Args:
            path: 目标 JSON 路径。

        Raises:
            OSError: 写入失败时由底层 ``path.write_text`` 抛出。
        """
        _save_custom(
            path,
            self._name_map,
            self._enchantment_names,
            _VANILLA_ITEM_NAMES,
            _ENCHANTMENT_NAMES,
        )

    def extract_language_from_jar(
        self,
        jar_path: Path,
        locale: str = "zh_cn",
    ) -> int:
        """从客户端或模组 JAR 提取语言并加载。

        Args:
            jar_path: JAR 文件路径。
            locale: 语言代码（UI 或 Minecraft 形式均可）。

        Returns:
            int: 导入条目数。
        """
        result = _extract_jar(
            jar_path,
            self._name_map,
            self._enchantment_names,
            locale,
        )
        return result.count

    def extract_language_from_jar_detailed(
        self,
        jar_path: Path,
        locale: str = "zh_cn",
    ) -> LanguageImportResult:
        """从 JAR 提取语言并返回详细结果。

        Args:
            jar_path: JAR 文件路径。
            locale: 语言代码。

        Returns:
            LanguageImportResult: 计数、来源路径与实际使用的 locale。
        """
        return _extract_jar(
            jar_path,
            self._name_map,
            self._enchantment_names,
            locale,
        )

    def import_language_from_local_minecraft(
        self,
        locale: str = "zh_cn",
        *,
        jar_path: Optional[Path] = None,
        minecraft_dir: Optional[Path] = None,
        start_path: Optional[Path] = None,
        configured_dir: Optional[Path] = None,
    ) -> LanguageImportResult:
        """从本地 Minecraft 安装导入语言。

        现代客户端（1.8+）优先解析 ``assets/indexes`` + ``assets/objects``；
        旧版 JAR 内嵌 ``.lang`` 作为回退。数据目录可配置、由存档推断，
        或由 ``versions/<id>/<id>.jar`` 推断。

        Args:
            locale: 首选语言代码。
            jar_path: 可选客户端/模组 JAR。
            minecraft_dir: 可选 ``.minecraft`` 目录（与 ``configured_dir`` 同义兼容）。
            start_path: 用于向上推断 ``.minecraft`` 的起点（通常为存档路径）。
            configured_dir: 设置页配置的 Minecraft 数据根。

        Returns:
            LanguageImportResult: 导入结果；未找到文件时 ``count`` 为 0。
        """
        return _extract_local_mc(
            self._name_map,
            self._enchantment_names,
            locale=locale,
            jar_path=jar_path,
            minecraft_dir=minecraft_dir,
            start_path=start_path,
            configured_dir=configured_dir,
        )

    @staticmethod
    def normalize_locale(locale: str) -> str:
        """将 UI/区域代码规范为 Minecraft lang 词干。

        Args:
            locale: 如 ``zh_CN``、``en-US``、``zh``。

        Returns:
            str: 如 ``zh_cn``、``en_us``。
        """
        return _normalize_locale(locale)

    @staticmethod
    def locale_fallbacks(locale: str) -> tuple[str, ...]:
        """返回语言回退链（首选 locale，必要时追加 ``en_us``）。

        Args:
            locale: 首选语言代码。

        Returns:
            tuple[str, ...]: 有序回退序列。
        """
        return _locale_fallbacks(locale)

    def set_item_mapping(self, item_id: str, display_name: str) -> None:
        """设置或覆盖物品显示名。

        Args:
            item_id: 物品 ID（建议含命名空间，如 ``minecraft:stone``）。
            display_name: 显示名称；空字符串会被忽略。
        """
        if item_id and display_name:
            self._name_map[item_id.strip()] = display_name.strip()

    def delete_item_mapping(self, item_id: str) -> bool:
        """删除自定义物品名称映射。

        若该 ID 存在原版默认名，则恢复为原版名；否则从映射表移除。

        Args:
            item_id: 物品 ID。

        Returns:
            bool: 是否发生了有效变更。
        """
        item_id = item_id.strip()
        if not item_id or item_id not in self._name_map:
            return False
        vanilla_name = _VANILLA_ITEM_NAMES.get(item_id)
        if vanilla_name == self._name_map.get(item_id):
            return False
        if vanilla_name is None:
            del self._name_map[item_id]
        else:
            self._name_map[item_id] = vanilla_name
        return True

    def get_custom_item_mappings(self) -> Dict[str, str]:
        """返回与内置原版表不同的自定义物品映射副本。

        Returns:
            Dict[str, str]: 自定义物品 ID → 显示名。
        """
        return {
            key: value
            for key, value in self._name_map.items()
            if _VANILLA_ITEM_NAMES.get(key) != value
        }

    def get_item_name(self, item_id: str) -> str:
        """解析物品显示名。

        Args:
            item_id: 物品 ID。

        Returns:
            str: 映射表中的名称；未命中时用本地 ID 标题化回退。
        """
        if item_id in self._name_map:
            return self._name_map[item_id]
        if ":" in item_id:
            _, local_id = item_id.split(":", 1)
            return local_id.replace("_", " ").title()
        return item_id

    def get_enchantment_name(self, ench_id: str) -> str:
        """解析附魔显示名。

        Args:
            ench_id: 附魔 ID。

        Returns:
            str: 映射表中的名称；未命中时用本地 ID 标题化回退。
        """
        if ench_id in self._enchantment_names:
            return self._enchantment_names[ench_id]
        if ":" in ench_id:
            _, local_id = ench_id.split(":", 1)
            return local_id.replace("_", " ").title()
        return ench_id

    def parse_item(self, item_data: Dict[str, Any]) -> ItemInfo:
        """解析物品数据，提取完整信息。

        Args:
            item_data: 原始物品字典（来自 NBT/JSON 投影）。

        Returns:
            ItemInfo: 结构化物品信息。
        """
        return _parse_item(
            item_data,
            self.get_item_name,
            self.get_enchantment_name,
        )

    def register_custom_slot(self, slot_id: int, name: str) -> None:
        """注册自定义槽位显示名。

        Args:
            slot_id: 槽位编号。
            name: 显示名称。
        """
        self._custom_slots[slot_id] = name

    def get_custom_slots(self) -> Dict[int, str]:
        """返回自定义槽位映射副本。

        Returns:
            Dict[int, str]: 槽位 ID → 名称。
        """
        return self._custom_slots.copy()

    def format_item_tooltip(self, item_info: ItemInfo) -> str:
        """格式化物品悬停提示文本。

        Args:
            item_info: 已解析的物品信息。

        Returns:
            str: 多行提示字符串。
        """
        return _format_tooltip(item_info)
