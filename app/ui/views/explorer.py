"""Explorer View —— 存档探险家（世界检查仪表盘）"""
import flet as ft
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Set, Tuple
from pathlib import Path

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field
from app.ui.components.cards import card

if TYPE_CHECKING:
    from app.application import Application

from core.omni.world_session import WorldSession


# ═══════════════════════════════════════════════
#  内部组件
# ═══════════════════════════════════════════════

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
                self._attrs["dimension"].value = "overworld"
            elif "nether" in ds:
                self._attrs["dimension"].value = "nether"
            elif "end" in ds:
                self._attrs["dimension"].value = "end"
            else:
                self._attrs["dimension"].value = ds
        pos = player_data.get("Pos")
        if pos is not None and len(pos) >= 3:
            self._attrs["pos"].value = f"{float(pos[0]):.1f}, {float(pos[1]):.1f}, {float(pos[2]):.1f}"
        self.update()


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
        self.update()

    def clear(self) -> None:
        for s in self._slots:
            s.bgcolor = THEME.bg_card
            s.content = ft.Text("", size=10, color=THEME.text_muted, text_align=ft.TextAlign.CENTER)
        self.update()


class MCAHeatmap(ft.GridView):
    """区域文件热力图"""

    def __init__(self, cell_size: int = 24) -> None:
        super().__init__(runs_count=0, max_extent=cell_size + 2, spacing=1, child_aspect_ratio=1.0)
        self._cell_size = cell_size
        self._selected: Set[Tuple[int, int]] = set()
        self._cells: Dict[Tuple[int, int], ft.Container] = {}

    def set_region_files(self, region_files: Dict[Tuple[int, int], Path]) -> None:
        self.controls.clear()
        self._cells.clear()
        if not region_files:
            if self.page:
                self.update()
            return
        xs = [c[0] for c in region_files]
        zs = [c[1] for c in region_files]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)

        def make_cell(coord):
            path = region_files.get(coord)
            bg = self._color_for_file(path) if path else THEME.bg_card

            def click(e):
                if coord in self._selected:
                    self._selected.remove(coord)
                    cell.border = ft.Border(left=ft.BorderSide(1, THEME.border_subtle), top=ft.BorderSide(1, THEME.border_subtle), right=ft.BorderSide(1, THEME.border_subtle), bottom=ft.BorderSide(1, THEME.border_subtle))
                else:
                    self._selected.add(coord)
                    cell.border = ft.Border(left=ft.BorderSide(2, THEME.accent), top=ft.BorderSide(2, THEME.accent), right=ft.BorderSide(2, THEME.accent), bottom=ft.BorderSide(2, THEME.accent))
                self.update()

            cell = ft.Container(
                width=self._cell_size, height=self._cell_size,
                bgcolor=bg, border=ft.Border(left=ft.BorderSide(1, THEME.border_subtle), top=ft.BorderSide(1, THEME.border_subtle), right=ft.BorderSide(1, THEME.border_subtle), bottom=ft.BorderSide(1, THEME.border_subtle)),
                border_radius=2, on_click=click,
            )
            self._cells[coord] = cell
            return cell

        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                self.controls.append(make_cell((x, z)))
        self.update()

    @staticmethod
    def _color_for_file(path: Path) -> str:
        try:
            s = path.stat().st_size
            max_s = 10 * 1024 * 1024
            i = min(255, int(s / max_s * 255))
            r = min(255, 100 + i // 5)
            g = min(255, 150 + i // 8)
            b = min(255, 200 + i // 3)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return THEME.bg_card

    def get_selected(self) -> List[Tuple[int, int]]:
        return list(self._selected)

    def clear_selection(self) -> None:
        for c in self._selected:
            if c in self._cells:
                self._cells[c].border = ft.Border(left=ft.BorderSide(1, THEME.border_subtle), top=ft.BorderSide(1, THEME.border_subtle), right=ft.BorderSide(1, THEME.border_subtle), bottom=ft.BorderSide(1, THEME.border_subtle))
        self._selected.clear()
        self.update()


class NBTTreeView(ft.Column):
    """NBT 树状视图占位符"""

    def __init__(self) -> None:
        super().__init__(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.expand = True
        self.controls.append(
            ft.Text("NBT 树状视图（开发中）", size=14, color=THEME.text_secondary)
        )

    def load_nbt(self, nbt_data: Any) -> None:
        pass

    def search(self, query: str) -> None:
        pass

    def get_modified_data(self) -> Any:
        return None


# ═══════════════════════════════════════════════
#  主视图
# ═══════════════════════════════════════════════

class ExplorerView(ft.Column):
    """存档探险家视图 —— 三标签页布局"""

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
                ft.Text("📂 存档探险家", size=24, weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary),
                self._world_label,
                ft.Container(),
                btn_primary("加载存档", on_click=self._load_world),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(bottom=16),
        )

        # 标签页容器
        self._tab_player = ft.Container()
        self._tab_player.expand = True
        self._tab_region = ft.Container()
        self._tab_region.expand = True
        self._tab_nbt = ft.Container()
        self._tab_nbt.expand = True
        self._tabs_content = [self._tab_player, self._tab_region, self._tab_nbt]
        self._tab_index = 0

        # 标签页按钮
        self._tab_labels_widgets: List[ft.Text] = []
        tab_label_conts: List[ft.Container] = []
        for idx, name in enumerate(["玩家", "区块", "NBT"]):
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

        self._build_player_tab()
        self._build_region_tab()
        self._build_nbt_tab()

    def _switch_tab(self, index: int) -> None:
        self._tab_index = index
        for i, lbl in enumerate(self._tab_labels_widgets):
            lbl.color = THEME.text_primary if i == index else THEME.text_secondary
        self._content_box.content = self._tabs_content[index]
        self._content_box.update()
        self._tab_bar.update()

    # ─── 玩家标签页 ───────────────────────────────

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

    # ─── 区块标签页 ───────────────────────────────

    def _build_region_tab(self) -> None:
        col = ft.Column(spacing=10)
        col.expand = True
        col.controls.append(
            ft.Text("区域热力图（根据文件大小着色）", size=14,
                    weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        self._heatmap = MCAHeatmap(cell_size=24)
        heatmap_container = ft.Container(content=self._heatmap)
        heatmap_container.expand = True
        col.controls.append(heatmap_container)

        tb = ft.Row([
            btn_primary("刷新热力图", width=120,
                        on_click=lambda e: self._refresh_heatmap()),
            btn_ghost("清空选择", width=120,
                      on_click=lambda e: self._heatmap.clear_selection()),
            ft.Text("点击单元格选择区域", size=12, color=THEME.text_muted),
        ], spacing=10)
        col.controls.append(tb)
        self._tab_region.content = col

    # ─── NBT 标签页 ───────────────────────────────

    def _build_nbt_tab(self) -> None:
        col = ft.Column(spacing=10)
        col.expand = True
        col.controls.append(
            ft.Text("NBT 数据查看器", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary)
        )
        self._nbt_tree = NBTTreeView()
        c = ft.Container(content=self._nbt_tree)
        c.expand = True
        col.controls.append(c)
        self._tab_nbt.content = col

    # ─── 交互回调 ──────────────────────────────────

    def _load_world(self, e: ft.ControlEvent = None) -> None:
        path = self.app.pick_directory()
        if not path:
            return
        try:
            self.world_session = WorldSession(Path(path))
            self._world_label.value = f"已加载: {self.world_session.world_path.name}"
            self._world_label.update()

            # 填充玩家下拉列表
            players = []
            for uuid, name in self.world_session._player_names.items():
                display = name or uuid
                formatted = self.world_session._format_uuid_with_hyphens(uuid)
                players.append((formatted, display))
            self._player_dropdown.options = [
                ft.dropdown.Option(v[0], v[1]) for v in players
            ]
            self._player_dropdown.update()
            self._refresh_heatmap()
        except Exception as ex:
            self.app.error_dialog("加载失败", f"无法加载存档: {ex}")

    def _on_player_selected(self, e: ft.ControlEvent) -> None:
        if not self.world_session or not e.control.value:
            return
        self.current_uuid = e.control.value
        try:
            player_data = self.world_session.load_player_data(self.current_uuid)
            self._player_hud.update_from_nbt(player_data)
            inv = player_data.get("Inventory", []) if player_data else []
            self._inventory.set_inventory(inv)
            nbt = self.world_session.load_player_nbt(self.current_uuid)
            self._nbt_tree.load_nbt(nbt)
        except Exception:
            pass

    def _refresh_heatmap(self) -> None:
        if self.world_session:
            self._heatmap.set_region_files(self.world_session._region_files)
            self._heatmap.update()

    def _import_usercache(self, e: ft.ControlEvent = None) -> None:
        path = self.app.pick_file(
            title="选择 usercache.json",
            file_types=[("JSON 文件 (*.json)", "*.json")],
        )
        if path:
            # WorldSession 已自动扫描 usercache，此处无需重复导入
            self.app.info_dialog("提示", "请直接加载存档目录，usercache.json 会被自动扫描。")
