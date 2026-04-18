"""国际化翻译模块

提供多语言支持，使用JSON文件存储翻译文本。
支持动态语言切换和热重载。
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Set, List, Tuple
from enum import Enum
try:
    from enum import StrEnum  # type: ignore
except ImportError:
    try:
        from typing_extensions import StrEnum  # type: ignore
    except ImportError:
        # 自定义 StrEnum 作为回退
        class _StrEnum(str, Enum):
            """自定义字符串枚举，兼容 Python <3.11"""
            pass
        StrEnum = _StrEnum

from .config import config_manager


class Language(StrEnum):  # type: ignore
    """支持的语言枚举"""
    ZH_CN = "zh_CN"  # 简体中文
    EN_US = "en_US"  # 英文（美国）

    @classmethod
    def _missing_(cls, value):
        """为未知语言代码动态创建枚举成员"""
        # 动态创建新成员
        member = str.__new__(cls, value)
        member._value_ = value
        # 生成一个合法的名称（替换非法字符）
        name = value.upper().replace('-', '_').replace(' ', '_')
        member._name_ = name
        # 注册到枚举映射中
        cls._value2member_map_[value] = member
        return member


class TranslationManager:
    """翻译管理器
    
    负责加载翻译文件、管理当前语言设置、提供翻译功能。
    """
    
    def __init__(self, translations_dir: Optional[Path] = None):
        """初始化翻译管理器
        
        Args:
            translations_dir: 翻译文件目录，默认为项目根目录下的 translations 文件夹
        """
        if translations_dir is None:
            # 默认翻译文件目录
            if hasattr(sys, '_MEIPASS'):
                # 打包后运行时
                base_dir = Path(sys._MEIPASS)  # type: ignore
            else:
                # 开发环境
                base_dir = Path(__file__).parent.parent
            self.translations_dir = base_dir / "translations"
        else:
            self.translations_dir = Path(translations_dir)
        
        # 确保目录存在（打包后目录已存在，无需创建）
        if not self.translations_dir.exists():
            self.translations_dir.mkdir(parents=True, exist_ok=True)
        
        # 当前语言，从配置中读取或使用默认
        self._current_language = Language.ZH_CN
        self._translations: Dict[str, Dict[str, str]] = {}
        self._loaded_files: Set[str] = set()
        self._available_languages: List[str] = []
        self._language_display_map: Dict[str, str] = {}
        
        # 加载配置中的语言设置
        self._load_language_from_config()
        
        # 扫描可用的语言文件
        self._available_languages = self._scan_available_languages()
        
        # 加载翻译文件
        self._load_translations()
    
    def _load_language_from_config(self) -> None:
        """从配置中加载语言设置"""
        try:
            # 尝试从配置中获取语言设置
            config = config_manager.config
            if "ui_settings" in config and "language" in config["ui_settings"]:
                lang_str = config["ui_settings"]["language"]
                try:
                    self._current_language = Language(lang_str)
                except ValueError:
                    # 如果配置中的语言无效，使用默认
                    print(f"警告: 配置中的语言 '{lang_str}' 无效，使用默认语言")
        except Exception as e:
            print(f"加载语言配置时出错: {e}")
    
    def _load_translations(self) -> None:
        """加载当前语言的翻译文件"""
        lang_code = self._current_language
        lang_str = str(lang_code)
        
        translation_file = self.translations_dir / f"{lang_str}.json"
        
        # 清除已加载的翻译
        self._translations.clear()
        self._loaded_files.clear()
        
        if translation_file.exists():
            try:
                with open(translation_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # 移除 __meta__ 键（如果有）
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
            # 创建空的翻译文件模板
            self._create_template_file(translation_file)
    
    def _scan_available_languages(self) -> List[str]:
        """扫描 translations 目录下的所有可用语言文件，返回语言代码列表"""
        languages = []
        self._language_display_map.clear()
        
        # 扫描 translations 目录
        for file in self.translations_dir.glob("*.json"):
            lang_code, display_name = self._parse_language_metadata(file)
            languages.append(lang_code)
            self._language_display_map[lang_code] = display_name
        
        # 确保至少包含默认语言
        if not languages:
            languages = [Language.ZH_CN, Language.EN_US]
            # 添加默认显示名称
            self._language_display_map[Language.ZH_CN] = "简体中文"
            self._language_display_map[Language.EN_US] = "English (US)"
        return languages

    def _parse_language_metadata(self, file_path: Path) -> Tuple[str, str]:
        """解析翻译文件的元数据，返回语言代码和显示名称
        
        Args:
            file_path: 翻译文件路径
            
        Returns:
            (语言代码, 显示名称)
        """
        lang_code = file_path.stem
        display_name = lang_code  # 默认显示名称
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 检查是否有 __meta__ 对象
                if "__meta__" in data and isinstance(data["__meta__"], dict):
                    meta = data["__meta__"]
                    if "language" in meta:
                        lang_code = meta["language"]
                    if "display_name" in meta:
                        display_name = meta["display_name"]
        except Exception:
            # 如果解析失败，使用默认值
            pass
        return lang_code, display_name
    
    def _create_template_file(self, file_path: Path) -> None:
        """创建翻译文件模板"""
        template = {
            "app": {
                "title": "MC Migrator Pro · 存档迁移工具",
                "subtitle": "存档迁移工具"
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
                "placeholder_select_world": "选择世界文件夹 (包含 level.dat)",
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
                "manual_names": "手动指定玩家名 (逗号分隔)",
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
            
            # 保存到配置
            self._save_language_to_config()
    
    def _save_language_to_config(self) -> None:
        """将当前语言保存到配置"""
        try:
            config = config_manager.config
            if "ui_settings" not in config:
                config["ui_settings"] = {}
            config["ui_settings"]["language"] = self._current_language
            config_manager.save_config()
        except Exception as e:
            print(f"保存语言配置时出错: {e}")
    
    def get(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """获取翻译文本
        
        Args:
            key: 翻译键，格式为 "category.key" 或 "category.subcategory.key"
            default: 如果找不到翻译时返回的默认文本
            **kwargs: 格式化参数
            
        Returns:
            翻译后的文本，如果找不到则返回默认文本或键本身
        """
        # 分割键
        parts = key.split('.')
        current_dict = self._translations
        
        # 遍历嵌套字典
        for part in parts:
            if isinstance(current_dict, dict) and part in current_dict:
                current_dict = current_dict[part]
            else:
                # 找不到翻译
                if default is not None:
                    result = default
                else:
                    result = key
                
                # 应用格式化
                if kwargs:
                    try:
                        result = result.format(**kwargs)
                    except (KeyError, ValueError):
                        pass
                return result
        
        # 找到的最终值
        result = str(current_dict) if current_dict is not None else (default or key)
        
        # 应用格式化
        if kwargs:
            try:
                result = result.format(**kwargs)
            except (KeyError, ValueError):
                pass
        
        return result
    
    def translate(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """翻译文本（get的别名）"""
        return self.get(key, default, **kwargs)
    
    def t(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """翻译文本（简写）"""
        return self.get(key, default, **kwargs)
    
    @property
    def current_language(self) -> Language:
        """获取当前语言"""
        return self._current_language
    
    @property
    def available_languages(self) -> Dict[Language, str]:
        """获取可用语言列表（动态扫描）"""
        result = {}
        for lang_code, display_name in self._language_display_map.items():
            # 将字符串语言代码转换为 Language 枚举成员
            try:
                lang = Language(lang_code)
            except ValueError:
                # 如果动态枚举无法处理，跳过
                continue
            result[lang] = display_name
        # 确保至少包含默认语言
        if Language.ZH_CN not in result:
            result[Language.ZH_CN] = "简体中文"
        if Language.EN_US not in result:
            result[Language.EN_US] = "English (US)"
        return result
    
    def reload(self) -> None:
        """重新加载翻译文件"""
        self._load_translations()


# 全局翻译管理器实例
_translation_manager: Optional[TranslationManager] = None


def init_translations(translations_dir: Optional[Path] = None) -> TranslationManager:
    """初始化翻译管理器
    
    Args:
        translations_dir: 翻译文件目录
        
    Returns:
        翻译管理器实例
    """
    global _translation_manager
    if _translation_manager is None:
        _translation_manager = TranslationManager(translations_dir)
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


# 便捷函数
def t(key: str, default: Optional[str] = None, **kwargs) -> str:
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
    """获取当前语言"""
    return get_translator().current_language


def get_available_languages() -> Dict[Language, str]:
    """获取可用语言列表"""
    return get_translator().available_languages