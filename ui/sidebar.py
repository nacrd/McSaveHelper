"""侧边栏组件"""
import customtkinter as ctk
from typing import Any, Callable, List, Dict, Optional
from ui.constants import COLORS
from ui.widgets import ModernButton


class Sidebar(ctk.CTkFrame):
    """现代化侧边栏，包含多个选项卡按钮"""
    
    def __init__(
        self,
        master: Any,
        tabs: List[Dict[str, Any]],
        on_tab_select: Callable[[str], None],
        default_tab: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        初始化侧边栏

        Args:
            master: 父容器
            tabs: 选项卡列表，每个选项卡是一个字典，包含:
                - id: 唯一标识符
                - label: 显示文本
                - icon: 可选图标字符
            on_tab_select: 选项卡选择回调函数 (tab_id)
            default_tab: 默认选中的选项卡ID
        """
        super().__init__(
            master,
            fg_color=COLORS["bg_primary"],
            corner_radius=0,
            width=180,  # 侧边栏宽度
            **kwargs
        )
        self.tabs = tabs
        self.on_tab_select = on_tab_select
        self.selected_tab_id = default_tab or (tabs[0]["id"] if tabs else None)
        self.buttons: Dict[str, Dict[str, Any]] = {}
        
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建侧边栏UI"""
        # 标题
        title_frame = ctk.CTkFrame(self, fg_color="transparent", height=80)
        title_frame.pack(fill="x", padx=20, pady=(30, 20))
        ctk.CTkLabel(
            title_frame,
            text="MC Migrator",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["accent"]
        ).pack()
        ctk.CTkLabel(
            title_frame,
            text="Pro",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        ).pack()
        
        # 选项卡按钮
        for tab in self.tabs:
            self._add_tab_button(tab)
        
        # 填充空白区域
        ctk.CTkFrame(self, fg_color="transparent", height=0).pack(fill="x", expand=True)
        
        # 底部版本信息（可选）
        version_frame = ctk.CTkFrame(self, fg_color="transparent", height=40)
        version_frame.pack(fill="x", side="bottom", pady=20)
        ctk.CTkLabel(
            version_frame,
            text="v1.0.0",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_muted"]
        ).pack()
    
    def _add_tab_button(self, tab: Dict[str, Any]) -> None:
        """添加一个选项卡按钮"""
        btn_frame = ctk.CTkFrame(self, fg_color="transparent", height=50)
        btn_frame.pack(fill="x", padx=12, pady=4)
        
        # 按钮
        btn = ModernButton(
            btn_frame,
            text=f"  {tab.get('icon', '')} {tab['label']}",
            anchor="w",
            height=44,
            fg_color="transparent",
            hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_secondary"],
            command=lambda: self._select_tab(tab["id"])
        )
        btn.pack(fill="x", expand=True)
        
        # 选中状态指示器（左侧竖条）
        indicator = ctk.CTkFrame(btn_frame, width=4, fg_color="transparent", corner_radius=2)
        indicator.place(relx=0, rely=0.5, relheight=0.7, anchor="w")
        self.buttons[tab["id"]] = {"button": btn, "indicator": indicator}
        
        # 设置初始选中状态
        if tab["id"] == self.selected_tab_id:
            self._update_button_style(tab["id"], selected=True)
    
    def _select_tab(self, tab_id: str) -> None:
        """选择选项卡"""
        if tab_id == self.selected_tab_id:
            return
        # 更新之前选中的按钮样式
        if self.selected_tab_id:
            self._update_button_style(self.selected_tab_id, selected=False)
        # 更新新选中的按钮样式
        self.selected_tab_id = tab_id
        self._update_button_style(tab_id, selected=True)
        # 调用回调
        self.on_tab_select(tab_id)
    
    def _update_button_style(self, tab_id: str, selected: bool) -> None:
        """更新按钮样式"""
        btn_info = self.buttons.get(tab_id)
        if not btn_info:
            return
        btn = btn_info["button"]
        indicator = btn_info["indicator"]
        
        if selected:
            btn.configure(
                fg_color=COLORS["bg_card"],
                text_color=COLORS["text_primary"],
                hover_color=COLORS["bg_card_hover"]
            )
            indicator.configure(fg_color=COLORS["accent"])
        else:
            btn.configure(
                fg_color="transparent",
                text_color=COLORS["text_secondary"],
                hover_color=COLORS["bg_card_hover"]
            )
            indicator.configure(fg_color="transparent")
    
    def select_tab(self, tab_id: str) -> None:
        """外部调用以选择选项卡"""
        self._select_tab(tab_id)