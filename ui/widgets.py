"""Flet custom UI components following Linear design system"""
import flet as ft
from typing import Any, Dict, List, Tuple, Optional, Callable, Set
from pathlib import Path
from ui.constants import COLORS


def _border_subtle():
    return ft.border.all(1, COLORS["border_subtle"])

def _border_standard():
    return ft.border.all(1, COLORS["border_standard"])


class LogPanel(ft.Column):
    def __init__(self):
        super().__init__(spacing=2, scroll=ft.ScrollMode.ALWAYS, expand=True)
        self._max_lines = 500

    def log(self, message: str, level: str = "info"):
        color_map = {
            "info": COLORS["text_primary"],
            "success": COLORS["terminal_green"],
            "warn": COLORS["terminal_yellow"],
            "error": COLORS["terminal_red"],
            "api": COLORS["terminal_blue"],
            "timestamp": COLORS["text_muted"],
            "header": COLORS["accent_light"],
            "separator": COLORS["border_tertiary"],
        }
        self.controls.append(
            ft.Text(message, color=color_map.get(level, COLORS["text_primary"]),
                    size=11, font_family="monospace"))
        while len(self.controls) > self._max_lines:
            self.controls.pop(0)
        self.update()

    def clear(self):
        self.controls.clear()
        self.update()


def card(content: ft.Control, padding=20, **kwargs) -> ft.Container:
    return ft.Container(
        content=ft.Container(content=content, padding=padding) if not isinstance(content, ft.Container) else content,
        bgcolor=COLORS["bg_card"],
        border=_border_standard(),
        border_radius=8,
        **kwargs,
    )


