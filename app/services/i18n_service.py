"""国际化服务 —— 封装翻译逻辑，简化 UI 层调用"""
from typing import Dict, List, Optional

from core.i18n import TranslationManager, init_translations, t as _t
from app.services.config_service import ConfigService


class I18nService:
    """国际化翻译服务

    职责：
      - 初始化翻译管理器
      - 提供翻译快捷方法
      - 管理可用语言列表
    """

    def __init__(self) -> None:
        self._config = ConfigService()
        self._manager: TranslationManager = init_translations(
            language_loader=lambda: self._config.language,
            language_saver=self._save_language,
        )

    def _save_language(self, lang_code: str) -> None:
        self._config.language = lang_code
        self._config.save()

    @property
    def available_languages(self) -> List[str]:
        """可用语言代码列表

        Returns:
            List[str]: 可用语言代码列表
        """
        return self._manager.available_language_codes

    @property
    def current_language(self) -> str:
        """当前使用的语言代码

        Returns:
            str: 当前语言代码
        """
        return str(self._manager.current_language)

    def translate(self, key: str, default: str = "", **kwargs) -> str:
        """翻译指定的键，支持格式化参数

        Args:
            key: 翻译键
            default: 默认文本（当键不存在时使用）
            **kwargs: 格式化参数

        Returns:
            str: 翻译后的文本
        """
        return _t(key, default, **kwargs)

    def set_language(self, lang_code: str) -> None:
        """切换语言

        Args:
            lang_code: 语言代码
        """
        from core.i18n import Language
        try:
            self._manager.set_language(Language(lang_code))
        except ValueError:
            pass

    def get_display_name(self, lang_code: str) -> str:
        """获取语言的显示名称

        Args:
            lang_code: 语言代码

        Returns:
            str: 语言的显示名称
        """
        return self._manager.get_display_name(lang_code)


# 模块级快捷函数（向后兼容）
_i18n_service: Optional[I18nService] = None


def get_i18n() -> I18nService:
    """获取I18nService单例实例

    Returns:
        I18nService: I18nService实例
    """
    global _i18n_service
    if _i18n_service is None:
        _i18n_service = I18nService()
    return _i18n_service


def t(key: str, default: str = "", **kwargs) -> str:
    """翻译快捷函数

    Args:
        key: 翻译键
        default: 默认文本
        **kwargs: 格式化参数

    Returns:
        str: 翻译后的文本
    """
    return get_i18n().translate(key, default, **kwargs)
