"""存档对比视图。"""
from pathlib import Path
from typing import TYPE_CHECKING, List

import flet as ft

from app.services.world_compare_service import CompareItem, get_world_compare_service
from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.components.cards import card, section_title
from app.ui.components.fields import text_field
from app.ui.theme import THEME

if TYPE_CHECKING:
    from app.application import Application


class CompareView(ft.Column):
    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._service = get_world_compare_service(log=app.log)
        self._build()

    def _build(self) -> None:
        self.controls.clear()
        self.controls.append(ft.Text("存档对比", size=22, weight=ft.FontWeight.BOLD, color=THEME.text_primary))

        self._left_field = text_field(label="左侧存档", hint_text="选择第一个存档目录")
        self._right_field = text_field(label="右侧存档", hint_text="选择第二个存档目录")
        picker = ft.Column([
            ft.Row([self._left_field, btn_ghost("浏览", width=90, on_click=lambda e: self._pick(self._left_field))], spacing=10),
            ft.Row([self._right_field, btn_ghost("浏览", width=90, on_click=lambda e: self._pick(self._right_field))], spacing=10),
            btn_primary("开始对比", width=120, on_click=self._compare),
        ], spacing=10)
        self.controls.append(card(picker, padding=16))

        self._summary = ft.Text("选择两个存档后开始对比。", size=12, color=THEME.text_muted)
        self._result = ft.Column(spacing=12)
        self.controls.append(card(ft.Column([section_title("结果"), self._summary, self._result], spacing=8), padding=0))

    def _pick(self, field: ft.TextField) -> None:
        path = self.app.pick_directory()
        if path:
            field.value = path
            field.update()

    def _compare(self, e: ft.ControlEvent) -> None:
        try:
            left = Path(self._left_field.value or "")
            right = Path(self._right_field.value or "")
            if not (left / "level.dat").exists() or not (right / "level.dat").exists():
                self.app.warn_dialog("提示", "请选择包含 level.dat 的有效存档目录。")
                return
            self._summary.value = "正在对比，请稍候..."
            self._result.controls.clear()
            self.update()
            result = self._service.compare_worlds(left, right)
            self._summary.value = f"变更项: {result.summary['changed']} / {sum(v for k, v in result.summary.items() if k != 'changed')}"
            self._result.controls.extend([
                self._group("WorldInfo 差异", result.world_info),
                self._group("玩家数据差异", result.players),
                self._group("区域文件差异", result.regions),
            ])
            self.update()
        except Exception as ex:
            self.app.handle_exception(ex, title="存档对比失败")

    def _group(self, title: str, items: List[CompareItem]) -> ft.Container:
        rows = []
        for item in items:
            if item.same:
                continue
            rows.append(ft.Container(
                content=ft.Column([
                    ft.Text(item.name, size=12, weight=ft.FontWeight.BOLD, color=THEME.mc_gold),
                    ft.Text(f"左: {item.left}", size=11, color=THEME.text_secondary),
                    ft.Text(f"右: {item.right}", size=11, color=THEME.text_secondary),
                ], spacing=2),
                padding=8,
                bgcolor=THEME.bg_secondary,
            ))
        if not rows:
            rows.append(ft.Text("未发现差异", size=12, color=THEME.text_muted))
        return card(ft.Column([ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary), *rows], spacing=8), padding=12)
