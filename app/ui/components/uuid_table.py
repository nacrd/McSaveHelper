"""UUID 映射表组件 —— 可视化编辑玩家名-UUID 映射"""
import csv
from pathlib import Path
from typing import Dict, List, Optional, Callable

import flet as ft

from app.ui.theme import THEME, TEXT_LABEL_SIZE
from app.ui.components.buttons import btn_primary, btn_ghost, btn_danger
from app.ui.icons import IconSet
from app.ui.utils import safe_update as _safe_update


class UUIDMappingTable(ft.Column):
    """可编辑的 UUID 映射表格

    支持：
      - 手动添加/删除行
      - 实时同步映射数据
      - 导入文本文件（player_name uuid 格式）
      - 导出为文本文件
      - 清空所有映射
    """

    def __init__(
        self,
        mappings: Optional[Dict[str, str]] = None,
        on_mappings_change: Optional[Callable[[Dict[str, str]], None]] = None,
        on_import_click: Optional[Callable[[], Optional[str]]] = None,
        on_export_click: Optional[Callable[[Dict[str, str]], Optional[str]]] = None,
    ) -> None:
        """构建可编辑映射表。

        Args:
            mappings: 初始 ``名字 -> UUID``。
            on_mappings_change: 表格变更时回调。
            on_import_click: 返回待导入文件路径的选择器。
            on_export_click: 导出路径选择；返回写入路径。
        """
        super().__init__(spacing=4)
        self._mappings: Dict[str, str] = dict(mappings or {})
        self.on_mappings_change = on_mappings_change
        self._on_import_click = on_import_click
        self._on_export_click = on_export_click
        self._row_data: List[dict] = []
        self._rebuild()

    # ─── 公共接口 ──────────────────────────────────

    def set_mappings(self, mappings: Dict[str, str]) -> None:
        """用新映射整体替换表格内容。"""
        self._mappings = dict(mappings)
        self._rebuild()

    def get_mappings(self) -> Dict[str, str]:
        """返回当前映射副本。"""
        return dict(self._mappings)

    def load_from_file(self, file_path: str) -> int:
        """从文件加载映射（支持 .txt 和 .csv）

        .txt 格式: player_name uuid
        .csv 格式: player_name,uuid

        Returns: 加载的条目数量
        """
        path = Path(file_path)
        if not path.exists():
            return 0

        loaded = (
            self._read_csv_mappings(path)
            if path.suffix.lower() == ".csv"
            else self._read_text_mappings(path)
        )

        if loaded:
            self._mappings.update(loaded)
            self._rebuild()
            self._sync()
        return len(loaded)

    @staticmethod
    def _read_csv_mappings(path: Path) -> Dict[str, str]:
        loaded: Dict[str, str] = {}
        try:
            with path.open("r", encoding="utf-8", newline="") as file:
                for row in csv.reader(file):
                    if len(row) < 2:
                        continue
                    name, uuid = row[0].strip(), row[1].strip()
                    if name and uuid:
                        loaded[name] = uuid
        except Exception:
            pass
        return loaded

    @staticmethod
    def _read_text_mappings(path: Path) -> Dict[str, str]:
        loaded: Dict[str, str] = {}
        try:
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    parts = line.strip().split()
                    if len(parts) >= 2 and not line.lstrip().startswith("#"):
                        loaded[parts[0]] = parts[1]
        except Exception:
            pass
        return loaded

    def save_to_file(self, file_path: str) -> int:
        """保存映射到文本文件 (player_name uuid)

        Returns: 保存的条目数量
        """
        if not self._mappings:
            return 0
        with open(file_path, "w", encoding="utf-8") as f:
            for name, uuid in self._mappings.items():
                f.write(f"{name} {uuid}\n")
        return len(self._mappings)

    # ─── UI 构建 ───────────────────────────────────

    def _rebuild(self) -> None:
        self.controls.clear()
        self._row_data.clear()

        # 表头
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Text("玩家名", weight=ft.FontWeight.BOLD, expand=2,
                            color=THEME.text_secondary,
                            size=TEXT_LABEL_SIZE),
                    ft.Text("UUID", weight=ft.FontWeight.BOLD, expand=3,
                            color=THEME.text_secondary,
                            size=TEXT_LABEL_SIZE),
                ],
                spacing=8,
            ),
            padding=ft.Padding(bottom=8),
        )
        self.controls.append(header)

        # 数据行
        for name, uuid in self._mappings.items():
            self._add_row_with_values(name, uuid)

        # 操作按钮
        tb = ft.Row(
            [
                btn_primary(
                    "添加一行",
                    icon=ft.Icons.ADD,
                    on_click=lambda e: self._add_row(),
                ),
                btn_ghost(
                    "导入名单",
                    icon=IconSet.IMPORT,
                    on_click=lambda e: self._import_file(),
                ),
                btn_ghost(
                    "导出名单",
                    icon=IconSet.EXPORT,
                    on_click=lambda e: self._export_file(),
                ),
                btn_danger(
                    "清空",
                    icon=IconSet.DELETE,
                    on_click=lambda e: self._clear_all(),
                ),
            ],
            spacing=10,
        )
        self.controls.append(tb)

    def _add_row_with_values(
            self,
            player_name: str = "",
            uuid: str = "") -> None:
        nf = ft.TextField(
            value=player_name,
            border_color=THEME.border_standard,
            text_size=13, height=44,
            bgcolor=THEME.bg_secondary,
            border_radius=0,
        )
        nf.expand = 2

        uf = ft.TextField(
            value=uuid,
            border_color=THEME.border_standard,
            text_size=13, height=44,
            bgcolor=THEME.bg_secondary,
            border_radius=0,
        )
        uf.expand = 3

        def on_change() -> None:
            self._sync()

        nf.on_change = on_change
        uf.on_change = on_change

        # Create container first, then reference it in lambda
        row_cont = ft.Container(
            content=ft.Row(
                [
                    nf, uf,
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_size=18,
                        on_click=lambda e: self._delete_row_by_fields(nf, uf),
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=2,
        )
        self._row_data.append({"container": row_cont, "name": nf, "uuid": uf})
        # 插入在操作按钮之前
        self.controls.insert(-1, row_cont)
        _safe_update(self)

    def _add_row(self, e: Optional[ft.ControlEvent] = None) -> None:
        self._add_row_with_values()
        self._sync()

    def _delete_row(self, row_container: ft.Container) -> None:
        self._row_data = [
            r for r in self._row_data if r["container"] is not row_container]
        self.controls.remove(row_container)
        self._sync()
        _safe_update(self)

    def _delete_row_by_fields(self, name_field, uuid_field) -> None:
        """Delete row by matching name and uuid fields"""
        for r in list(self._row_data):
            if r["name"] is name_field and r["uuid"] is uuid_field:
                self.controls.remove(r["container"])
                self._row_data.remove(r)
                break
        self._sync()
        _safe_update(self)

    def _sync(self) -> None:
        new_mappings: Dict[str, str] = {}
        for r in self._row_data:
            n = r["name"].value.strip()
            u = r["uuid"].value.strip()
            if n and u:
                new_mappings[n] = u
        self._mappings = new_mappings
        if self.on_mappings_change:
            self.on_mappings_change(new_mappings)

    def _clear_all(self) -> None:
        for r in list(self._row_data):
            self.controls.remove(r["container"])
        self._row_data.clear()
        self._mappings.clear()
        if self.on_mappings_change:
            self.on_mappings_change({})
        _safe_update(self)

    def _import_file(self) -> None:
        """触发导入文件操作"""
        if self._on_import_click:
            path = self._on_import_click()
            if path:
                self.load_from_file(path)

    def _export_file(self) -> None:
        """触发导出文件操作"""
        if self._on_export_click:
            path = self._on_export_click(self._mappings)
            if path:
                self.save_to_file(path)
