"""顶部导航栏混入类"""
import customtkinter as ctk
from typing import Any, TYPE_CHECKING

from ui.constants import COLORS
from ui.widgets import ModernButton, ModernProgressBar
from core.i18n import Language, get_translator, t

if TYPE_CHECKING:
    pass


class TopBarMixin:
    """提供顶部导航栏构建方法"""
    
    if TYPE_CHECKING:
        main_bg: ctk.CTkFrame
        progress_label: ctk.CTkLabel
        progress: ModernProgressBar
        start_btn: ModernButton
        language_btn: ModernButton
        
        def start(self) -> None: ...
        def log_msg(self, msg: str, level: str = "INFO") -> None: ...
        def update_all_ui_texts(self) -> None: ...
    
    def _build_top_bar(self) -> None:
        """构建现代化顶部导航栏"""
        top_frame = ctk.CTkFrame(
            self.main_bg,
            fg_color=COLORS["bg_secondary"],
            corner_radius=0,
            height=75
        )
        top_frame.pack(fill="x")
        
        title_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        title_frame.pack(side="left", padx=25, pady=15)
        
        ctk.CTkLabel(
            title_frame,
            text="🌍",
            font=ctk.CTkFont(size=28),
            text_color=COLORS["accent_light"],
        ).pack(side="left", padx=(0, 10))
        
        title_label = ctk.CTkLabel(
            title_frame,
            text="MC Migrator Pro",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=COLORS["text_primary"],
        )
        title_label.pack(side="left")
        
        subtitle_label = ctk.CTkLabel(
            title_frame,
            text="存档迁移工具",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        subtitle_label.pack(side="left", padx=(8, 0))
        
        # 语言切换按钮容器
        language_container = ctk.CTkFrame(top_frame, fg_color="transparent")
        language_container.pack(side="right", padx=(0, 15), pady=18)
        
        # 获取当前语言显示文本
        translator = get_translator()
        current_lang = translator.current_language
        available = translator.available_languages
        display_name = available.get(current_lang, str(current_lang))
        flag_emoji = self._get_flag_emoji(current_lang)
        lang_display = f"{flag_emoji} {display_name}" if flag_emoji else display_name
        
        self.language_btn = ModernButton(
            language_container,
            text=lang_display,
            width=100,
            height=35,
            command=self._toggle_language,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_primary"]
        )
        self.language_btn.pack()
        
        progress_container = ctk.CTkFrame(top_frame, fg_color="transparent")
        progress_container.pack(side="right", padx=(0, 15), pady=18)
        
        self.progress_label = ctk.CTkLabel(
            progress_container,
            text=t("top_bar.ready", "就绪"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["accent_light"],
        )
        self.progress_label.pack(side="left", padx=(0, 12))
        
        self.progress = ModernProgressBar(
            progress_container,
            width=220,
            height=10,
        )
        self.progress.pack(side="left")
        self.progress.set(0)
        
        self.start_btn = ModernButton(
            top_frame,
            text=t("top_bar.start_conversion", "🚀 开始转换"),
            width=140,
            height=40,
            command=self.start,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
        )
        self.start_btn.pack(side="right", padx=(0, 25), pady=18)
    
    def _toggle_language(self) -> None:
        """切换语言（支持动态语言列表）"""
        translator = get_translator()
        current_lang = translator.current_language
        available = translator.available_languages  # Dict[Language, str]
        
        if not available:
            # 如果没有可用语言，回退到默认切换
            new_lang = Language.EN_US if current_lang == Language.ZH_CN else Language.ZH_CN
        else:
            # 获取语言列表
            lang_list = list(available.keys())
            try:
                current_index = lang_list.index(current_lang)
                next_index = (current_index + 1) % len(lang_list)
                new_lang = lang_list[next_index]
            except ValueError:
                # 当前语言不在列表中，选择第一个
                new_lang = lang_list[0]
        
        # 设置新语言
        translator.set_language(new_lang)
        
        # 更新按钮文本
        display_name = available.get(new_lang, str(new_lang))
        # 添加国旗表情符号（可选）
        flag_emoji = self._get_flag_emoji(new_lang)
        lang_display = f"{flag_emoji} {display_name}" if flag_emoji else display_name
        self.language_btn.configure(text=lang_display)
        
        # 更新其他UI文本
        self._update_ui_texts()
        
        # 尝试调用App的update_all_ui_texts方法（如果存在）
        if hasattr(self, 'update_all_ui_texts'):
            self.update_all_ui_texts()
        
        # 记录日志（如果存在log_msg方法）
        try:
            self.log_msg(f"语言已切换为: {display_name}", "INFO")
        except AttributeError:
            # 如果log_msg方法不存在，静默忽略
            pass
    
    def _get_flag_emoji(self, language: Language) -> str:
        """根据语言代码返回国旗表情符号"""
        # 简单映射
        mapping = {
            Language.ZH_CN: "🇨🇳",
            Language.EN_US: "🇺🇸",
            # 可以扩展其他语言
        }
        return mapping.get(language, "")
    
    def _update_ui_texts(self) -> None:
        """更新UI文本（需要在子类中实现或通过其他方式更新）"""
        # 更新进度标签
        self.progress_label.configure(text=t("top_bar.ready", "就绪"))
        
        # 更新开始按钮
        self.start_btn.configure(text=t("top_bar.start_conversion", "🚀 开始转换"))
        
        # 注意：其他UI文本的更新需要在各自的混入类中处理
        # 这里只是更新顶部导航栏的文本