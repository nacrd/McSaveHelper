"""Explorer View - 存档浏览器"""
import flet as ft
import json
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Set, Tuple
from pathlib import Path

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field
from app.ui.components.cards import card

if TYPE_CHECKING:
    from app.application import Application

from core.omni.world_session import WorldSession, WorldInfo


def _safe_update(control: ft.Control) -> None:
    """安全更新控件，若控件未挂载到页面则静默跳过"""
    try:
        control.update()
    except RuntimeError:
        pass


class WorldInfoPanel(ft.Column):
    """存档信息展示面板"""
    
    def __init__(self, t_cb=None) -> None:
        super().__init__(spacing=8)
        self._t = t_cb or (lambda k, d="", **kw: d)
        self._info_text = ft.Text(
            "请先加载存档", 
            size=13, 
            color=THEME.text_muted,
            text_align=ft.TextAlign.CENTER
        )
        self.controls = [
            ft.Text(
                "存档信息", 
                size=16, 
                weight=ft.FontWeight.BOLD, 
                color=THEME.text_primary
            ),
            self._info_text
        ]
    
    def update_info(self, world_info: Optional[WorldInfo]) -> None:
        """更新存档信息显示"""
        if world_info is None:
            self._info_text.value = "未找到存档信息"
            self._info_text.color = THEME.text_muted
            _safe_update(self)
            return
        
        info_lines = []
        if world_info.level_name:
            info_lines.append(f"🏷️ 存档名称: {world_info.level_name}")
        if world_info.version_name:
            info_lines.append(f"📦 版本: {world_info.version_name} ({world_info.version})")
        else:
            info_lines.append(f"📦 版本 ID: {world_info.version}")
        
        game_type_map = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}
        if world_info.game_type is not None:
            game_type_str = game_type_map.get(world_info.game_type, str(world_info.game_type))
            info_lines.append(f"🎮 游戏模式: {game_type_str}")
        
        if world_info.spawn_x is not None:
            info_lines.append(f"📍 出生点: ({world_info.spawn_x}, {world_info.spawn_y}, {world_info.spawn_z})")
        
        self._info_text.value = "\n".join(info_lines)
        self._info_text.color = THEME.text_primary
        _safe_update(self)


