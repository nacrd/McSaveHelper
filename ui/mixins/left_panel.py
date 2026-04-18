"""左侧面板混入类"""
import customtkinter as ctk
from typing import Any, TYPE_CHECKING

from ui.constants import COLORS
from ui.widgets import TerminalLikeTextbox, ModernEntry, ModernButton
from core.i18n import t

if TYPE_CHECKING:
    from ui.mixins.common import CommonUIMixin


class LeftPanelMixin:
    """提供左侧面板构建方法"""
    
    if TYPE_CHECKING:
        src_path: ctk.StringVar
        dest_path: ctk.StringVar
        world_name: ctk.StringVar
        batch_dir_path: ctk.StringVar
        manual_names: ctk.StringVar
        batch_frame: ctk.CTkFrame
        batch_result_label: ctk.CTkLabel
        log: TerminalLikeTextbox
        convert_platform: ctk.StringVar
        
        def choose_src(self) -> None: ...
        def choose_dest(self) -> None: ...
        def choose_batch_dir(self) -> None: ...
        def scan_batch_worlds(self) -> None: ...
        def _toggle_batch_mode(self) -> None: ...
        def clear_log(self) -> None: ...
        
        def _create_card(self, parent: Any) -> Any: ...
        def _add_section_title(self, parent: Any, text: str, icon_only: bool = False) -> None: ...
        def _add_labeled_entry(self, parent: Any, label_text: str, var: Any, placeholder: str, browse_cmd: Any) -> None: ...
    
    def _build_left_panel(self, parent: Any) -> None:
        """构建现代化左侧面板"""
        # 目录设置
        dir_card = self._create_card(parent)
        dir_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(dir_card, t("left_panel.archive_config", "📁 存档目录配置"), icon_only=False)
        
        self._add_labeled_entry(
            dir_card,
            t("left_panel.client_archive", "客户端存档"),
            self.src_path,
            t("left_panel.placeholder_select_world", "选择世界文件夹 (包含 level.dat)"),
            self.choose_src
        )
        self._add_labeled_entry(
            dir_card,
            t("left_panel.server_root", "服务端根目录"),
            self.dest_path,
            t("left_panel.placeholder_default_dir", "默认为程序当前目录"),
            self.choose_dest
        )
        
        name_frame = ctk.CTkFrame(dir_card, fg_color="transparent")
        name_frame.pack(fill="x", padx=20, pady=(8, 18))
        ctk.CTkLabel(
            name_frame,
            text=t("left_panel.world_folder_name", "世界文件夹名"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", pady=(0, 6))
        ModernEntry(
            name_frame,
            textvariable=self.world_name,
            placeholder_text=t("left_panel.placeholder_world_name", "例如: world"),
            height=38,
        ).pack(fill="x")
        
        # 批量处理目录选择
        self.batch_frame = ctk.CTkFrame(dir_card, fg_color="transparent")
        self.batch_frame.pack(fill="x", padx=20, pady=(8, 0))
        ctk.CTkLabel(
            self.batch_frame,
            text=t("left_panel.batch_archive_dir", "批量存档目录"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", pady=(0, 6))
        batch_entry_frame = ctk.CTkFrame(self.batch_frame, fg_color="transparent")
        batch_entry_frame.pack(fill="x")
        ModernEntry(
            batch_entry_frame,
            textvariable=self.batch_dir_path,
            placeholder_text=t("left_panel.placeholder_batch_dir", "选择包含多个世界存档的目录"),
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ModernButton(
            batch_entry_frame,
            text=t("left_panel.browse", "📂 浏览"),
            width=90,
            height=38,
            command=self.choose_batch_dir,
            fg_color=COLORS["bg_secondary"],
            hover_color=COLORS["border_light"],
            text_color=COLORS["text_primary"]
        ).pack(side="right")
        ModernButton(
            batch_entry_frame,
            text=t("left_panel.scan", "🔍 扫描"),
            width=90,
            height=38,
            command=self.scan_batch_worlds,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"]
        ).pack(side="right", padx=(0, 10))
        
        # 批量扫描结果
        self.batch_result_label = ctk.CTkLabel(
            self.batch_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"]
        )
        self.batch_result_label.pack(anchor="w", pady=(6, 0))
        
        # 隐藏批量处理相关控件，直到启用批量模式
        self._toggle_batch_mode()
        
        # 手动玩家名
        manual_card = self._create_card(parent)
        manual_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(manual_card, "👥 手动指定玩家 (选填)", icon_only=False)
        ModernEntry(
            manual_card,
            textvariable=self.manual_names,
            placeholder_text="多个玩家用英文逗号分隔，例如: Steve, Alex",
            height=38,
        ).pack(fill="x", padx=20, pady=(8, 18))
        
        # 转换选项
        convert_card = self._create_card(parent)
        convert_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(convert_card, "🔄 存档转换 (实验性)", icon_only=False)
        
        # 平台选择
        platform_frame = ctk.CTkFrame(convert_card, fg_color="transparent")
        platform_frame.pack(fill="x", padx=20, pady=(8, 10))
        ctk.CTkLabel(
            platform_frame,
            text="目标平台:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(side="left", padx=(0, 10))
        self.convert_platform = ctk.StringVar(value="java")
        platform_menu = ctk.CTkOptionMenu(
            platform_frame,
            values=["Java", "Bedrock"],
            variable=self.convert_platform,
            width=120,
            height=32,
            fg_color=COLORS["bg_secondary"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"]
        )
        platform_menu.pack(side="left")
        
        # 转换按钮
        convert_button = ModernButton(
            convert_card,
            text="🚀 开始转换",
            height=38,
            command=self._perform_conversion,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"]
        )
        convert_button.pack(fill="x", padx=20, pady=(0, 18))
        
        # 日志区域
        log_header = ctk.CTkFrame(parent, fg_color="transparent")
        log_header.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            log_header,
            text="📋 运行日志",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(side="left")
        ModernButton(
            log_header,
            text="🗑️ 清空",
            width=80,
            height=32,
            command=self.clear_log,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["border_light"],
            text_color=COLORS["text_secondary"]
        ).pack(side="right")
        
        self.log = TerminalLikeTextbox(parent, height=220)
        self.log.pack(fill="both", expand=True)

    def _perform_conversion(self) -> None:
        """
        执行存档转换操作。
        """
        # 获取目标平台
        platform = self.convert_platform.get().lower()
        # 检查是否有源路径
        src = self.src_path.get()
        if not src:
            self.log.add_line("❌ 请先选择客户端存档路径", "ERROR")
            return
        from pathlib import Path
        from core.omni.world_session import WorldSession
        try:
            session = WorldSession(Path(src), log=self.log.add_line)
            session.queue_conversion(target_platform=platform)
            # 提交到临时目录（示例）
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "converted"
                success = session.commit(dest)
                if success:
                    self.log.add_line(f"✅ 转换成功，结果保存在 {dest}", "SUCCESS")
                else:
                    self.log.add_line("❌ 转换失败，请查看日志", "ERROR")
        except Exception as e:
            self.log.add_line(f"❌ 转换过程发生错误: {e}", "ERROR")