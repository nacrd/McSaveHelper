"""右侧面板混入类"""
import customtkinter as ctk

from ui.constants import COLORS
from ui.widgets import TerminalLikeTextbox


class RightPanelMixin:
    """提供右侧面板构建方法"""
    
    def _build_right_panel(self, parent):
        """构建右侧面板"""
        # 模式选择
        mode_card = self._create_card(parent)
        mode_card.pack(fill="x", pady=(0, 15))
        self._add_section_title(mode_card, "⚙️ 迁移模式", icon_only=False)
        mode_frame = ctk.CTkFrame(mode_card, fg_color="transparent")
        mode_frame.pack(fill="x", padx=20, pady=(10, 5))
        ctk.CTkRadioButton(
            mode_frame,
            text="⚡ 快速模式",
            variable=self.mode_var,
            value="fast",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left", padx=(0, 30))
        ctk.CTkRadioButton(
            mode_frame,
            text="🧠 完整模式",
            variable=self.mode_var,
            value="full",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")
        ctk.CTkLabel(
            mode_card,
            text="快速：仅复制双 UUID 文件   |   完整：深度转换 + 可选精简",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"]
        ).pack(anchor="w", padx=20, pady=(0, 15))
        
        # UUID 查询
        uuid_card = self._create_card(parent)
        uuid_card.pack(fill="x", pady=(0, 15))
        self._add_section_title(uuid_card, "🔍 UUID 查询", icon_only=False)
        query_frame = ctk.CTkFrame(uuid_card, fg_color="transparent")
        query_frame.pack(fill="x", padx=20, pady=(10, 5))
        ctk.CTkEntry(
            query_frame,
            textvariable=self.query_name_var,
            height=36,
            placeholder_text="输入玩家名，如: Steve",
            border_width=1,
            border_color=COLORS["border"]
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(
            query_frame,
            text="🔎 查询",
            width=80,
            height=36,
            command=self.query_uuid,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"]
        ).pack(side="right")
        self.query_result = TerminalLikeTextbox(uuid_card, height=100)
        self.query_result.pack(fill="x", padx=20, pady=(5, 15))
        self._set_readonly_text(
            self.query_result,
            "💡 查询结果会显示在这里...\n离线 UUID 与 正版 UUID"
        )
        
        # 迁移选项
        opt_card = self._create_card(parent)
        opt_card.pack(fill="x", pady=(0, 15))
        self._add_section_title(opt_card, "🔧 迁移选项", icon_only=False)
        opt_frame = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_frame.pack(fill="x", padx=20, pady=(10, 5))
        ctk.CTkCheckBox(
            opt_frame,
            text="强制离线模式 (不请求 Mojang API)",
            variable=self.offline_mode
        ).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(
            opt_frame,
            text="精简存档 (删除缓存/日志等)",
            variable=self.clean_mode
        ).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(
            opt_frame,
            text="批量处理模式",
            variable=self.batch_mode,
            command=self._toggle_batch_mode
        ).pack(anchor="w", pady=5)
        
        # 高级配置
        adv_card = self._create_card(parent)
        adv_card.pack(fill="x", pady=(0, 15))
        self._add_section_title(adv_card, "⚙️ 高级配置", icon_only=False)
        
        # 版本检测
        config_frame1 = ctk.CTkFrame(adv_card, fg_color="transparent")
        config_frame1.pack(fill="x", padx=20, pady=(10, 5))
        ctk.CTkCheckBox(
            config_frame1,
            text="自动检测Minecraft版本",
            variable=self.version_detection,
            command=self._save_config
        ).pack(side="left", padx=(0, 20))
        
        # 批量处理设置
        batch_frame = ctk.CTkFrame(adv_card, fg_color="transparent")
        batch_frame.pack(fill="x", padx=20, pady=(5, 15))
        ctk.CTkLabel(
            batch_frame,
            text="最大并发数:",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        ).pack(side="left")
        concurrent_spinbox = ctk.CTkEntry(
            batch_frame,
            textvariable=self.max_concurrent,
            width=60,
            border_width=1,
            border_color=COLORS["border"]
        )
        concurrent_spinbox.pack(side="left", padx=(10, 0))
        concurrent_spinbox.bind("<FocusOut>", lambda e: self._save_config())
        
        # UUID映射管理
        uuid_card = self._create_card(parent)
        uuid_card.pack(fill="x")
        self._add_section_title(uuid_card, "🔗 自定义UUID映射", icon_only=False)
        
        uuid_frame = ctk.CTkFrame(uuid_card, fg_color="transparent")
        uuid_frame.pack(fill="x", padx=20, pady=(10, 5))
        
        # 添加新映射
        add_frame = ctk.CTkFrame(uuid_frame, fg_color="transparent")
        add_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            add_frame,
            text="玩家名:",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        ).pack(side="left")
        ctk.CTkEntry(
            add_frame,
            textvariable=self.new_player_name,
            width=120,
            border_width=1,
            border_color=COLORS["border"]
        ).pack(side="left", padx=(5, 20))
        ctk.CTkLabel(
            add_frame,
            text="UUID:",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        ).pack(side="left")
        ctk.CTkEntry(
            add_frame,
            textvariable=self.new_uuid,
            width=250,
            border_width=1,
            border_color=COLORS["border"]
        ).pack(side="left", padx=(5, 10))
        ctk.CTkButton(
            add_frame,
            text="添加",
            width=60,
            command=self._add_uuid_mapping,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"]
        ).pack(side="left")
        
        # 映射列表
        self.uuid_listbox = ctk.CTkTextbox(uuid_card, height=100)
        self.uuid_listbox.pack(fill="x", padx=20, pady=(5, 15))
        self._update_uuid_list()
        
        ctk.CTkButton(
            uuid_card,
            text="🗑️ 清空所有映射",
            width=120,
            command=self._clear_uuid_mappings,
            fg_color=COLORS["error"],
            hover_color="#DC2626"
        ).pack(anchor="e", padx=20, pady=(0, 10))