"""国际化翻译模块

提供多语言支持，使用 JSON 文件存储翻译文本。
支持动态语言切换和热重载。
"""

import json
import os
import sys
from pathlib import Path
from typing import Callable, Dict, Any, Optional, Set, List, Tuple
from enum import Enum

try:
    from enum import StrEnum
except ImportError:
    try:
        from typing_extensions import StrEnum
    except ImportError:
        class _StrEnum(str, Enum):
            """自定义字符串枚举，兼容 Python <3.11"""
            pass
        StrEnum = _StrEnum


class Language(StrEnum):
    """支持的语言枚举

    包含预定义语言和动态创建的语言。
    """
    ZH_CN = "zh_CN"
    EN_US = "en_US"

    @classmethod
    def _missing_(cls, value: str) -> 'Language':
        """为未知语言代码动态创建枚举成员

        Args:
            value: 语言代码

        Returns:
            动态创建的枚举成员
        """
        member = str.__new__(cls, value)
        member._value_ = value
        name = value.upper().replace('-', '_').replace(' ', '_')
        member._name_ = name
        cls._value2member_map_[value] = member
        return member


class TranslationManager:
    """翻译管理器

    负责加载翻译文件、管理当前语言设置、提供翻译功能。
    """

    def __init__(
        self,
        translations_dir: Optional[Path] = None,
        language_loader: Optional[Callable[[], str]] = None,
        language_saver: Optional[Callable[[str], None]] = None,
    ) -> None:
        """初始化翻译管理器

        Args:
            translations_dir: 翻译文件目录
            language_loader: 当前语言配置读取函数
            language_saver: 当前语言配置保存函数
        """
        if translations_dir is None:
            if hasattr(sys, '_MEIPASS'):
                base_dir = Path(sys._MEIPASS)
            else:
                base_dir = Path(__file__).parent.parent
            self.translations_dir: Path = base_dir / "translations"
        else:
            self.translations_dir: Path = Path(translations_dir)

        if not self.translations_dir.exists():
            self.translations_dir.mkdir(parents=True, exist_ok=True)

        self._current_language: Language = Language.ZH_CN
        self._translations: Dict[str, Any] = {}
        self._loaded_files: Set[str] = set()
        self._available_languages: List[str] = []
        self._language_display_map: Dict[str, str] = {}
        self._config_loaded: bool = False
        self._language_loader = language_loader
        self._language_saver = language_saver

        self._available_languages = self._scan_available_languages()

        self._ensure_config_loaded()
        self._load_translations()

    def _ensure_config_loaded(self) -> None:
        """延迟加载语言配置"""
        if self._config_loaded:
            return
        self._config_loaded = True
        if self._language_loader is None:
            return
        try:
            lang_str = self._language_loader()
            try:
                self._current_language = Language(lang_str)
            except ValueError:
                print(f"警告: 配置中的语言 '{lang_str}' 无效，使用默认语言")
        except Exception as e:
            print(f"加载语言配置时出错: {e}")

    def _load_translations(self) -> None:
        """加载当前语言的翻译文件"""
        lang_code = self._current_language
        lang_str = str(lang_code)

        translation_file = self.translations_dir / f"{lang_str}.json"

        self._translations.clear()
        self._loaded_files.clear()

        if translation_file.exists():
            try:
                with open(translation_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        if "__meta__" in data:
                            data.pop("__meta__")
                        self._translations = data
                        self._loaded_files.add(str(translation_file))
                        print(f"已加载翻译文件: {translation_file}")
                    else:
                        print(f"警告: 翻译文件格式无效，应为字典: {translation_file}")
            except Exception as e:
                print(f"加载翻译文件时出错 {translation_file}: {e}")
        else:
            print(f"警告: 翻译文件不存在: {translation_file}")
            self._create_template_file(translation_file)

    def _scan_available_languages(self) -> List[str]:
        """扫描 translations 目录下的所有可用语言文件

        Returns:
            语言代码列表
        """
        languages: List[str] = []
        self._language_display_map.clear()

        for file in self.translations_dir.glob("*.json"):
            lang_code, display_name = self._parse_language_metadata(file)
            languages.append(lang_code)
            self._language_display_map[lang_code] = display_name

        if not languages:
            languages = [Language.ZH_CN, Language.EN_US]
            self._language_display_map[Language.ZH_CN] = "简体中文"
            self._language_display_map[Language.EN_US] = "English (US)"
        return languages

    def _parse_language_metadata(self, file_path: Path) -> Tuple[str, str]:
        """解析翻译文件的元数据

        Args:
            file_path: 翻译文件路径

        Returns:
            (语言代码, 显示名称)
        """
        lang_code = file_path.stem
        display_name = lang_code
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "__meta__" in data and isinstance(data["__meta__"], dict):
                    meta = data["__meta__"]
                    if "language" in meta:
                        lang_code = meta["language"]
                    if "display_name" in meta:
                        display_name = meta["display_name"]
        except Exception:
            pass
        return lang_code, display_name

    def _create_template_file(self, file_path: Path) -> None:
        """创建翻译文件模板

        Args:
            file_path: 模板文件路径
        """
        template: Dict[str, Any] = {
            "app": {
                "title": "MCSaveHelper · 存档管理工具",
                "subtitle": "存档管理工具"
            },
            "top_bar": {
                "ready": "就绪",
                "start_conversion": "🚀 开始转换"
            },
            "left_panel": {
                "archive_config": "📁 存档目录配置",
                "client_archive": "客户端存档",
                "server_root": "服务端根目录",
                "world_folder_name": "世界文件夹名",
                "batch_archive_dir": "批量存档目录",
                "browse": "📂 浏览",
                "scan": "🔍 扫描",
                "placeholder_select_world": "选择世界文件夹（包含 level.dat）",
                "placeholder_default_dir": "默认为程序当前目录",
                "placeholder_world_name": "例如: world",
                "placeholder_batch_dir": "选择包含多个世界存档的目录"
            },
            "right_panel": {
                "mode_settings": "⚙️ 模式设置",
                "fast_mode": "快速模式",
                "full_mode": "完整模式",
                "offline_mode": "离线模式",
                "clean_mode": "清理模式",
                "version_detection": "版本检测",
                "advanced_settings": "⚙️ 高级设置",
                "max_concurrent": "最大并发数",
                "uuid_mapping": "UUID映射管理",
                "player_name": "玩家名称",
                "uuid": "UUID",
                "add": "添加",
                "remove": "移除",
                "manual_names": "手动指定玩家名（逗号分隔）",
                "placeholder_player_name": "输入玩家名",
                "placeholder_uuid": "输入UUID",
                "placeholder_manual_names": "player1,player2,player3"
            },
            "common": {
                "select": "选择",
                "confirm": "确认",
                "cancel": "取消",
                "save": "保存",
                "reset": "重置",
                "clear_log": "🗑️ 清空日志"
            },
            "dialogs": {
                "select_client_archive": "选择客户端存档目录",
                "select_server_root": "选择服务端根目录",
                "select_batch_dir": "选择包含多个世界存档的目录",
                "warning": "提示",
                "error": "错误",
                "success": "成功"
            },
            "messages": {
                "please_select_batch_dir": "请先选择批量存档目录",
                "batch_dir_not_exist": "批量存档目录不存在",
                "scanned_worlds": "扫描到 {count} 个世界存档: {names}",
                "no_valid_worlds": "未找到有效的世界存档（需要包含level.dat）",
                "batch_scan_complete": "批量扫描完成: 找到 {count} 个世界存档",
                "batch_scan_no_worlds": "批量扫描: 未找到有效的世界存档",
                "conversion_started": "转换开始...",
                "conversion_completed": "转换完成!",
                "conversion_failed": "转换失败: {error}"
            },
            "log_levels": {
                "INFO": "信息",
                "SUCCESS": "成功",
                "WARN": "警告",
                "ERROR": "错误",
                "API": "API"
            }
        }

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(template, f, ensure_ascii=False, indent=2)
            print(f"已创建翻译模板文件: {file_path}")
        except Exception as e:
            print(f"创建翻译模板文件时出错: {e}")

    def set_language(self, language: Language) -> None:
        """设置当前语言

        Args:
            language: 要设置的语言
        """
        if language != self._current_language:
            self._current_language = language
            self._load_translations()
            self._save_language_to_config()

    def _save_language_to_config(self) -> None:
        """将当前语言保存到配置"""
        if self._language_saver is None:
            return
        try:
            self._language_saver(str(self._current_language))
        except Exception as e:
            print(f"保存语言配置时出错: {e}")

    def get(
            self,
            key: str,
            default: Optional[str] = None,
            **kwargs: Any) -> str:
        """获取翻译文本

        Args:
            key: 翻译键，格式为 "category.key" 或 "category.subcategory.key"
            default: 如果找不到翻译时返回的默认文本
            **kwargs: 格式化参数

        Returns:
            翻译后的文本
        """
        parts = key.split('.')
        current = self._translations

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                result = default if default is not None else key
                if kwargs:
                    try:
                        result = result.format(**kwargs)
                    except (KeyError, ValueError):
                        pass
                return result

        result = str(current) if current is not None else (default or key)

        if kwargs:
            try:
                result = result.format(**kwargs)
            except (KeyError, ValueError):
                pass

        return result

    def translate(
            self,
            key: str,
            default: Optional[str] = None,
            **kwargs: Any) -> str:
        """翻译文本（get 的别名

        Args:
            key: 翻译键
            default: 默认文本
            **kwargs: 格式化参数

        Returns:
            翻译后的文本
        """
        return self.get(key, default, **kwargs)

    def t(self, key: str, default: Optional[str] = None, **kwargs: Any) -> str:
        """翻译文本（简写）

        Args:
            key: 翻译键
            default: 默认文本
            **kwargs: 格式化参数

        Returns:
            翻译后的文本
        """
        return self.get(key, default, **kwargs)

    @property
    def current_language(self) -> Language:
        """获取当前语言

        Returns:
            当前语言
        """
        return self._current_language

    @property
    def available_languages(self) -> Dict[Language, str]:
        """获取可用语言列表（动态扫描）

        Returns:
            语言枚举到显示名称的映射
        """
        self._scan_available_languages()
        result: Dict[Language, str] = {}
        for lang_code, display_name in self._language_display_map.items():
            try:
                lang = Language(lang_code)
                result[lang] = display_name
            except ValueError:
                continue
        return result

    @property
    def available_language_codes(self) -> List[str]:
        """获取可用语言代码列表

        Returns:
            语言代码列表
        """
        return self._available_languages.copy()

    def get_display_name(self, lang_code: str) -> str:
        """获取语言的显示名称

        Args:
            lang_code: 语言代码

        Returns:
            显示名称
        """
        return self._language_display_map.get(lang_code, lang_code)

    def reload(self) -> None:
        """重新加载翻译文件"""
        self._load_translations()


_translation_manager: Optional[TranslationManager] = None


def init_translations(
    translations_dir: Optional[Path] = None,
    language_loader: Optional[Callable[[], str]] = None,
    language_saver: Optional[Callable[[str], None]] = None,
) -> TranslationManager:
    """初始化翻译管理器

    Args:
        translations_dir: 翻译文件目录
        language_loader: 当前语言配置读取函数
        language_saver: 当前语言配置保存函数

    Returns:
        翻译管理器实例
    """
    global _translation_manager
    if _translation_manager is None:
        _translation_manager = TranslationManager(
            translations_dir, language_loader, language_saver)
    else:
        if language_loader is not None:
            _translation_manager._language_loader = language_loader
        if language_saver is not None:
            _translation_manager._language_saver = language_saver
    return _translation_manager


def get_translator() -> TranslationManager:
    """获取翻译管理器实例

    Returns:
        翻译管理器实例
    """
    global _translation_manager
    if _translation_manager is None:
        _translation_manager = TranslationManager()
    return _translation_manager


def t(key: str, default: Optional[str] = None, **kwargs: Any) -> str:
    """翻译文本（便捷函数）

    Args:
        key: 翻译键
        default: 默认文本
        **kwargs: 格式化参数

    Returns:
        翻译后的文本
    """
    return get_translator().t(key, default, **kwargs)


def set_language(language: Language) -> None:
    """设置当前语言

    Args:
        language: 要设置的语言
    """
    get_translator().set_language(language)


def get_current_language() -> Language:
    """获取当前语言

    Returns:
        当前语言
    """
    return get_translator().current_language


def get_available_languages() -> Dict[Language, str]:
    """获取可用语言列表

    Returns:
        可用语言映射
    """
    return get_translator().available_languages
