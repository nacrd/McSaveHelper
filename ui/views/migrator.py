"""批量迁移视图 (整合 LeftPanelMixin + RightPanelMixin)"""
import customtkinter as ctk
from typing import Any
from ui.constants import COLORS


class MigratorView(ctk.CTkFrame):
    """迁移工具主视图，包含左右两个面板"""
    
    def __init__(self, master: Any, controller: Any, **kwargs) -> None:
        """
        初始化迁移视图
        
        Args:
            master: 父容器
            controller: 拥有 LeftPanelMixin 和 RightPanelMixin 的控制器 (通常是 App 实例)
        """
        # 从 kwargs 中移除 fg_color，避免重复传递
        fg_color = kwargs.pop("fg_color", "transparent")
        super().__init__(master, fg_color=fg_color, **kwargs)
        self.controller = controller
        self._build_ui()
    
    def _build_ui(self) -> None:
        """构建左右面板"""
        # 左右两列容器
        left_panel = ctk.CTkFrame(self, fg_color="transparent")
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 18))
        right_panel = ctk.CTkFrame(self, fg_color="transparent")
        right_panel.pack(side="left", fill="both", expand=True)
        
        # 调用控制器的 mixin 方法构建面板
        self.controller._build_left_panel(left_panel)
        self.controller._build_right_panel(right_panel)