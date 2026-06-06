"""国际化服务 —— 封装翻译逻辑，简化 UI 层调用"""
from typing import Dict, List, Optional

from core.i18n import TranslationManager, t as _t


class I18nService:
    """国际化翻译服务

    职责：
      - 初始化翻译管理器
      - 提供翻译快捷方法
      - 管理可用语言列表
    """

    def __init__(self) -> None:
        self._manager = TranslationManager()

    @property
    def available_languages(self) -> List[str]:
        return self._manager.available_language_codes

    @property
    def current_language(self) -> str:
        return str(self._manager.current_language)

    def translate(self, key: str, default: str = "", **kwargs) -> str:
        """翻译指定的键，支持格式化参数"""
        return _t(key, default, **kwargs)

    def set_language(self, lang_code: str) -> None:
        """切换语言"""
        from core.i18n import Language
        try:
            self._manager.set_language(Language(lang_code))
        except ValueError:
            pass

    def get_display_name(self, lang_code: str) -> str:
        """获取语言的显示名称"""
        return self._manager.get_display_name(lang_code)


# 模块级快捷函数（向后兼容）
_i18n_service: Optional[I18nService] = None


def get_i18n() -> I18nService:
    global _i18n_service
    if _i18n_service is None:
        _i18n_service = I18nService()
    return _i18n_service


def t(key: str, default: str = "", **kwargs) -> str:
    return get_i18n().translate(key, default, **kwargs)
