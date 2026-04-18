"""存档探险视图 - 可视化查看与编辑模块"""
import customtkinter as ctk
from typing import Any, Optional, List, Dict
from pathlib import Path
from tkinter import filedialog, messagebox

from ui.constants import COLORS
from ui.widgets import ModernCard, InventoryGrid, MCAHeatmap, NBTTreeView
from core.omni.world_session import WorldSession


class PlayerHUDCard(ModernCard):
    """玩家属性卡片，显示生命值、经验、坐标等"""
    
    def __init__(self, master: Any, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._build_ui()
        self._set_placeholder()
    
    def _build_ui(self) -> None:
        # 标题
        self.title_label = ctk.CTkLabel(
            self,
            text="玩家状态",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.title_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(20, 10))
        
        # 属性网格
        self.attributes = {}
        rows = [
            ("生命值", "health", "♥"),
            ("饥饿值", "food", "🍖"),
            ("经验等级", "level", "⭐"),
            ("氧气", "air", "🌊"),
            ("维度", "dimension", "🌍"),
            ("坐标", "pos", "📍"),
        ]
        for idx, (label, key, icon) in enumerate(rows):
            # 标签
            lbl = ctk.CTkLabel(
                self,
                text=f"{icon} {label}:",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_secondary"]
            )
            lbl.grid(row=idx+1, column=0, sticky="w", padx=(20, 10), pady=5)
            # 值
            val = ctk.CTkLabel(
                self,
                text="--",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=COLORS["accent_light"]
            )
            val.grid(row=idx+1, column=1, sticky="w", padx=(0, 20), pady=5)
            self.attributes[key] = val
        
        # 调整列权重
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
    
    def _set_placeholder(self) -> None:
        """设置占位符数据"""
        self.attributes["health"].configure(text="20 / 20")
        self.attributes["food"].configure(text="20 / 20")
        self.attributes["level"].configure(text="0")
        self.attributes["air"].configure(text="300")
        self.attributes["dimension"].configure(text="overworld")
        self.attributes["pos"].configure(text="0, 64, 0")
    
    def update_from_nbt(self, player_data: Any) -> None:
        """
        从玩家 NBT 数据更新显示
        
        Args:
            player_data: nbtlib.Compound 玩家数据
        """
        if player_data is None:
            return
        
        # 提取属性
        health = player_data.get("Health")
        if health is not None:
            self.attributes["health"].configure(text=f"{int(health)} / 20")
        
        food = player_data.get("foodLevel")
        if food is not None:
            self.attributes["food"].configure(text=f"{int(food)} / 20")
        
        level = player_data.get("XpLevel")
        if level is not None:
            self.attributes["level"].configure(text=str(int(level)))
        
        air = player_data.get("Air")
        if air is not None:
            self.attributes["air"].configure(text=str(int(air)))
        
        dimension = player_data.get("Dimension")
        if dimension is not None:
            dim_str = str(dimension)
            # 转换 ID 为可读名称
            if dim_str == "minecraft:overworld":
                self.attributes["dimension"].configure(text="overworld")
            elif dim_str == "minecraft:the_nether":
                self.attributes["dimension"].configure(text="nether")
            elif dim_str == "minecraft:the_end":
                self.attributes["dimension"].configure(text="end")
            else:
                self.attributes["dimension"].configure(text=dim_str)
        
        pos = player_data.get("Pos")
        if pos is not None and len(pos) >= 3:
            x = float(pos[0])
            y = float(pos[1])
            z = float(pos[2])
            self.attributes["pos"].configure(text=f"{x:.1f}, {y:.1f}, {z:.1f}")


class ExplorerView(ctk.CTkFrame):
    """存档探险视图 - 集成玩家看板、区块热力图、NBT树视图"""
    
    def __init__(self, master: Any, **kwargs) -> None:
        # 确保背景透明，移除可能冲突的fg_color参数
        kwargs.pop('fg_color', None)
        super().__init__(master, fg_color="transparent", **kwargs)
        self.world_session: Optional[WorldSession] = None
        self.current_uuid: Optional[str] = None
        self._build_ui()
    
    def _build_ui(self) -> None:
        # 顶部工具栏
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(20, 10))
        
        ctk.CTkLabel(
            toolbar,
            text="📂 存档探险家",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(side="left")
        
        # 世界路径标签
        self.world_path_label = ctk.CTkLabel(
            toolbar,
            text="未加载存档",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"]
        )
        self.world_path_label.pack(side="left", padx=(20, 0))
        
        # 加载存档按钮
        ctk.CTkButton(
            toolbar,
            text="加载存档",
            command=self._load_world,
            width=100
        ).pack(side="right", padx=(10, 0))
        
        # 主选项卡
        self.tabview = ctk.CTkTabview(self, fg_color="transparent", border_width=1, border_color=COLORS["border"])
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        # 玩家标签页
        self.player_tab = self.tabview.add("玩家")
        self._build_player_tab()
        
        # 区块标签页
        self.region_tab = self.tabview.add("区块")
        self._build_region_tab()
        
        # NBT标签页
        self.nbt_tab = self.tabview.add("NBT")
        self._build_nbt_tab()
        
        # 日志区域
        log_frame = ctk.CTkFrame(self, fg_color="transparent")
        log_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        ctk.CTkLabel(
            log_frame,
            text="📜 日志",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w")
        
        self.log_text = ctk.CTkTextbox(
            log_frame,
            height=80,
            font=ctk.CTkFont(family="Cascadia Code", size=11),
            fg_color=COLORS["log_bg"],
            border_width=1,
            border_color=COLORS["log_border"],
            corner_radius=8,
        )
        self.log_text.pack(fill="x", pady=(10, 0))
        self.log_text.insert("1.0", "等待加载存档...")
        self.log_text.configure(state="disabled")
    
    def _build_player_tab(self) -> None:
        """构建玩家标签页内容"""
        # 左侧玩家面板
        left_panel = ctk.CTkFrame(self.player_tab, fg_color="transparent", width=300)
        left_panel.pack(side="left", fill="y", padx=(0, 20))
        
        # 玩家选择器
        ctk.CTkLabel(
            left_panel,
            text="选择玩家",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", pady=(0, 10))
        
        self.player_selector = ctk.CTkComboBox(
            left_panel,
            values=[],
            state="disabled",
            command=self._on_player_selected
        )
        self.player_selector.pack(fill="x", pady=(0, 20))
        
        # 玩家属性卡片
        self.hud_card = PlayerHUDCard(left_panel)
        self.hud_card.pack(fill="x", pady=(0, 20))
        
        # 右侧背包面板
        right_panel = ctk.CTkFrame(self.player_tab, fg_color="transparent")
        right_panel.pack(side="right", fill="both", expand=True)
        
        ctk.CTkLabel(
            right_panel,
            text="物品栏",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", pady=(0, 10))
        
        self.inventory_grid = InventoryGrid(right_panel, slot_size=50)
        self.inventory_grid.pack(fill="both", expand=True)
    
    def _build_region_tab(self) -> None:
        """构建区块标签页内容"""
        ctk.CTkLabel(
            self.region_tab,
            text="区域热力图（根据文件大小着色）",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", pady=(0, 10))
        
        # 热力图控件
        self.heatmap = MCAHeatmap(self.region_tab, cell_size=24)
        self.heatmap.pack(fill="both", expand=True, pady=(0, 20))
        
        # 热力图工具栏
        toolbar = ctk.CTkFrame(self.region_tab, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 10))
        
        ctk.CTkButton(
            toolbar,
            text="刷新热力图",
            command=self._refresh_heatmap,
            width=120
        ).pack(side="left", padx=(0, 10))
        
        ctk.CTkButton(
            toolbar,
            text="清空选择",
            command=self.heatmap.clear_selection,
            width=120
        ).pack(side="left", padx=(0, 10))
        
        ctk.CTkLabel(
            toolbar,
            text="点击单元格选择区域，再次点击取消选择",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"]
        ).pack(side="left", padx=(20, 0))
    
    def _build_nbt_tab(self) -> None:
        """构建 NBT 标签页内容"""
        ctk.CTkLabel(
            self.nbt_tab,
            text="NBT 树状查看器（支持搜索与编辑）",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", pady=(0, 10))
        
        # 搜索栏
        search_frame = ctk.CTkFrame(self.nbt_tab, fg_color="transparent")
        search_frame.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(
            search_frame,
            text="搜索：",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        ).pack(side="left", padx=(0, 5))
        
        self.nbt_search_entry = ctk.CTkEntry(search_frame, placeholder_text="输入键名或值...")
        self.nbt_search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ctk.CTkButton(
            search_frame,
            text="搜索",
            command=self._search_nbt,
            width=80
        ).pack(side="left")
        
        # NBT 树视图
        self.nbt_tree = NBTTreeView(self.nbt_tab)
        self.nbt_tree.pack(fill="both", expand=True)
    
    def _log(self, message: str) -> None:
        """添加日志"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"\n{message}")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
    
    def _load_world(self) -> None:
        """加载存档"""
        path = filedialog.askdirectory(title="选择 Minecraft 存档目录")
        if not path:
            return
        try:
            session = WorldSession(Path(path))
            self.set_world_session(session)
            self._log(f"已加载存档: {path}")
        except Exception as e:
            self._log(f"加载失败: {e}")
            messagebox.showerror("加载错误", f"无法加载存档:\n{e}")
    
    def _refresh_heatmap(self) -> None:
        """刷新热力图数据"""
        if self.world_session:
            region_files = self.world_session._region_files  # 临时访问内部属性
            self.heatmap.set_region_files(region_files)
            self._log("热力图已刷新")
        else:
            self._log("请先加载存档")
    
    def _search_nbt(self) -> None:
        """搜索 NBT 树"""
        query = self.nbt_search_entry.get().strip()
        if query:
            self.nbt_tree.search(query)
            self._log(f"搜索 NBT: {query}")
    
    def _on_player_selected(self, uuid: str) -> None:
        """当玩家被选择时更新显示"""
        if not self.world_session or uuid == "":
            return
        self.current_uuid = uuid
        player_data = self.world_session.get_player_data(uuid)
        if player_data:
            self.hud_card.update_from_nbt(player_data)
            # 提取背包数据
            inventory = self._extract_inventory(player_data)
            self.inventory_grid.set_inventory(inventory)
            # 加载 NBT 树
            self.nbt_tree.load_nbt(player_data)
            self._log(f"已加载玩家 {uuid} 的数据")
        else:
            self._log(f"无法加载玩家 {uuid} 的数据")
    
    def _extract_inventory(self, player_data: Any) -> List[Dict[str, Any]]:
        """
        从玩家数据中提取背包物品列表
        
        Args:
            player_data: nbtlib.Compound 玩家数据
        
        Returns:
            物品字典列表，每个字典包含 slot, id, count, tag
        """
        items = []
        # 尝试获取 Inventory 标签（1.12.2及更早版本）
        inventory = player_data.get("Inventory")
        if inventory is not None and isinstance(inventory, list):
            for slot in inventory:
                try:
                    slot_id = slot.get("Slot", -1)
                    item_id = slot.get("id", "")
                    count = slot.get("Count", 1)
                    tag = slot.get("tag")
                    if item_id:
                        items.append({
                            "slot": int(slot_id),
                            "id": str(item_id),
                            "count": int(count),
                            "tag": tag
                        })
                except Exception:
                    pass
        # TODO: 支持 1.13+ 的物品格式
        return items
    
    def set_world_session(self, session: WorldSession) -> None:
        """设置当前世界会话并更新 UI"""
        self.world_session = session
        self.world_path_label.configure(
            text=f"存档: {session.world_path.name}"
        )
        uuids = session.get_player_uuids()
        self.player_selector.configure(
            values=uuids,
            state="readonly" if uuids else "disabled"
        )
        if uuids:
            self.player_selector.set(uuids[0])
            self._on_player_selected(uuids[0])
        # 刷新热力图
        self._refresh_heatmap()
        self._log(f"已加载存档，发现 {len(uuids)} 个玩家")
