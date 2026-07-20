"""存档对比视图。"""
import threading
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

import flet as ft

from app.services.world_compare_service import CompareItem, get_world_compare_service
from app.ui.components.buttons import btn_ghost
from app.ui.components.cards import card, placeholder, section_title
from app.ui.components.fields import text_field, current_save_field
from app.ui.components.layout import page_header
from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.utils import run_on_ui
from app.ui.view_actions import ViewAction

if TYPE_CHECKING:
    from app.application import Application


class CompareView(ft.Column):
    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._service = get_world_compare_service(log=app.log)
        self._comparing = False
        self._build()

    def get_top_actions(self) -> list[ViewAction]:
        return [
            ViewAction(
                self.app.translate("top_bar.start_compare", "开始对比"),
                self._compare,
            )
        ]

    def _build(self) -> None:
        self.controls.clear()
        self.controls.append(
            page_header(
                "存档对比",
                ft.Text(
                    "比较两个世界的 level.dat、玩家数据和区域文件差异",
                    size=12,
                    color=THEME.text_muted),
                icon=IconSet.BALANCE,
            ))

        self._left_field = current_save_field(
            label="基准存档", hint_text="请通过侧边栏「设置当前存档」设置基准存档")
        self._right_field = text_field(label="目标存档", hint_text="指定要对比的目标存档目录")
        picker = ft.Column([self._left_field,
                            ft.Row([self._right_field,
                                    btn_ghost("浏览对比目标",
                                              width=120,
                                              on_click=lambda e: self._pick(self._right_field))],
                                   spacing=10),
                            ft.Text("设置两份存档后，可通过顶栏“开始对比”执行。",
                                    size=11,
                                    color=THEME.text_muted),
                            ],
                           spacing=10)
        self.controls.append(card(picker, padding=16))

        self._summary = ft.Text(
            "通过侧边栏设置基准存档，再指定目标存档后开始对比。",
            size=12,
            color=THEME.text_muted)
        self._result = ft.Column(spacing=12)
        self.controls.append(card(ft.Column(
            [section_title("结果"), self._summary, self._result], spacing=8), padding=0))

    def _pick(self, field: ft.TextField) -> None:
        path = self.app.pick_directory()
        if path:
            field.value = path
            field.update()

    def _compare(self, e: ft.ControlEvent) -> None:
        try:
            if self._comparing:
                self.app.warn_dialog("提示", "对比正在进行中，请稍候。")
                return
            paths = self._validated_compare_paths()
            if paths is None:
                return
            self._summary.value = "正在对比，请稍候..."
            self._result.controls.clear()
            self._comparing = True
            self.update()
            threading.Thread(
                target=self._run_compare,
                args=paths,
                daemon=True,
            ).start()
        except Exception as ex:
            self._handle_compare_error(ex)

    def _validated_compare_paths(self) -> Optional[Tuple[Path, Path]]:
        left = Path(self._left_field.value or "")
        right = Path(self._right_field.value or "")
        if not (left / "level.dat").exists():
            self.app.warn_dialog("提示", "请先通过侧边栏设置有效基准存档目录。")
            return None
        if not (right / "level.dat").exists():
            self.app.warn_dialog("提示", "请指定包含 level.dat 的有效目标存档目录。")
            return None
        return left, right

    def _run_compare(self, left: Path, right: Path) -> None:
        try:
            result = self._service.compare_worlds(left, right)
            total = sum(
                value
                for key, value in result.summary.items()
                if key != "changed"
            )
            summary = f"变更项: {result.summary['changed']} / {total}"
            groups = [
                self._group("WorldInfo 差异", result.world_info),
                self._group("玩家数据差异", result.players),
                self._group("区域文件差异", result.regions),
            ]
            run_on_ui(self.app.page, self._finish_compare, summary, groups)
        except Exception as ex:
            run_on_ui(self.app.page, self._handle_compare_error, ex)

    def _finish_compare(
        self,
        summary: str,
        groups: List[ft.Container],
    ) -> None:
        self._summary.value = summary
        self._result.controls.extend(groups)
        self._comparing = False
        self.update()

    def _handle_compare_error(self, error: Exception) -> None:
        self._comparing = False
        self.app.handle_exception(error, title="存档对比失败")

    def _group(self, title: str, items: List[CompareItem]) -> ft.Container:
        rows = []
        for item in items:
            if item.same:
                continue
            rows.append(ft.Container(
                content=ft.Column([
                    ft.Text(item.name, size=12, weight=ft.FontWeight.BOLD, color=THEME.mc_gold),
                    ft.Text(f"基准: {item.left}", size=11, color=THEME.text_secondary),
                    ft.Text(f"目标: {item.right}", size=11, color=THEME.text_secondary),
                ], spacing=2),
                padding=8,
                bgcolor=THEME.bg_secondary,
            ))
        if not rows:
            rows.append(placeholder(
                icon=IconSet.SUCCESS,
                title="未发现差异",
                subtitle="该分组中的两份存档数据一致",
                height=110,
            ))
        return card(ft.Column([ft.Text(title,
                                       size=14,
                                       weight=ft.FontWeight.BOLD,
                                       color=THEME.text_primary),
                               *rows],
                              spacing=8),
                    padding=12)

    def on_save_selected(self, path: str) -> None:
        """统一入口设置当前存档回调"""
        try:
            self._left_field.value = path
            self._left_field.update()
        except Exception:
            pass