class PlayerHUDCard(ft.Column):
    """玩家状态快速视图"""

    def __init__(self, t_cb=None) -> None:
        super().__init__(spacing=8)
        self._t = t_cb or (lambda k, d="", **kw: d)
        self._attrs: Dict[str, ft.Text] = {}
        
        rows_data = [
            ("health", "生命值", "♥"),
            ("food", "饥饿值", "🍖"),
            ("level", "经验等级", "⭐"),
            ("air", "氧气", "🌊"),
            ("dimension", "维度", "🌍"),
            ("pos", "坐标", "📍"),
        ]
        
        self.controls.append(
            ft.Text("玩家状态", size=16, weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        
        for key, label_text, icon in rows_data:
            lbl = ft.Text(f"{icon} {label_text}:", size=13, color=THEME.text_secondary)
            val = ft.Text("--", size=13, weight=ft.FontWeight.BOLD, color=THEME.accent_light)
            self._attrs[key] = val
            self.controls.append(ft.Row([lbl, val], spacing=10))

    def update_from_nbt(self, player_data: Any) -> None:
        if player_data is None:
            return
        try:
            h = player_data.get("Health")
            if h is not None:
                self._attrs["health"].value = f"{int(h)} / 20"
            f = player_data.get("foodLevel")
            if f is not None:
                self._attrs["food"].value = f"{int(f)} / 20"
            lvl = player_data.get("XpLevel")
            if lvl is not None:
                self._attrs["level"].value = str(int(lvl))
            a = player_data.get("Air")
            if a is not None:
                self._attrs["air"].value = str(int(a))
            dim = player_data.get("Dimension")
            if dim is not None:
                ds = str(dim).lower()
                if "overworld" in ds:
                    self._attrs["dimension"].value = "主世界"
                elif "nether" in ds:
                    self._attrs["dimension"].value = "下界"
                elif "end" in ds:
                    self._attrs["dimension"].value = "末地"
                else:
                    self._attrs["dimension"].value = ds
            pos = player_data.get("Pos")
            if pos is not None and len(pos) >= 3:
                self._attrs["pos"].value = f"{float(pos[0]):.1f}, {float(pos[1]):.1f}, {float(pos[2]):.1f}"
        except Exception:
            pass
        _safe_update(self)


class InventoryGrid(ft.GridView):
    """36 格物品栏网格"""

    def __init__(self, slot_size: int = 48) -> None:
        super().__init__(runs_count=9, max_extent=slot_size, spacing=2, child_aspect_ratio=1.0)
        self._slots: List[ft.Container] = []
        for _ in range(36):
            s = ft.Container(
                width=slot_size, height=slot_size,
                bgcolor=THEME.bg_card,
                border=ft.Border(left=ft.BorderSide(1, THEME.border_subtle), top=ft.BorderSide(1, THEME.border_subtle), right=ft.BorderSide(1, THEME.border_subtle), bottom=ft.BorderSide(1, THEME.border_subtle)),
                border_radius=6,
                content=ft.Text("", size=10, color=THEME.text_muted, text_align=ft.TextAlign.CENTER),
            )
            self._slots.append(s)
            self.controls.append(s)

    def set_inventory(self, inventory: List[Dict[str, Any]]) -> None:
        for s in self._slots:
            s.bgcolor = THEME.bg_card
            s.content = ft.Text("", size=10, color=THEME.text_muted, text_align=ft.TextAlign.CENTER)
        try:
            for item in inventory:
                si = item.get("slot", -1)
                if not 0 <= si < 36:
                    continue
                idx = 27 + si if si < 9 else si - 9
                c = item.get("count", 1)
                iid = item.get("id", "")
                dn = iid.split(":")[-1] if ":" in iid else iid
                lbl = f"{dn}\n×{c}" if c > 1 else dn
                s = self._slots[idx]
                s.bgcolor = THEME.bg_card_hover
                s.content = ft.Text(lbl, size=9, color=THEME.text_primary, text_align=ft.TextAlign.CENTER)
        except Exception:
            pass
        _safe_update(self)

    def clear(self) -> None:
        for s in self._slots:
            s.bgcolor = THEME.bg_card
            s.content = ft.Text("", size=10, color=THEME.text_muted, text_align=ft.TextAlign.CENTER)
        _safe_update(self)


class MCAHeatmap(ft.Container):
    """区域文件热力图 - 简单直观的区域查看器"""

    def __init__(self, cell_size: int = 28) -> None:
        super().__init__()
        self._cell_size = cell_size
        self._selected: Set[Tuple[int, int]] = set()
        self._cells: Dict[Tuple[int, int], ft.Container] = {}
        self._region_files: Dict[Tuple[int, int], Path] = {}
        
        # 统计信息
        self._stats_text = ft.Text(
            "加载存档后显示统计",
            size=12,
            color=THEME.text_muted
        )
        
        # 选中信息
        self._selection_text = ft.Text(
            "👆 点击方块查看详情",
            size=13,
            color=THEME.text_secondary
        )
        
        # 颜色图例
        legend_row = ft.Row([
            ft.Text("颜色说明：", size=12, color=THEME.text_secondary),
            ft.Container(width=16, height=16, bgcolor="#64B5F6", border_radius=2),  # 浅蓝
            ft.Text("小", size=11, color=THEME.text_muted),
            ft.Container(width=16, height=16, bgcolor="#1565C0", border_radius=2),  # 深蓝
            ft.Text("大", size=11, color=THEME.text_muted),
        ], spacing=6, alignment=ft.MainAxisAlignment.START)
        
        # 内部网格
        self._grid = ft.GridView(
            runs_count=0,
            max_extent=cell_size + 2,
            spacing=2,
            child_aspect_ratio=1.0,
            expand=True
        )
        
        # 组装布局
        content = ft.Column([
            ft.Text("🗺️ 世界区域地图", size=16, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            legend_row,
            ft.Container(height=8),  # 间距
            self._grid,
        ], spacing=8)
        
        self.content = content

    def set_region_files(self, region_files: Dict[Tuple[int, int], Path]) -> None:
        self._region_files = region_files
        self._cells.clear()
        self._selected.clear()
        
        # 计算统计信息
        if not region_files:
            self._stats_text.value = "⚠️ 未找到区域文件"
            self._selection_text.value = "👆 点击方块查看详情"
            self._grid.controls.clear()
            _safe_update(self)
            return
        
        # 计算文件大小统计
        sizes = []
        for path in region_files.values():
            try:
                sizes.append(path.stat().st_size)
            except Exception:
                pass
        
        total_size = sum(sizes) if sizes else 0
        avg_size = total_size // len(sizes) if sizes else 0
        max_size = max(sizes) if sizes else 0
        min_size = min(sizes) if sizes else 0
        
        # 格式化大小
        def format_size(size):
            kb = size / 1024
            mb = kb / 1024
            if mb >= 1:
                return f"{mb:.1f} MB"
            elif kb >= 1:
                return f"{kb:.1f} KB"
            else:
                return f"{size} B"
        
        stats_lines = [
            f"📊 区域文件总数：{len(region_files)} 个",
            f"💾 总大小：{format_size(total_size)}",
            f"📈 平均大小：{format_size(avg_size)}",
            f"🔍 最小：{format_size(min_size)} | 最大：{format_size(max_size)}"
        ]
        self._stats_text.value = "\n".join(stats_lines)
        self._selection_text.value = "👆 点击方块查看详情"
        
        # 构建网格
        self._grid.controls.clear()
        xs = [c[0] for c in region_files]
        zs = [c[1] for c in region_files]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        
        # 记录全局最大最小值用于颜色映射
        self._global_min_size = min_size
        self._global_max_size = max_size if max_size > 0 else 1
        
        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                cell = self._create_cell((x, z), region_files.get((x, z)))
                self._cells[(x, z)] = cell
                self._grid.controls.append(cell)
        
        _safe_update(self)

    def _create_cell(self, coord: Tuple[int, int], path: Optional[Path]) -> ft.Container:
        """创建单个区域方块"""
        # 根据相对大小计算颜色
        bg = self._get_color_for_path(path)
        
        def on_click(e):
            try:
                # 切换选中状态
                if coord in self._selected:
                    self._selected.remove(coord)
                    cell.border = ft.Border(
                        left=ft.BorderSide(1, THEME.border_subtle),
                        top=ft.BorderSide(1, THEME.border_subtle),
                        right=ft.BorderSide(1, THEME.border_subtle),
                        bottom=ft.BorderSide(1, THEME.border_subtle)
                    )
                else:
                    self._selected.add(coord)
                    cell.border = ft.Border(
                        left=ft.BorderSide(2, THEME.accent),
                        top=ft.BorderSide(2, THEME.accent),
                        right=ft.BorderSide(2, THEME.accent),
                        bottom=ft.BorderSide(2, THEME.accent)
                    )
                
                # 更新选中信息显示
                self._update_selection_info(coord, path)
                _safe_update(cell)
                _safe_update(self)
            except Exception:
                pass
        
        cell = ft.Container(
            width=self._cell_size,
            height=self._cell_size,
            bgcolor=bg,
            border=ft.Border(
                left=ft.BorderSide(1, THEME.border_subtle),
                top=ft.BorderSide(1, THEME.border_subtle),
                right=ft.BorderSide(1, THEME.border_subtle),
                bottom=ft.BorderSide(1, THEME.border_subtle)
            ),
            border_radius=3,
            on_click=on_click,
            tooltip=f"区域 ({coord[0]}, {coord[1]})"
        )
        return cell

    def _get_color_for_path(self, path: Optional[Path]) -> str:
        """根据文件大小获取颜色"""
        if path is None:
            return THEME.bg_card
        
        try:
            size = path.stat().st_size
            # 使用对数缩放让颜色分布更均匀
            import math
            min_s = max(1, self._global_min_size)
            max_s = max(1, self._global_max_size)
            
            # 对数缩放
            log_min = math.log(max(1, min_s))
            log_max = math.log(max(1, max_s))
            log_size = math.log(max(1, size))
            
            # 归一化到 0-1
            if log_max > log_min:
                ratio = (log_size - log_min) / (log_max - log_min)
            else:
                ratio = 0.5
            ratio = max(0, min(1, ratio))
            
            # 蓝色渐变：浅蓝 -> 深蓝
            # 浅色：RGB(100, 181, 246) #64B5F6
            # 深色：RGB(21, 101, 192)  #1565C0
            r = int(100 + ratio * (21 - 100))
            g = int(181 + ratio * (101 - 181))
            b = int(246 + ratio * (192 - 246))
            
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return THEME.bg_card

    def _update_selection_info(self, coord: Tuple[int, int], path: Optional[Path]) -> None:
        """更新选中区域的信息显示"""
        def format_size(size):
            kb = size / 1024
            mb = kb / 1024
            if mb >= 1:
                return f"{mb:.2f} MB"
            elif kb >= 1:
                return f"{kb:.2f} KB"
            else:
                return f"{size} B"
        
        if path is None:
            self._selection_text.value = f"⚠️ 区域 ({coord[0]}, {coord[1]}) 不存在"
            self._selection_text.color = THEME.warning
        else:
            try:
                size = path.stat().st_size
                # 计算相对于平均的大小
                avg_size = sum(p.stat().st_size for p in self._region_files.values() if p) / len(self._region_files)
                ratio = size / avg_size if avg_size > 0 else 1
                
                if ratio > 1.5:
                    activity = "🔥 非常活跃"
                elif ratio > 1.0:
                    activity = "📗 较活跃"
                elif ratio > 0.5:
                    activity = "📙 一般"
                else:
                    activity = "📕 不活跃"
                
                self._selection_text.value = (
                    f"✅ 已选择区域 ({coord[0]}, {coord[1]})\n"
                    f"   💾 文件大小：{format_size(size)}\n"
                    f"   {activity}（相对于平均大小 {ratio:.1f}x）"
                )
                self._selection_text.color = THEME.accent_light
            except Exception:
                self._selection_text.value = f"❓ 区域 ({coord[0]}, {coord[1]}) - 无法读取信息"
                self._selection_text.color = THEME.error

    def get_selected(self) -> List[Tuple[int, int]]:
        return list(self._selected)

    def clear_selection(self) -> None:
        for c in self._selected:
            if c in self._cells:
                self._cells[c].border = ft.Border(
                    left=ft.BorderSide(1, THEME.border_subtle),
                    top=ft.BorderSide(1, THEME.border_subtle),
                    right=ft.BorderSide(1, THEME.border_subtle),
                    bottom=ft.BorderSide(1, THEME.border_subtle)
                )
        self._selected.clear()
        self._selection_text.value = "👆 点击方块查看详情"
        self._selection_text.color = THEME.text_secondary
        _safe_update(self)


class NBTTreeView(ft.Column):
    """NBT 树状视图 - 可展开/折叠的 NBT 数据浏览器"""

    MAX_DEPTH = 20
    MAX_CHILDREN = 500

    _TYPE_INFO = {
        "Compound":  ("📦", "Compound",  THEME.accent_light),
        "List":      ("📋", "List",      THEME.accent_light),
        "String":    ("🔤", "String",    THEME.terminal_green),
        "Int":       ("🔢", "Int",       THEME.terminal_cyan),
        "Long":      ("🔢", "Long",      THEME.terminal_cyan),
        "Byte":      ("🔵", "Byte",      THEME.terminal_blue),
        "Short":     ("🔢", "Short",     THEME.terminal_cyan),
        "Float":     ("📐", "Float",     THEME.terminal_purple),
        "Double":    ("📐", "Double",    THEME.terminal_purple),
        "IntArray":  ("🧮", "IntArray",  THEME.warning_light),
        "ByteArray": ("🧮", "ByteArray", THEME.warning_light),
    }

    def __init__(self) -> None:
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self._root_data: Any = None
        self._search_query: str = ""
        self._matched_keys: Set[str] = set()
        self._placeholder = ft.Text(
            "请选择玩家以加载 NBT 数据", size=13, color=THEME.text_muted
        )
        self.controls.append(self._placeholder)

    def load_nbt(self, nbt_data: Any) -> None:
        self._root_data = nbt_data
        self._search_query = ""
        self._matched_keys.clear()
        self._rebuild_tree()

    def search(self, query: str) -> None:
        self._search_query = query.strip().lower()
        self._matched_keys.clear()
        try:
            if self._search_query and self._root_data is not None:
                self._collect_matches(self._root_data, "")
        except Exception:
            pass
        self._rebuild_tree()

    def get_modified_data(self) -> Any:
        return self._root_data
    
    def export_json(self, path: str) -> bool:
        """导出 NBT 数据为 JSON 文件"""
        try:
            if self._root_data is None:
                return False
            
            def convert_to_serializable(obj):
                if hasattr(obj, 'value'):
                    return convert_to_serializable(obj.value)
                elif isinstance(obj, dict):
                    return {k: convert_to_serializable(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_to_serializable(item) for item in obj]
                elif isinstance(obj, (int, float, str, bool, type(None))):
                    return obj
                else:
                    return str(obj)
            
            serializable_data = convert_to_serializable(self._root_data)
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception:
            return False

    def _rebuild_tree(self) -> None:
        self.controls.clear()
        if self._root_data is None:
            self.controls.append(self._placeholder)
            _safe_update(self)
            return
        try:
            nodes = self._build_nodes(self._root_data, "", depth=0)
            if not nodes:
                self.controls.append(
                    ft.Text("（空 NBT 数据）", size=13, color=THEME.text_muted)
                )
            else:
                self.controls.extend(nodes)
        except Exception:
            self.controls.append(
                ft.Text("解析 NBT 数据失败", size=13, color=THEME.error)
            )
        _safe_update(self)

    def _build_nodes(self, data: Any, path_prefix: str, depth: int) -> List:
        if depth > self.MAX_DEPTH:
            return [ft.Text("  " * depth + "…（深度已达上限）", size=12, color=THEME.text_muted)]

        nodes: List = []
        try:
            if isinstance(data, dict):
                items = list(data.items())
                if len(items) > self.MAX_CHILDREN:
                    items = items[:self.MAX_CHILDREN]
                for key, value in items:
                    child_path = f"{path_prefix}.{key}" if path_prefix else key
                    nodes.append(self._build_node(key, value, child_path, depth))
                if len(data) > self.MAX_CHILDREN:
                    nodes.append(
                        ft.Text(
                            "  " * depth + f"…（省略 {len(data) - self.MAX_CHILDREN} 项）",
                            size=12, color=THEME.text_muted,
                        )
                    )
            elif isinstance(data, list):
                length = len(data)
                show_count = min(length, self.MAX_CHILDREN)
                for i in range(show_count):
                    child_path = f"{path_prefix}[{i}]"
                    nodes.append(self._build_node(f"[{i}]", data[i], child_path, depth))
                if length > self.MAX_CHILDREN:
                    nodes.append(
                        ft.Text(
                            "  " * depth + f"…（省略 {length - self.MAX_CHILDREN} 项）",
                            size=12, color=THEME.text_muted,
                        )
                    )
        except Exception:
            pass
        return nodes

    def _build_node(self, key: str, value: Any, path: str, depth: int) -> ft.Control:
        type_name = self._get_type_name(value)
        icon, label, val_color = self._TYPE_INFO.get(
            type_name, ("❓", type_name, THEME.text_muted)
        )
        is_highlighted = path.lower() in self._matched_keys

        if isinstance(value, dict):
            count = len(value) if hasattr(value, '__len__') else 0
            subtitle = f"{count} 项"
            title_row = ft.Row([
                ft.Text(icon, size=13),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(f"({label})", size=11, color=THEME.text_muted),
                ft.Text(subtitle, size=11, color=THEME.text_secondary),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            children = self._build_nodes(value, path, depth + 1)
            return ft.ExpansionTile(
                title=title_row,
                controls=children,
                expanded=(depth < 1 or is_highlighted),
                bgcolor=ft.Colors.TRANSPARENT,
                collapsed_bgcolor=ft.Colors.TRANSPARENT,
                tile_padding=ft.Padding(left=depth * 16, top=2, bottom=2, right=8),
                controls_padding=0,
                dense=True,
            )
        elif isinstance(value, list):
            length = len(value) if hasattr(value, '__len__') else 0
            list_type = self._detect_list_subtype(value)
            subtitle = f"{length} 项"
            type_hint = f"<{list_type}>" if list_type else ""
            title_row = ft.Row([
                ft.Text(icon, size=13),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(f"({label}{type_hint})", size=11, color=THEME.text_muted),
                ft.Text(subtitle, size=11, color=THEME.text_secondary),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            children = self._build_nodes(value, path, depth + 1)
            return ft.ExpansionTile(
                title=title_row,
                controls=children,
                expanded=(depth < 1 or is_highlighted),
                bgcolor=ft.Colors.TRANSPARENT,
                collapsed_bgcolor=ft.Colors.TRANSPARENT,
                tile_padding=ft.Padding(left=depth * 16, top=2, bottom=2, right=8),
                controls_padding=0,
                dense=True,
            )
        else:
            raw = self._format_primitive(value, type_name)
            display_val = raw if len(raw) <= 120 else raw[:117] + "…"
            title_row = ft.Row([
                ft.Text(icon, size=13),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(f"({label})", size=11, color=THEME.text_muted),
                ft.Text(display_val, size=13, color=val_color,
                        overflow=ft.TextOverflow.ELLIPSUS, expand=True),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            return ft.Container(
                content=title_row,
                padding=ft.Padding(left=depth * 16 + 28, top=2, bottom=2, right=8),
            )

    @staticmethod
    def _get_type_name(value: Any) -> str:
        return type(value).__name__

    @staticmethod
    def _detect_list_subtype(lst: list) -> str:
        if not lst or len(lst) == 0:
            return ""
        return type(lst[0]).__name__ if lst else ""

    @staticmethod
    def _format_primitive(value: Any, type_name: str) -> str:
        try:
            if hasattr(value, 'value'):
                v = value.value
            else:
                v = value
            if type_name in ("IntArray", "ByteArray"):
                items = list(value)
                if len(items) <= 8:
                    return "[" + ", ".join(str(x) for x in items) + "]"
                return "[" + ", ".join(str(x) for x in items[:8]) + f", …] ({len(items)} 项)"
            if type_name == "String":
                s = str(v)
                return f'"{s}"'
            return str(v)
        except Exception:
            return str(value)

    def _collect_matches(self, data: Any, path_prefix: str) -> None:
        q = self._search_query
        try:
            if isinstance(data, dict):
                for key, value in data.items():
                    child_path = f"{path_prefix}.{key}" if path_prefix else key
                    if q in key.lower():
                        self._matched_keys.add(child_path.lower())
                    if isinstance(value, (dict, list)):
                        self._collect_matches(value, child_path)
                    else:
                        raw = str(getattr(value, 'value', value)).lower()
                        if q in raw:
                            self._matched_keys.add(child_path.lower())
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    child_path = f"{path_prefix}[{i}]"
                    if isinstance(item, (dict, list)):
                        self._collect_matches(item, child_path)
                    else:
                        raw = str(getattr(item, 'value', item)).lower()
                        if q in raw:
                            self._matched_keys.add(child_path.lower())
        except Exception:
            pass


class ExplorerView(ft.Column):
    """存档浏览器视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=0)
        self.expand = True
        self.app: "Application" = app
        self.world_session: Optional[WorldSession] = None
        self.current_uuid: Optional[str] = None
        self.player_uuid_map: Dict[str, str] = {}
        self._build()

    @property
    def _t(self):
        return self.app._t

    def _build(self) -> None:
        self.controls.clear()

        # 工具栏
        self._world_label = ft.Text(
            "未加载存档", size=12, color=THEME.text_muted,
        )
        toolbar = ft.Container(
            content=ft.Row([
                ft.Text("📂 存档浏览器", size=24, weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary),
                self._world_label,
                ft.Container(),
                btn_primary("加载存档", on_click=self._load_world),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(bottom=16),
        )

        # 标签页容器
        self._tab_world_info = ft.Container()
        self._tab_world_info.expand = True
        self._tab_player = ft.Container()
        self._tab_player.expand = True
        self._tab_region = ft.Container()
        self._tab_region.expand = True
        self._tab_nbt = ft.Container()
        self._tab_nbt.expand = True
        
        self._tabs_content = [
            self._tab_world_info, 
            self._tab_player, 
            self._tab_region, 
            self._tab_nbt
        ]
        self._tab_index = 0

        # 标签页按钮
        self._tab_labels_widgets: List[ft.Text] = []
        tab_label_conts: List[ft.Container] = []
        for idx, name in enumerate(["存档信息", "玩家", "区域", "NBT"]):
            lbl = ft.Text(name, size=14, weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary if idx == 0 else THEME.text_secondary)
            self._tab_labels_widgets.append(lbl)
            tab_label_conts.append(ft.Container(
                content=lbl,
                padding=ft.Padding(right=24, bottom=8),
                on_click=lambda e, i=idx: self._switch_tab(i),
            ))

        tab_labels_row = ft.Row(tab_label_conts, spacing=0)
        self._tab_indicator = ft.Container(height=2, bgcolor=THEME.accent)
        self._tab_bar = ft.Column([tab_labels_row, self._tab_indicator], spacing=0)
        self._content_box = ft.Container(content=self._tabs_content[0])
        self._content_box.expand = True

        self.controls.append(toolbar)
        col_tabs = ft.Column([self._tab_bar, self._content_box], spacing=8)
        col_tabs.expand = True
        self.controls.append(col_tabs)

        self._build_world_info_tab()
        self._build_player_tab()
        self._build_region_tab()
        self._build_nbt_tab()

    def _switch_tab(self, index: int) -> None:
        try:
            self._tab_index = index
            for i, lbl in enumerate(self._tab_labels_widgets):
                lbl.color = THEME.text_primary if i == index else THEME.text_secondary
            self._content_box.content = self._tabs_content[index]
            _safe_update(self._content_box)
            _safe_update(self._tab_bar)
        except Exception as e:
            self.app.handle_exception(e)

    def _build_world_info_tab(self) -> None:
        """构建存档信息标签页"""
        self._world_info_panel = WorldInfoPanel(self._t)
        
        # 存档统计信息
        self._stats_text = ft.Text(
            "等待加载存档...",
            size=13,
            color=THEME.text_muted
        )
        
        col = ft.Column([
            card(self._world_info_panel, padding=15),
            card(
                ft.Column([
                    ft.Text("存档统计", size=16, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    self._stats_text
                ], spacing=8),
                padding=15
            )
        ], spacing=10)
        col.expand = True
        
        self._tab_world_info.content = col

    def _build_player_tab(self) -> None:
        left = ft.Column(spacing=10, width=300)
        left.controls.append(
            ft.Text("选择玩家", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        self._player_dropdown = ft.Dropdown(
            options=[], on_select=self._on_player_selected,
            border_color=THEME.border_standard, text_size=13,
        )
        left.controls.append(self._player_dropdown)
        left.controls.append(
            btn_ghost("导入 usercache.json", height=30, on_click=self._import_usercache)
        )

        self._player_hud = PlayerHUDCard()
        self._hud_card = card(self._player_hud, padding=15)
        left.controls.append(self._hud_card)

        right = ft.Column(spacing=10)
        right.expand = True
        right.controls.append(
            ft.Text("物品栏", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        self._inventory = InventoryGrid(slot_size=50)
        right.controls.append(self._inventory)

        self._tab_player.content = ft.Row([left, ft.Container(width=20), right], expand=True)

    def _build_region_tab(self) -> None:
        """构建区域标签页 - 简单直观的世界地图"""
        self._heatmap = MCAHeatmap(cell_size=28)
        
        # 说明文字
        help_text = ft.Text(
            "💡 提示：每个方块代表一个 32×32 区块的区域，颜色越深表示玩家活动越频繁",
            size=12,
            color=THEME.text_muted,
            italic=True
        )
        
        # 统计卡片
        stats_card = card(
            ft.Column([
                ft.Text("📊 区域统计", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._heatmap._stats_text
            ], spacing=6),
            padding=12
        )
        
        # 操作按钮
        action_row = ft.Row([
            btn_primary("🔄 刷新", width=100, on_click=lambda e: self._refresh_heatmap()),
            btn_ghost("🗑️ 清空选择", width=100, on_click=lambda e: self._heatmap.clear_selection()),
        ], spacing=10)
        
        # 组装主布局
        main_content = ft.Column([
            help_text,
            ft.Container(height=8),
            self._heatmap,
        ], spacing=8)
        
        # 热力图容器
        heatmap_container = ft.Container(
            content=main_content,
            padding=15,
            bgcolor=THEME.bg_card,
            border_radius=12,
            expand=True
        )
        
        # 选中信息卡片
        selection_card = card(
            ft.Column([
                ft.Text("👆 点击详情", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._heatmap._selection_text
            ], spacing=6),
            padding=12
        )
        
        # 整体布局
        col = ft.Column([
            heatmap_container,
            ft.Container(height=12),
            selection_card,
            ft.Container(height=8),
            stats_card,
            ft.Container(height=8),
            action_row,
        ], spacing=0)
        col.expand = True
        
        self._tab_region.content = col

    def _build_nbt_tab(self) -> None:
        col = ft.Column(spacing=10)
        col.expand = True
        
        # 搜索栏
        search_row = ft.Row([
            ft.Text("🔍 搜索:", size=14, color=THEME.text_primary),
            text_field(
                label="输入搜索内容",
                width=300,
                on_change=self._on_nbt_search
            ),
            btn_ghost("导出 JSON", on_click=self._export_nbt_json)
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        
        col.controls.append(card(search_row, padding=10))
        col.controls.append(
            ft.Text("NBT 数据查看器", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        self._nbt_tree = NBTTreeView()
        c = ft.Container(content=self._nbt_tree)
        c.expand = True
        col.controls.append(c)
        self._tab_nbt.content = col

    def _load_world(self, e: ft.ControlEvent = None) -> None:
        try:
            path = self.app.pick_directory()
            if not path:
                return
            
            self.world_session = WorldSession(Path(path), log=self.app.log)
            self._world_label.value = f"已加载: {self.world_session.world_path.name}"
            _safe_update(self._world_label)

            # 更新存档信息面板
            world_info = self.world_session.get_world_info()
            self._world_info_panel.update_info(world_info)
            
            # 更新统计信息
            player_count = len(self.world_session.get_player_uuids())
            region_count = len(self.world_session._region_files)
            self._stats_text.value = f"👥 玩家数: {player_count}\n🗺️ 区域文件数: {region_count}"
            _safe_update(self._stats_text)

            # 获取完整的玩家名称映射
            player_names = self.world_session.get_player_names()

            # 填充玩家下拉列表
            players = []
            for uuid, name in player_names.items():
                display = name or uuid
                formatted = self.world_session._format_uuid_with_hyphens(uuid)
                players.append((formatted, display))
            self._player_dropdown.options = [
                ft.dropdown.Option(v[0], v[1]) for v in players
            ]
            _safe_update(self._player_dropdown)
            
            # 自动选择第一个玩家并加载其数据
            if players:
                first_player_uuid = players[0][0]
                self._player_dropdown.value = first_player_uuid
                _safe_update(self._player_dropdown)
                self._load_player_data(first_player_uuid)
            
            self._refresh_heatmap()
        except Exception as e:
            self.app.handle_exception(e, title="加载存档失败")

    def _on_player_selected(self, e: ft.ControlEvent) -> None:
        try:
            if not self.world_session or not e.control.value:
                return
            self._load_player_data(e.control.value)
        except Exception as e:
            self.app.handle_exception(e, title="加载玩家数据失败")
    
    def _load_player_data(self, uuid: str) -> None:
        """加载指定 UUID 的玩家数据"""
        try:
            if not self.world_session:
                return
            self.current_uuid = uuid
            player_data = self.world_session.load_player_data(uuid)
            self._player_hud.update_from_nbt(player_data)
            inv = self.world_session.get_player_inventory(uuid)
            self._inventory.set_inventory(inv)
            nbt = self.world_session.load_player_nbt(uuid)
            self._nbt_tree.load_nbt(nbt)
        except Exception as e:
            self.app.handle_exception(e, title="加载玩家数据失败")

    def _refresh_heatmap(self) -> None:
        try:
            if self.world_session:
                self._heatmap.set_region_files(self.world_session._region_files)
        except Exception as e:
            self.app.handle_exception(e, title="刷新热力图失败")

    def _import_usercache(self, e: ft.ControlEvent = None) -> None:
        try:
            path = self.app.pick_file(
                title="选择 usercache.json",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if path and self.world_session:
                imported = self.world_session.import_usercache(Path(path))
                if imported > 0:
                    # 重新获取玩家名称并刷新下拉列表
                    player_names = self.world_session.get_player_names()
                    players = []
                    for uuid, name in player_names.items():
                        display = name or uuid
                        formatted = self.world_session._format_uuid_with_hyphens(uuid)
                        players.append((formatted, display))
                    self._player_dropdown.options = [
                        ft.dropdown.Option(v[0], v[1]) for v in players
                    ]
                    _safe_update(self._player_dropdown)
                    self.app.info_dialog("成功", f"成功导入 {imported} 个玩家名称。")
                else:
                    self.app.info_dialog("提示", "未能导入任何玩家名称。")
        except Exception as e:
            self.app.handle_exception(e, title="导入 usercache 失败")
    
    def _on_nbt_search(self, e: ft.ControlEvent) -> None:
        try:
            self._nbt_tree.search(e.control.value or "")
        except Exception as e:
            self.app.handle_exception(e, title="搜索 NBT 失败")
    
    def _export_nbt_json(self, e: ft.ControlEvent) -> None:
        try:
            if not self._nbt_tree._root_data:
                self.app.warn_dialog("提示", "没有可导出的 NBT 数据")
                return
            
            path = self.app.save_file(
                title="保存 JSON 文件",
                default_ext=".json",
                file_types=[("JSON 文件 (*.json)", "*.json")]
            )
            if path:
                success = self._nbt_tree.export_json(path)
                if success:
                    self.app.info_dialog("成功", f"已导出到: {path}")
                else:
                    self.app.error_dialog("失败", "导出 JSON 失败")
        except Exception as e:
            self.app.handle_exception(e, title="导出 JSON 失败")
