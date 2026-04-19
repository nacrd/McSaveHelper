"""映射管理视图（数据仓库）"""
import customtkinter as ctk
from typing import Any, TYPE_CHECKING
from ui.constants import COLORS
from ui.widgets import UUIDMappingTable

if TYPE_CHECKING:
    from ui.app import App


class MappingsView(ctk.CTkFrame):
    """映射管理视图，作为自定义UUID映射的数据仓库"""

    def __init__(self, master: Any, controller: Any = None, **kwargs) -> None:
        # 确保背景透明，移除可能冲突的fg_color参数
        kwargs.pop('fg_color', None)
        super().__init__(master, fg_color="transparent", **kwargs)
        self.controller = controller  # App实例
        self._build_ui()

    def _build_ui(self) -> None:
        """构建UI，包含完整的UUID映射编辑器"""
        # 标题
        title = ctk.CTkLabel(
            self,
            text="🔗 UUID映射管理",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        title.pack(anchor="w", pady=(0, 24))

        # 说明文本
        description = ctk.CTkLabel(
            self,
            text="在此处管理自定义玩家名与UUID的映射关系。这些映射将用于批量迁移时的UUID替换。",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
            wraplength=800,
            justify="left"
        )
        description.pack(anchor="w", pady=(0, 32))

        # 可视化UUID映射编辑器
        self.uuid_table = UUIDMappingTable(
            self,
            mappings=getattr(self.controller, 'custom_uuid_mappings', {}),
            on_mappings_change=getattr(self.controller, '_on_uuid_mappings_change', None)
        )
        self.uuid_table.pack(fill="both", expand=True, padx=0, pady=(0, 20))

        # 底部提示
        hint = ctk.CTkLabel(
            self,
            text="提示：您可以通过“导入名单”批量导入映射，或手动添加每一行。\n"
                 "映射数据会实时保存到配置文件，并在迁移时根据首页开关决定是否启用。",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"],
            wraplength=800,
            justify="left"
        )
        hint.pack(anchor="w", pady=(10, 0))

    def refresh_mappings(self) -> None:
        """刷新表格中的数据（当外部修改映射后调用）"""
        if hasattr(self.controller, 'custom_uuid_mappings'):
            self.uuid_table.mappings = self.controller.custom_uuid_mappings
            self.uuid_table._load_mappings()