def section_title(text: str) -> ft.Container:
    return ft.Container(
        content=ft.Row([
            ft.Text(text, size=15, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
            ft.Container(height=1, expand=True, bgcolor=COLORS["border_subtle"]),
        ], spacing=15, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.only(left=20, right=20, top=18, bottom=8),
    )


def label(text: str) -> ft.Text:
    return ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=COLORS["text_secondary"])


def btn_primary(text: str, on_click: Callable = None, width: int = None, height: int = 38, icon: str = None) -> ft.ElevatedButton:
    return ft.ElevatedButton(
        text=text, icon=icon, on_click=on_click, width=width, height=height,
        style=ft.ButtonStyle(color=COLORS["text_primary"], bgcolor=COLORS["accent"],
                             shape=ft.RoundedRectangleBorder(radius=6)),
    )


def btn_ghost(text: str, on_click: Callable = None, width: int = None, height: int = 38) -> ft.ElevatedButton:
    return ft.ElevatedButton(
        text=text, on_click=on_click, width=width, height=height,
        style=ft.ButtonStyle(color=COLORS["text_secondary"],
                             bgcolor="rgba(255,255,255,0.02)",
                             side=ft.BorderSide(1, COLORS["border_standard"]),
                             shape=ft.RoundedRectangleBorder(radius=6)),
    )


def btn_success(text: str, on_click: Callable = None, width: int = None, height: int = 38) -> ft.ElevatedButton:
    return ft.ElevatedButton(
        text=text, on_click=on_click, width=width, height=height,
        style=ft.ButtonStyle(color=COLORS["text_primary"], bgcolor=COLORS["success"],
                             shape=ft.RoundedRectangleBorder(radius=6)),
    )


def btn_danger(text: str, on_click: Callable = None, width: int = None, height: int = 38) -> ft.ElevatedButton:
    return ft.ElevatedButton(
        text=text, on_click=on_click, width=width, height=height,
        style=ft.ButtonStyle(color=COLORS["text_primary"], bgcolor=COLORS["error"],
                             shape=ft.RoundedRectangleBorder(radius=6)),
    )


def text_field(value: str = "", label: str = None, hint_text: str = None,
               expand: bool = True, width: int = None, on_change: Callable = None,
               password: bool = False) -> ft.TextField:
    return ft.TextField(
        value=value, label=label, hint_text=hint_text, expand=expand, width=width,
        on_change=on_change, password=password,
        border_color=COLORS["border_standard"], focused_border_color=COLORS["accent"],
        text_size=13, color=COLORS["text_primary"],
        bgcolor="rgba(255,255,255,0.02)",
        border_radius=6,
    )


def checkbox(label: str, value: bool = False, on_change: Callable = None) -> ft.Checkbox:
    return ft.Checkbox(label=label, value=value, on_change=on_change,
                       check_color=COLORS["accent"], label_style=ft.TextStyle(size=13, color=COLORS["text_secondary"]))


class UUIDMappingTable(ft.Column):
    def __init__(self, mappings: Dict[str, str] = None, on_mappings_change: Callable = None):
        super().__init__(spacing=4)
        self._mappings = mappings or {}
        self.on_mappings_change = on_mappings_change
        self._row_data: List[Dict] = []
        self._rebuild()

    def _rebuild(self):
        self.controls.clear()
        self._row_data.clear()
        header = ft.Container(
            content=ft.Row([
                ft.Text("玩家名", weight=ft.FontWeight.BOLD, expand=2, color=COLORS["text_secondary"], size=12),
                ft.Text("UUID", weight=ft.FontWeight.BOLD, expand=3, color=COLORS["text_secondary"], size=12),
            ], spacing=8),
            padding=ft.padding.only(bottom=8),
        )
        self.controls.append(header)
        for p, u in self._mappings.items():
            self._add_row_with_values(p, u)
        tb = ft.Row([
            btn_primary("+ 添加一行", on_click=lambda e: self._add_row()),  # fixed click
            btn_ghost("📁 导入名单", on_click=lambda e: None, height=32),
            btn_ghost("💾 导出名单", on_click=lambda e: None, height=32),
            btn_danger("🗑️ 清空", on_click=lambda e: self._clear_all(), height=32),
        ], spacing=10)
        self.controls.append(tb)

    def _add_row_with_values(self, player_name="", uuid=""):
        nf = ft.TextField(value=player_name, expand=2, border_color=COLORS["border_standard"],
                          text_size=13, height=40, bgcolor="rgba(255,255,255,0.02)", border_radius=6)
        uf = ft.TextField(value=uuid, expand=3, border_color=COLORS["border_standard"],
                          text_size=13, height=40, bgcolor="rgba(255,255,255,0.02)", border_radius=6)

        def on_change(e):
            self._sync()

        nf.on_change = on_change
        uf.on_change = on_change

        row = ft.Container(
            content=ft.Row([
                nf, uf,
                ft.IconButton(ft.icons.DELETE_OUTLINE, icon_size=18,
                              on_click=lambda e: self._delete_row(row)),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=2,
        )
        self._row_data.append({"container": row, "name": nf, "uuid": uf})
        self.controls.insert(-1, row)
        self.update()

    def _add_row(self, e=None):
        self._add_row_with_values()
        self._sync()

    def _delete_row(self, row_container):
        self._row_data = [r for r in self._row_data if r["container"] != row_container]
        self.controls.remove(row_container)
        self._sync()
        self.update()

    def _sync(self):
        nm = {}
        for r in self._row_data:
            n = r["name"].value.strip()
            u = r["uuid"].value.strip()
            if n and u:
                nm[n] = u
        self._mappings = nm
        if self.on_mappings_change:
            self.on_mappings_change(nm)

    def _clear_all(self):
        for r in self._row_data:
            self.controls.remove(r["container"])
        self._row_data.clear()
        self._mappings = {}
        if self.on_mappings_change:
            self.on_mappings_change({})
        self.update()

    def get_mappings(self) -> Dict[str, str]:
        return self._mappings.copy()

    def set_mappings(self, mappings: Dict[str, str]):
        self._mappings = mappings.copy()
        self._rebuild()
        self.update()

    @property
    def mappings(self) -> Dict[str, str]:
        return self._mappings

    @mappings.setter
    def mappings(self, value: Dict[str, str]):
        self._mappings = value
        self._rebuild()
        self.update()


class NBTTreeView(ft.Column):
    def __init__(self):
        super().__init__(expand=True, alignment=ft.MainAxisAlignment.CENTER,
                         horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        self.controls.append(
            ft.Text("NBT 树状视图（开发中）", size=14, color=COLORS["text_secondary"])
        )

    def load_nbt(self, nbt_data: Any):
        pass

    def search(self, query: str):
        pass

    def get_modified_data(self) -> Any:
        return None


class MCAHeatmap(ft.GridView):
    def __init__(self, cell_size: int = 24):
        super().__init__(runs_count=0, max_extent=cell_size + 2, spacing=1, child_aspect_ratio=1.0)
        self._cell_size = cell_size
        self._selected: Set[Tuple[int, int]] = set()
        self._cells: Dict[Tuple[int, int], ft.Container] = {}

    def set_region_files(self, region_files: Dict[Tuple[int, int], Path]):
        self.controls.clear()
        self._cells.clear()
        if not region_files:
            self.update()
            return
        xs = [c[0] for c in region_files]
        zs = [c[1] for c in region_files]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)

        def make_cell(coord):
            path = region_files.get(coord)
            bg = self._color_for_file(path) if path else COLORS["bg_card"]

            def click(e):
                if coord in self._selected:
                    self._selected.remove(coord)
                    cell.border = _border_subtle()
                else:
                    self._selected.add(coord)
                    cell.border = ft.border.all(2, COLORS["accent"])
                self.update()

            cell = ft.Container(width=self._cell_size, height=self._cell_size,
                                bgcolor=bg, border=_border_subtle(), border_radius=2, on_click=click)
            self._cells[coord] = cell
            return cell

        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                self.controls.append(make_cell((x, z)))
        self.update()

    def _color_for_file(self, path: Path) -> str:
        try:
            s = path.stat().st_size
            max_s = 10 * 1024 * 1024
            i = min(255, int(s / max_s * 255))
            r = min(255, 100 + i // 5)
            g = min(255, 150 + i // 8)
            b = min(255, 200 + i // 3)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return COLORS["bg_card"]

    def get_selected(self) -> List[Tuple[int, int]]:
        return list(self._selected)

    def clear_selection(self):
        for c in self._selected:
            if c in self._cells:
                self._cells[c].border = _border_subtle()
        self._selected.clear()
        self.update()


class InventoryGrid(ft.GridView):
    def __init__(self, slot_size: int = 48):
        super().__init__(runs_count=9, max_extent=slot_size, spacing=2, child_aspect_ratio=1.0)
        self._slots: List[ft.Container] = []
        for _ in range(36):
            s = ft.Container(width=slot_size, height=slot_size, bgcolor=COLORS["bg_card"],
                             border=_border_subtle(), border_radius=6,
                             content=ft.Text("", size=10, color=COLORS["text_muted"],
                                             text_align=ft.TextAlign.CENTER))
            self._slots.append(s)
            self.controls.append(s)

    def set_inventory(self, inventory: List[Dict[str, Any]]):
        for s in self._slots:
            s.bgcolor = COLORS["bg_card"]
            s.content = ft.Text("", size=10, color=COLORS["text_muted"], text_align=ft.TextAlign.CENTER)
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
            s.bgcolor = COLORS["bg_card_hover"]
            s.content = ft.Text(lbl, size=9, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER)
        self.update()

    def clear(self):
        for s in self._slots:
            s.bgcolor = COLORS["bg_card"]
            s.content = ft.Text("", size=10, color=COLORS["text_muted"], text_align=ft.TextAlign.CENTER)
        self.update()
