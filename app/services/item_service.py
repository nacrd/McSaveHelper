"""物品服务 - 处理物品名称映射和属性解析（门面模式）"""
from pathlib import Path
from typing import Any, Dict, Optional

from .item.constants import _ENCHANTMENT_NAMES, _MAX_DURABILITY, _VANILLA_ITEM_NAMES
from .item.models import ItemInfo
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
from .item.parser import format_item_tooltip as _format_tooltip, parse_item as _parse_item


class ItemService:
    """物品服务 - 处理物品名称映射和属性解析"""

    def __init__(self) -> None:
        self._name_map: Dict[str, str] = _VANILLA_ITEM_NAMES.copy()
        self._enchantment_names: Dict[str, str] = _ENCHANTMENT_NAMES.copy()
        self._max_durability: Dict[str, Optional[int]] = _MAX_DURABILITY.copy()
        self._custom_slots: Dict[int, str] = {}

    def load_language_file(self, path: Path, namespace: str = "minecraft") -> int:
        """加载 Minecraft 语言文件（JSON 格式）"""
        return _load_lang(path, self._name_map, self._enchantment_names, namespace)

    def load_custom_mapping_file(self, path: Path) -> int:
        """加载外部 JSON 物品映射"""
        return _load_custom(path, self._name_map, self._enchantment_names)

    def save_custom_mapping_file(self, path: Path) -> None:
        """导出当前非内置物品/附魔映射"""
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
        """从客户端或模组 JAR 中提取指定语言文件并加载。"""
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
        """Extract language files from a jar and return a detailed result."""
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
    ) -> LanguageImportResult:
        """Load language from the installed Minecraft client jar if present."""
        return _extract_local_mc(
            self._name_map,
            self._enchantment_names,
            locale=locale,
            jar_path=jar_path,
        )

    @staticmethod
    def normalize_locale(locale: str) -> str:
        return _normalize_locale(locale)

    @staticmethod
    def locale_fallbacks(locale: str) -> tuple[str, ...]:
        return _locale_fallbacks(locale)

    def set_item_mapping(self, item_id: str, display_name: str) -> None:
        if item_id and display_name:
            self._name_map[item_id.strip()] = display_name.strip()

    def delete_item_mapping(self, item_id: str) -> bool:
        """删除自定义物品名称映射"""
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
        return {
            k: v
            for k, v in self._name_map.items()
            if _VANILLA_ITEM_NAMES.get(k) != v
        }

    def get_item_name(self, item_id: str) -> str:
        if item_id in self._name_map:
            return self._name_map[item_id]
        if ":" in item_id:
            _, local_id = item_id.split(":", 1)
            return local_id.replace("_", " ").title()
        return item_id

    def get_enchantment_name(self, ench_id: str) -> str:
        if ench_id in self._enchantment_names:
            return self._enchantment_names[ench_id]
        if ":" in ench_id:
            _, local_id = ench_id.split(":", 1)
            return local_id.replace("_", " ").title()
        return ench_id

    def parse_item(self, item_data: Dict[str, Any]) -> ItemInfo:
        """解析物品数据，提取完整信息"""
        return _parse_item(item_data, self.get_item_name, self.get_enchantment_name)

    def register_custom_slot(self, slot_id: int, name: str) -> None:
        self._custom_slots[slot_id] = name

    def get_custom_slots(self) -> Dict[int, str]:
        return self._custom_slots.copy()

    def format_item_tooltip(self, item_info: ItemInfo) -> str:
        return _format_tooltip(item_info)
