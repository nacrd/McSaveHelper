"""Explorer view - world inspection dashboard"""
import flet as ft
from typing import TYPE_CHECKING, Any, Optional, List, Dict
from pathlib import Path
import re

from ui.constants import COLORS
from ui.widgets import card, btn_primary, btn_ghost, text_field, InventoryGrid, MCAHeatmap, NBTTreeView, LogPanel

if TYPE_CHECKING:
    from ui.app import App

from core.omni.world_session import WorldSession


class PlayerHUDCard(ft.Column):
    def __init__(self):
        super().__init__(spacing=8)
        self._attrs = {}
        rows_data = [
            ("生命值", "health", "♥"),
            ("饥饿值", "food", "🍖"),
            ("经验等级", "level", "⭐"),
            ("氧气", "air", "🌊"),
            ("维度", "dimension", "🌍"),
            ("坐标", "pos", "📍"),
        ]
        self.controls.append(
            ft.Text("玩家状态", size=16, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        for label_text, key, icon in rows_data:
            lbl = ft.Text(f"{icon} {label_text}:", size=13, color=COLORS["text_secondary"])
            val = ft.Text("--", size=13, weight=ft.FontWeight.BOLD, color=COLORS["accent_light"])
            self._attrs[key] = val
            self.controls.append(ft.Row([lbl, val], spacing=10))

    def update_from_nbt(self, player_data: Any):
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
            ds = str(dim)
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


class ExplorerView(ft.Column):
    def __init__(self, app: "App"):
        super().__init__(expand=True, spacing=0)
        self.app = app
        self.world_session: Optional[WorldSession] = None
        self.current_uuid: Optional[str] = None
        self.player_uuid_map: Dict[str, str] = {}
        self._build()

    def _build(self):
        self.controls.clear()

        self._world_label = ft.Text("未加载存档", size=12, color=COLORS["text_muted"])

        toolbar = ft.Container(
            content=ft.Row([
                ft.Text("📂 存档探险家", size=24, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                self._world_label,
                ft.Container(expand=True),
                btn_primary("加载存档", on_click=lambda e: self._load_world()),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(bottom=16),
        )

        self._tab_player = ft.Container(expand=True)
        self._tab_region = ft.Container(expand=True)
        self._tab_nbt = ft.Container(expand=True)
        tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="玩家", content=self._tab_player),
                ft.Tab(text="区块", content=self._tab_region),
                ft.Tab(text="NBT", content=self._tab_nbt),
            ],
            expand=True,
        )

        self.controls.append(toolbar)
        self.controls.append(tabs)

        self._build_player_tab()
        self._build_region_tab()
        self._build_nbt_tab()

    def _build_player_tab(self):
        left = ft.Column(spacing=10, width=300)
        left.controls.append(
            ft.Text("选择玩家", size=14, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )

        self._player_dropdown = ft.Dropdown(
            options=[], on_change=self._on_player_selected,
            border_color=COLORS["border_standard"], text_size=13,
        )
        left.controls.append(self._player_dropdown)
        left.controls.append(
            btn_ghost("导入 usercache.json", height=30, on_click=lambda e: self._import_usercache())
        )

        self._player_hud = PlayerHUDCard()
        self._hud_card = card(self._player_hud, padding=15)
        left.controls.append(self._hud_card)

        right = ft.Column(spacing=10, expand=True)
        right.controls.append(
            ft.Text("物品栏", size=14, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        self._inventory = InventoryGrid(slot_size=50)
        right.controls.append(self._inventory)

        self._tab_player.content = ft.Row([left, ft.Container(width=20), right], expand=True)

    def _build_region_tab(self):
        col = ft.Column(spacing=10, expand=True)
        col.controls.append(
            ft.Text("区域热力图（根据文件大小着色）", size=14, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        self._heatmap = MCAHeatmap(cell_size=24)
        col.controls.append(ft.Container(content=self._heatmap, expand=True))

        tb = ft.Row([
            btn_primary("刷新热力图", width=120, on_click=lambda e: self._refresh_heatmap()),
            btn_ghost("清空选择", width=120, on_click=lambda e: self._heatmap.clear_selection()),
            ft.Text("点击单元格选择区域，再次点击取消选择", size=12, color=COLORS["text_muted"]),
        ], spacing=10)
        col.controls.append(tb)
        self._tab_region.content = col

    def _build_nbt_tab(self):
        col = ft.Column(spacing=10, expand=True)
        col.controls.append(
            ft.Text("NBT 树状查看器（支持搜索与编辑）", size=14, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        sr = ft.Row([
            ft.Text("搜索：", size=12, color=COLORS["text_secondary"]),
            text_field(hint_text="输入键名或值...", expand=True),
            btn_primary("搜索", width=80, on_click=lambda e: self._search_nbt()),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        col.controls.append(sr)
        self._nbt_tree = NBTTreeView()
        col.controls.append(ft.Container(content=self._nbt_tree, expand=True))
        self._tab_nbt.content = col

    def _log(self, message: str):
        self.app.log_msg(f"[存档探险] {message}", "INFO")

    def _load_world(self):
        self.app._pick_directory(self._load_world_path)

    def _load_world_path(self, path_str: str):
        try:
            session = WorldSession(Path(path_str))
            self.set_world_session(session)
            self._log(f"已加载存档: {path_str}")
        except Exception as exc:
            self._log(f"加载失败: {exc}")
            self.app._error_dialog("加载错误", f"无法加载存档:\n{exc}")

    def _import_usercache(self):
        if not self.world_session:
            self.app._warn_dialog("未加载存档", "请先加载存档")
            return

        def on_file(path: str):
            try:
                imported = self.world_session.import_usercache(Path(path))
                self._log(f"已导入 {imported} 个玩家名称映射")
                self.set_world_session(self.world_session)
            except Exception as exc:
                self._log(f"导入失败: {exc}")

        self.app._pick_file(on_file, file_types=["json"])

    def _refresh_heatmap(self):
        if self.world_session:
            self._heatmap.set_region_files(self.world_session._region_files)
            self._log("热力图已刷新")
        else:
            self._log("请先加载存档")

    def _search_nbt(self):
        pass

    def _on_player_selected(self, e):
        selection = e.control.value
        if not self.world_session or not selection:
            return
        uuid = self.player_uuid_map.get(selection, selection)
        if uuid == selection and "(" in selection:
            m = re.search(r'\(([0-9a-f\-]{36})\)', selection)
            if m:
                uuid = m.group(1)
        self.current_uuid = uuid
        pd = self.world_session.get_player_data(uuid)
        if pd:
            self._player_hud.update_from_nbt(pd)
            inv = self._extract_inventory(pd)
            self._inventory.set_inventory(inv)
            self._nbt_tree.load_nbt(pd)
            self._log(f"已加载玩家 {uuid} 的数据")
        else:
            self._log(f"无法加载玩家 {uuid} 的数据")

    def _extract_inventory(self, player_data: Any) -> List[Dict[str, Any]]:
        items = []
        inv = player_data.get("Inventory")
        if inv is not None and isinstance(inv, list):
            for slot in inv:
                try:
                    si = slot.get("Slot", -1)
                    iid = slot.get("id", "")
                    cnt = slot.get("Count", 1)
                    tag = slot.get("tag")
                    if iid:
                        items.append({"slot": int(si), "id": str(iid), "count": int(cnt), "tag": tag})
                except Exception:
                    pass
        return items

    def set_world_session(self, session: WorldSession):
        self.world_session = session
        nm = session.get_player_names()
        uuids = list(nm.keys())
        dv = []
        self.player_uuid_map.clear()
        for uuid in uuids:
            name = nm[uuid]
            fuuid = session._format_uuid_with_hyphens(uuid)
            display = f"{name} ({fuuid})" if name else f"未知玩家 ({fuuid})"
            dv.append(display)
            self.player_uuid_map[display] = uuid
        self._player_dropdown.options = [ft.dropdown.Option(d) for d in dv]
        self._player_dropdown.value = dv[0] if dv else None
        self._player_dropdown.disabled = not bool(uuids)
        self._player_dropdown.update()
        self._world_label.value = f"存档: {session.world_path.name}"
        self._world_label.update()
        if uuids:
            self._on_player_selected(None)
        self._refresh_heatmap()
        self._log(f"已加载存档，发现 {len(uuids)} 个玩家")
