"""Explorer view - world inspection dashboard"""
import flet as ft
from typing import TYPE_CHECKING, Any, Optional, List, Dict
from pathlib import Path
import re

from ui.constants import COLORS
from ui.widgets import card, btn_primary, btn_ghost, text_field, InventoryGrid, MCAHeatmap, NBTTreeView
from core.i18n import t

if TYPE_CHECKING:
    from ui.app import App

from core.omni.world_session import WorldSession


class PlayerHUDCard(ft.Column):
    def __init__(self) -> None:
        super().__init__(spacing=8)
        self._attrs: Dict[str, ft.Text] = {}
        rows_data: List[tuple] = [
            (t("explorer.health", "生命值"), "health", "♥"),
            (t("explorer.food", "饥饿值"), "food", "🍖"),
            (t("explorer.level", "经验等级"), "level", "⭐"),
            (t("explorer.air", "氧气"), "air", "🌊"),
            (t("explorer.dimension", "维度"), "dimension", "🌍"),
            (t("explorer.position", "坐标"), "pos", "📍"),
        ]
        self.controls.append(
            ft.Text(t("explorer.player_status", "玩家状态"), size=16,
                    weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        for label_text, key, icon in rows_data:
            lbl = ft.Text(f"{icon} {label_text}:", size=13, color=COLORS["text_secondary"])
            val = ft.Text("--", size=13, weight=ft.FontWeight.BOLD, color=COLORS["accent_light"])
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
    def __init__(self, app: "App") -> None:
        super().__init__(spacing=0)
        self.expand = True
        self.app: "App" = app
        self.world_session: Optional[WorldSession] = None
        self.current_uuid: Optional[str] = None
        self.player_uuid_map: Dict[str, str] = {}
        self._build()

    def _switch_tab(self, index: int) -> None:
        self._tab_index = index
        for i, lbl in enumerate(self._tab_labels_widgets):
            lbl.color = COLORS["text_primary"] if i == index else COLORS["text_secondary"]
        self._content_box.content = self._tabs_content[index]
        self._content_box.update()
        self._tab_bar.update()

    def _build(self) -> None:
        self.controls.clear()

        self._world_label: ft.Text = ft.Text(
            t("explorer.no_world_loaded", "未加载存档"), size=12, color=COLORS["text_muted"])

        toolbar = ft.Container(
            content=ft.Row([
                ft.Text(t("explorer.title", "📂 存档探险家"), size=24,
                        weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                self._world_label,
                ft.Container(),
                btn_primary(t("explorer.load_world", "加载存档"), on_click=self._load_world),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(bottom=16),
        )

        self._tab_player: ft.Container = ft.Container()
        self._tab_player.expand = True
        self._tab_region: ft.Container = ft.Container()
        self._tab_region.expand = True
        self._tab_nbt: ft.Container = ft.Container()
        self._tab_nbt.expand = True
        self._tabs_content: List[ft.Container] = [self._tab_player, self._tab_region, self._tab_nbt]
        self._tab_index: int = 0

        self._tab_labels_widgets: List[ft.Text] = []
        tab_label_conts: List[ft.Container] = []
        tab_names = [
            t("explorer.tab_players", "玩家"),
            t("explorer.tab_regions", "区块"),
            t("explorer.tab_nbt", "NBT"),
        ]
        for idx, name in enumerate(tab_names):
            lbl = ft.Text(name, size=14, weight=ft.FontWeight.BOLD,
                          color=COLORS["text_primary"] if idx == 0 else COLORS["text_secondary"])
            self._tab_labels_widgets.append(lbl)
            tab_label_conts.append(
                ft.Container(
                    content=lbl,
                    padding=ft.padding.only(right=24, bottom=8),
                    on_click=lambda e, i=idx: self._switch_tab(i),
                )
            )
        tab_labels_row = ft.Row(tab_label_conts, spacing=0)  # type: ignore[arg-type]
        self._tab_indicator: ft.Container = ft.Container(height=2, bgcolor=COLORS["accent"])
        self._tab_bar: ft.Column = ft.Column([tab_labels_row, self._tab_indicator], spacing=0)
        self._content_box: ft.Container = ft.Container(content=self._tabs_content[0])
        self._content_box.expand = True

        self.controls.append(toolbar)
        col_tabs = ft.Column([self._tab_bar, self._content_box], spacing=8)
        col_tabs.expand = True
        self.controls.append(col_tabs)
        self._build_player_tab()
        self._build_region_tab()
        self._build_nbt_tab()

    def _build_player_tab(self) -> None:
        left = ft.Column(spacing=10, width=300)
        left.controls.append(
            ft.Text(t("explorer.select_player", "选择玩家"), size=14,
                    weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )

        self._player_dropdown: ft.Dropdown = ft.Dropdown(
            options=[], on_select=self._on_player_selected,  # type: ignore[arg-type]
            border_color=COLORS["border_standard"], text_size=13,
        )
        left.controls.append(self._player_dropdown)
        left.controls.append(
            btn_ghost(t("explorer.import_usercache", "导入 usercache.json"), height=30,
                      on_click=self._import_usercache)
        )

        self._player_hud: PlayerHUDCard = PlayerHUDCard()
        self._hud_card: ft.Container = card(self._player_hud, padding=15)
        left.controls.append(self._hud_card)

        right = ft.Column(spacing=10)
        right.expand = True
        right.controls.append(
            ft.Text(t("explorer.inventory", "物品栏"), size=14,
                    weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        self._inventory: InventoryGrid = InventoryGrid(slot_size=50)
        right.controls.append(self._inventory)

        self._tab_player.content = ft.Row([left, ft.Container(width=20), right], expand=True)

    def _build_region_tab(self) -> None:
        col = ft.Column(spacing=10)
        col.expand = True
        col.controls.append(
            ft.Text(t("explorer.region_heatmap", "区域热力图（根据文件大小着色）"), size=14,
                    weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        self._heatmap: MCAHeatmap = MCAHeatmap(cell_size=24)
        heatmap_container = ft.Container(content=self._heatmap)
        heatmap_container.expand = True
        col.controls.append(heatmap_container)

        tb = ft.Row([
            btn_primary(t("explorer.refresh_heatmap", "刷新热力图"), width=120,
                        on_click=lambda e: self._refresh_heatmap()),
            btn_ghost(t("explorer.clear_selection", "清空选择"), width=120,
                      on_click=lambda e: self._heatmap.clear_selection()),
            ft.Text(t("explorer.heatmap_hint", "点击单元格选择区域，再次点击取消选择"),
                    size=12, color=COLORS["text_muted"]),
        ], spacing=10)
        col.controls.append(tb)
        self._tab_region.content = col

    def _build_nbt_tab(self) -> None:
        col = ft.Column(spacing=10)
        col.expand = True
        col.controls.append(
            ft.Text(t("explorer.nbt_viewer", "NBT 树状查看器（支持搜索与编辑）"), size=14,
                    weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        sr = ft.Row([
            ft.Text(t("explorer.search", "搜索："), size=12, color=COLORS["text_secondary"]),
            text_field(hint_text=t("explorer.search_hint", "输入键名或值..."), expand=True),
            btn_primary(t("explorer.search_button", "搜索"), width=80,
                        on_click=lambda e: self._search_nbt()),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        col.controls.append(sr)
        self._nbt_tree: NBTTreeView = NBTTreeView()
        nbt_container = ft.Container(content=self._nbt_tree)
        nbt_container.expand = True
        col.controls.append(nbt_container)
        self._tab_nbt.content = col

    def _log(self, message: str) -> None:
        self.app.log_msg(f"[{t('explorer.title', '存档探险')}] {message}", "INFO")

    def _load_world(self, e: Optional[ft.ControlEvent] = None) -> None:
        path_str = self.app._pick_directory()
        if path_str:
            try:
                session = WorldSession(Path(path_str))
                self.set_world_session(session)
                self._log(t("explorer.load_success", "已加载存档: {path}", path=path_str))
            except Exception as exc:
                self._log(t("explorer.load_fail", "加载失败: {error}", error=str(exc)))
                self.app._error_dialog(
                    t("dialogs.error", "加载错误"),
                    t("messages.loading_world_failed", "无法加载存档:\n{error}", error=str(exc)),
                )

    def _import_usercache(self, e: Optional[ft.ControlEvent] = None) -> None:
        if not self.world_session:
            self.app._warn_dialog(t("dialogs.warning", "未加载存档"),
                                  t("explorer.load_first", "请先加载存档"))
            return

        path = self.app._pick_file(
            title=t("dialogs.load", "选择 usercache.json 文件"),
            file_types=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            try:
                imported = self.world_session.import_usercache(Path(path))
                self._log(t("explorer.imported_cache", "已导入 {count} 个玩家名称映射", count=imported))
                self.set_world_session(self.world_session)
            except Exception as exc:
                self._log(t("explorer.import_fail", "导入失败: {error}", error=str(exc)))

    def _refresh_heatmap(self) -> None:
        if self.world_session:
            self._heatmap.set_region_files(self.world_session._region_files)
            self._log(t("explorer.heatmap_refreshed", "热力图已刷新"))
        else:
            self._log(t("explorer.load_first", "请先加载存档"))

    def _search_nbt(self) -> None:
        pass

    def _on_player_selected(self, e: Optional[ft.ControlEvent]) -> None:
        if e is None or not e.control.value:
            return
        selection: str = e.control.value
        if not self.world_session or not selection:
            return
        uuid: str = self.player_uuid_map.get(selection, selection)
        if uuid == selection and "(" in selection:
            m = re.search(r'\(([0-9a-f\-]{36})\)', selection)
            if m:
                uuid = m.group(1)
        self.current_uuid = uuid
        pd = self.world_session.get_player_data(uuid)
        if pd:
            self._player_hud.update_from_nbt(pd)
            inv = self.world_session.get_player_inventory(uuid)
            self._inventory.set_inventory(inv)
            self._nbt_tree.load_nbt(pd)
            self._log(t("explorer.player_loaded", "已加载玩家 {uuid} 的数据", uuid=uuid))
        else:
            self._log(t("explorer.player_load_fail", "无法加载玩家 {uuid} 的数据", uuid=uuid))

    def set_world_session(self, session: WorldSession) -> None:
        self.world_session = session
        nm = session.get_player_names()
        uuids = list(nm.keys())
        dv: List[str] = []
        self.player_uuid_map.clear()
        for uuid in uuids:
            name = nm[uuid]
            fuuid = session._format_uuid_with_hyphens(uuid)
            display = f"{name} ({fuuid})" if name else f"{t('explorer.unknown_player', '未知玩家')} ({fuuid})"
            dv.append(display)
            self.player_uuid_map[display] = uuid
        self._player_dropdown.options = [ft.dropdown.Option(d) for d in dv]
        self._player_dropdown.value = dv[0] if dv else None
        self._player_dropdown.disabled = not bool(uuids)
        self._player_dropdown.update()
        self._world_label.value = f"{t('explorer.world_label', '存档')}: {session.world_path.name}"
        self._world_label.update()
        if uuids:
            self._on_player_selected(None)
        self._refresh_heatmap()
        self._log(t("explorer.session_loaded", "已加载存档，发现 {count} 个玩家", count=len(uuids)))
