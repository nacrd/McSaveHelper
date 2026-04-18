"""右侧面板混入类"""
import customtkinter as ctk
from typing import Any, TYPE_CHECKING, Callable

from ui.constants import COLORS
from ui.widgets import TerminalLikeTextbox, ModernEntry, ModernButton, ModernCheckbox, UUIDMappingTable
from core.i18n import t

if TYPE_CHECKING:
    from ui.mixins.common import CommonUIMixin


class RightPanelMixin:
    """提供右侧面板构建方法"""
    
    if TYPE_CHECKING:
        mode_var: ctk.StringVar
        query_name_var: ctk.StringVar
        query_result: TerminalLikeTextbox
        offline_mode: ctk.BooleanVar
        clean_mode: ctk.BooleanVar
        batch_mode: ctk.BooleanVar
        version_detection: ctk.BooleanVar
        max_concurrent: ctk.IntVar
        new_player_name: ctk.StringVar
        new_uuid: ctk.StringVar
        uuid_listbox: ctk.CTkTextbox
        custom_uuid_mappings: dict
        _on_uuid_mappings_change: Callable[[dict], None]
        
        def query_uuid(self) -> None: ...
        def _toggle_batch_mode(self) -> None: ...
        def _save_config(self) -> None: ...
        def _add_uuid_mapping(self) -> None: ...
        def _update_uuid_list(self) -> None: ...
        def _clear_uuid_mappings(self) -> None: ...
        
        def _create_card(self, parent: Any) -> Any: ...
        def _add_section_title(self, parent: Any, text: str, icon_only: bool = False) -> None: ...
        def _set_readonly_text(self, textbox: Any, content: str) -> None: ...
    
    def _build_right_panel(self, parent: Any) -> None:
        """构建现代化右侧面板"""
        # 模式选择
        mode_card = self._create_card(parent)
        mode_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(mode_card, t("right_panel.mode_settings"), icon_only=False)
        mode_frame = ctk.CTkFrame(mode_card, fg_color="transparent")
        mode_frame.pack(fill="x", padx=20, pady=(12, 8))
        ctk.CTkRadioButton(
            mode_frame,
            text="⚡ " + t("right_panel.fast_mode"),
            variable=self.mode_var,
            value="fast",
            font=ctk.CTkFont(size=14, weight="bold"),
            hover_color=COLORS["accent_light"]
        ).pack(side="left", padx=(0, 30))
        ctk.CTkRadioButton(
            mode_frame,
            text="🧠 " + t("right_panel.full_mode"),
            variable=self.mode_var,
            value="full",
            font=ctk.CTkFont(size=14, weight="bold"),
            hover_color=COLORS["accent_light"]
        ).pack(side="left")
        ctk.CTkLabel(
            mode_card,
            text=t("right_panel.mode_description"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"]
        ).pack(anchor="w", padx=20, pady=(0, 18))
        
        # UUID 查询
        uuid_card = self._create_card(parent)
        uuid_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(uuid_card, t("right_panel.uuid_query"), icon_only=False)
        query_frame = ctk.CTkFrame(uuid_card, fg_color="transparent")
        query_frame.pack(fill="x", padx=20, pady=(12, 8))
        ModernEntry(
            query_frame,
            textvariable=self.query_name_var,
            placeholder_text=t("right_panel.placeholder_player_name"),
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ModernButton(
            query_frame,
            text=t("right_panel.query_button"),
            width=90,
            height=38,
            command=self.query_uuid,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"]
        ).pack(side="right")
        self.query_result = TerminalLikeTextbox(uuid_card, height=110)
        self.query_result.pack(fill="x", padx=20, pady=(8, 18))
        self._set_readonly_text(
            self.query_result,
            t("right_panel.query_result_placeholder")
        )
        
        # 迁移选项
        opt_card = self._create_card(parent)
        opt_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(opt_card, t("right_panel.migration_options"), icon_only=False)
        opt_frame = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_frame.pack(fill="x", padx=20, pady=(12, 8))
        ModernCheckbox(
            opt_frame,
            text=t("right_panel.offline_mode"),
            variable=self.offline_mode
        ).pack(anchor="w", pady=6)
        ModernCheckbox(
            opt_frame,
            text=t("right_panel.clean_mode"),
            variable=self.clean_mode
        ).pack(anchor="w", pady=6)
        ModernCheckbox(
            opt_frame,
            text=t("right_panel.batch_mode"),
            variable=self.batch_mode,
            command=self._toggle_batch_mode
        ).pack(anchor="w", pady=6)
        
        # 高级配置
        adv_card = self._create_card(parent)
        adv_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(adv_card, t("right_panel.advanced_settings"), icon_only=False)
        
        # 版本检测
        config_frame1 = ctk.CTkFrame(adv_card, fg_color="transparent")
        config_frame1.pack(fill="x", padx=20, pady=(12, 8))
        ModernCheckbox(
            config_frame1,
            text=t("right_panel.version_detection"),
            variable=self.version_detection,
            command=self._save_config
        ).pack(side="left", padx=(0, 20))
        
        # 批量处理设置
        batch_frame = ctk.CTkFrame(adv_card, fg_color="transparent")
        batch_frame.pack(fill="x", padx=20, pady=(8, 18))
        ctk.CTkLabel(
            batch_frame,
            text=t("right_panel.max_concurrent"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(side="left")
        concurrent_spinbox = ModernEntry(
            batch_frame,
            textvariable=self.max_concurrent,
            width=60,
            height=38,
        )
        concurrent_spinbox.pack(side="left", padx=(10, 0))
        concurrent_spinbox.bind("<FocusOut>", lambda e: self._save_config())
        
        # UUID映射管理
        uuid_card = self._create_card(parent)
        uuid_card.pack(fill="x")
        self._add_section_title(uuid_card, t("right_panel.uuid_mapping"), icon_only=False)

        # 可视化UUID映射编辑器
        self.uuid_table = UUIDMappingTable(
            uuid_card,
            mappings=self.custom_uuid_mappings,
            on_mappings_change=self._on_uuid_mappings_change
        )
        self.uuid_table.pack(fill="x", padx=20, pady=(12, 18))