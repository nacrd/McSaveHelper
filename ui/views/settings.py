"""设置视图 - 应用配置管理"""
import customtkinter as ctk
from typing import Any, List, Dict
from pathlib import Path

from ui.constants import COLORS
from ui.widgets import ModernCard, ModernButton, ModernCheckbox, ModernEntry
from core.config import config_manager
from core.i18n import t


class SettingsView(ctk.CTkFrame):
    """设置视图"""
    
    def __init__(self, master: Any, **kwargs) -> None:
        # 确保背景透明，移除可能冲突的fg_color参数
        kwargs.pop('fg_color', None)
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config_manager = config_manager
        self._build_ui()
    
    def _build_ui(self) -> None:
        # 创建滚动容器
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, padx=0, pady=0)
        
        # 通用设置卡片
        self._build_general_card()
        
        # UI 设置卡片
        self._build_ui_card()
        
        # 批量处理卡片
        self._build_batch_card()
        
        # UUID 映射卡片
        self._build_uuid_card()
        
        # 清理模式卡片
        self._build_cleanup_card()
        
        # 操作按钮卡片
        self._build_action_card()
    
    def _build_general_card(self) -> None:
        """通用设置"""
        card = ModernCard(self.scroll_frame)
        card.pack(fill="x", padx=0, pady=(0, 16))
        
        # 标题
        ctk.CTkLabel(
            card,
            text=t("settings.general.title", "通用设置"),
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", padx=20, pady=(20, 10))
        
        # 版本检测
        self.version_detection_var = ctk.BooleanVar(
            value=self.config_manager.config["version_detection"]
        )
        chk = ModernCheckbox(
            card,
            text=t("settings.general.version_detection", "启用版本自动检测"),
            variable=self.version_detection_var,
            hover_color=COLORS["accent_hover"]
        )
        chk.pack(anchor="w", padx=20, pady=(0, 8))
        
        # API 超时
        ctk.CTkLabel(
            card,
            text=t("settings.general.api_timeout", "API 超时 (秒)"),
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(10, 0))
        
        self.api_timeout_var = ctk.StringVar(
            value=str(self.config_manager.config["api_timeout"])
        )
        entry = ModernEntry(
            card,
            textvariable=self.api_timeout_var,
            placeholder_text="10",
            width=100
        )
        entry.pack(anchor="w", padx=20, pady=(5, 20))
    
    def _build_ui_card(self) -> None:
        """UI 设置"""
        card = ModernCard(self.scroll_frame)
        card.pack(fill="x", padx=0, pady=(0, 16))
        
        ctk.CTkLabel(
            card,
            text=t("settings.ui.title", "界面设置"),
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", padx=20, pady=(20, 10))
        
        # 主题选择
        ctk.CTkLabel(
            card,
            text=t("settings.ui.theme", "主题"),
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 5))
        
        theme_choices = ["dark", "light"]
        self.theme_var = ctk.StringVar(
            value=self.config_manager.config["ui_settings"]["theme"]
        )
        theme_menu = ctk.CTkOptionMenu(
            card,
            values=theme_choices,
            variable=self.theme_var,
            width=120,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"]
        )
        theme_menu.pack(anchor="w", padx=20, pady=(0, 10))
        
        # 语言选择
        ctk.CTkLabel(
            card,
            text=t("settings.ui.language", "语言"),
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 5))
        
        lang_choices = ["zh_CN", "en_US"]
        self.language_var = ctk.StringVar(
            value=self.config_manager.config["ui_settings"]["language"]
        )
        lang_menu = ctk.CTkOptionMenu(
            card,
            values=lang_choices,
            variable=self.language_var,
            width=120,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"]
        )
        lang_menu.pack(anchor="w", padx=20, pady=(0, 10))
        
        # 自动清除日志
        self.auto_clear_log_var = ctk.BooleanVar(
            value=self.config_manager.config["ui_settings"]["auto_clear_log"]
        )
        chk = ModernCheckbox(
            card,
            text=t("settings.ui.auto_clear_log", "自动清除旧日志"),
            variable=self.auto_clear_log_var,
            hover_color=COLORS["accent_hover"]
        )
        chk.pack(anchor="w", padx=20, pady=(0, 20))
    
    def _build_batch_card(self) -> None:
        """批量处理设置"""
        card = ModernCard(self.scroll_frame)
        card.pack(fill="x", padx=0, pady=(0, 16))
        
        ctk.CTkLabel(
            card,
            text=t("settings.batch.title", "批量处理"),
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", padx=20, pady=(20, 10))
        
        # 最大并发数
        ctk.CTkLabel(
            card,
            text=t("settings.batch.max_concurrent", "最大并发处理数 (1‑16)"),
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", padx=20, pady=(0, 5))
        
        self.max_concurrent_var = ctk.StringVar(
            value=str(self.config_manager.config["batch_processing"]["max_concurrent"])
        )
        entry = ModernEntry(
            card,
            textvariable=self.max_concurrent_var,
            placeholder_text="2",
            width=100
        )
        entry.pack(anchor="w", padx=20, pady=(0, 10))
        
        # 保留结构
        self.preserve_structure_var = ctk.BooleanVar(
            value=self.config_manager.config["batch_processing"]["preserve_structure"]
        )
        chk = ModernCheckbox(
            card,
            text=t("settings.batch.preserve_structure", "保留原始文件结构"),
            variable=self.preserve_structure_var,
            hover_color=COLORS["accent_hover"]
        )
        chk.pack(anchor="w", padx=20, pady=(0, 20))
    
    def _build_uuid_card(self) -> None:
        """UUID 映射设置"""
        card = ModernCard(self.scroll_frame)
        card.pack(fill="x", padx=0, pady=(0, 16))
        
        ctk.CTkLabel(
            card,
            text=t("settings.uuid.title", "自定义 UUID 映射"),
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", padx=20, pady=(20, 10))
        
        # 说明文本
        ctk.CTkLabel(
            card,
            text=t("settings.uuid.description", "在此添加玩家名与 UUID 的映射，用于离线模式下的玩家数据转换。"),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
            wraplength=600
        ).pack(anchor="w", padx=20, pady=(0, 15))
        
        # 映射表格（使用现有组件）
        from ui.widgets import UUIDMappingTable
        self.mapping_table = UUIDMappingTable(
            card,
            mappings=self.config_manager.config["custom_uuid_mappings"],
            on_mappings_change=self._on_mappings_change
        )
        self.mapping_table.pack(fill="x", padx=20, pady=(0, 20))
    
    def _build_cleanup_card(self) -> None:
        """清理模式设置"""
        card = ModernCard(self.scroll_frame)
        card.pack(fill="x", padx=0, pady=(0, 16))
        
        ctk.CTkLabel(
            card,
            text=t("settings.cleanup.title", "清理模式"),
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", padx=20, pady=(20, 10))
        
        # 说明
        ctk.CTkLabel(
            card,
            text=t("settings.cleanup.description", "转换完成后自动删除的文件/目录模式（每行一个，支持通配符）"),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
            wraplength=600
        ).pack(anchor="w", padx=20, pady=(0, 10))
        
        # 多行文本框
        self.cleanup_text = ctk.CTkTextbox(card, height=100, corner_radius=6, border_width=1, border_color=COLORS["border"])
        self.cleanup_text.pack(fill="x", padx=20, pady=(0, 10))
        
        # 加载现有模式
        patterns = self.config_manager.config["cleanup_patterns"]
        if isinstance(patterns, list):
            self.cleanup_text.insert("1.0", "\n".join(patterns))
        
        # 默认按钮
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ModernButton(
            btn_frame,
            text=t("settings.cleanup.restore_defaults", "恢复默认"),
            width=120,
            command=self._restore_default_cleanup
        ).pack(side="left")
    
    def _build_action_card(self) -> None:
        """操作按钮"""
        card = ModernCard(self.scroll_frame)
        card.pack(fill="x", padx=0, pady=(0, 24))
        
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=20)
        
        # 保存按钮
        save_btn = ModernButton(
            btn_frame,
            text=t("settings.actions.save", "💾 保存设置"),
            width=140,
            command=self._save_settings,
            fg_color=COLORS["success"],
            hover_color=COLORS["success_light"]
        )
        save_btn.pack(side="left", padx=(0, 10))
        
        # 重置按钮
        reset_btn = ModernButton(
            btn_frame,
            text=t("settings.actions.reset", "↻ 重置为默认"),
            width=140,
            command=self._reset_to_defaults,
            fg_color=COLORS["warning"],
            hover_color=COLORS["warning_light"]
        )
        reset_btn.pack(side="left", padx=(0, 10))
        
        # 取消按钮
        cancel_btn = ModernButton(
            btn_frame,
            text=t("settings.actions.cancel", "取消"),
            width=100,
            command=self._cancel,
            fg_color=COLORS["bg_card"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            hover_color=COLORS["bg_card_hover"]
        )
        cancel_btn.pack(side="left")
    
    def _on_mappings_change(self, mappings: Dict[str, str]) -> None:
        """UUID 映射变更回调"""
        self.config_manager.config["custom_uuid_mappings"] = mappings
    
    def _restore_default_cleanup(self) -> None:
        """恢复默认清理模式"""
        default_patterns = ["*.log", "cache/", "logs/"]
        self.cleanup_text.delete("1.0", "end")
        self.cleanup_text.insert("1.0", "\n".join(default_patterns))
    
    def _save_settings(self) -> None:
        """保存所有设置到配置文件"""
        try:
            # 通用设置
            self.config_manager.config["version_detection"] = self.version_detection_var.get()
            try:
                self.config_manager.config["api_timeout"] = int(self.api_timeout_var.get())
            except ValueError:
                pass  # 保持原值
            
            # UI 设置
            self.config_manager.config["ui_settings"]["theme"] = self.theme_var.get()
            self.config_manager.config["ui_settings"]["language"] = self.language_var.get()
            self.config_manager.config["ui_settings"]["auto_clear_log"] = self.auto_clear_log_var.get()
            
            # 批量处理
            try:
                self.config_manager.config["batch_processing"]["max_concurrent"] = int(self.max_concurrent_var.get())
            except ValueError:
                pass
            self.config_manager.config["batch_processing"]["preserve_structure"] = self.preserve_structure_var.get()
            
            # 清理模式
            text = self.cleanup_text.get("1.0", "end-1c").strip()
            patterns = [p.strip() for p in text.splitlines() if p.strip()]
            self.config_manager.config["cleanup_patterns"] = patterns
            
            # 保存到文件
            self.config_manager.save_config()
            
            # 提示成功
            self._show_message(t("messages.settings_saved", "设置已保存"), "success")
        except Exception as e:
            self._show_message(t("messages.save_failed", "保存失败: {error}").format(error=str(e)), "error")
    
    def _reset_to_defaults(self) -> None:
        """重置所有设置为默认值"""
        from core.config import ConfigSchema
        default_config = {}
        for key, field_def in ConfigSchema.BASE_SCHEMA.items():
            if key == "version":
                default_config[key] = field_def["default"]
            elif "schema" in field_def:
                default_config[key] = {}
                for sub_key, sub_field_def in field_def["schema"].items():
                    default_config[key][sub_key] = sub_field_def["default"]
            else:
                default_config[key] = field_def["default"]
        
        # 更新当前配置
        self.config_manager.config.update(default_config)
        # 重新加载 UI（简易实现：重新构建）
        self._reload_ui()
        self._show_message(t("messages.settings_reset", "已重置为默认设置"), "info")
    
    def _cancel(self) -> None:
        """取消更改，关闭视图？这里我们只清空更改，但保留现有配置"""
        # 重新从配置文件加载
        self.config_manager.__init__()  # 重新初始化以重新加载
        self._reload_ui()
        self._show_message(t("messages.changes_discarded", "更改已丢弃"), "info")
    
    def _reload_ui(self) -> None:
        """重新加载 UI 以反映配置更改"""
        # 销毁现有组件
        for child in self.scroll_frame.winfo_children():
            child.destroy()
        # 重新构建
        self._build_ui()
    
    def _show_message(self, text: str, level: str = "info") -> None:
        """显示临时消息（简单实现）"""
        # 这里可以扩展为状态栏或 toast 通知
        print(f"[{level}] {text}")