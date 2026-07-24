"""存档对比视图。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import flet as ft

from app.presenters.compare_view_state import (
    CompareGroupState,
    begin_compare,
    complete_compare,
    fail_compare,
    initial_compare_state,
    invalidate_compare,
)
from app.services.world_compare_service import WorldCompareResult
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
)
from app.ui.components.buttons import btn_ghost
from app.ui.components.cards import card, placeholder, section_title
from app.ui.components.fields import text_field, current_save_field
from app.ui.components.layout import page_header
from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.utils import run_on_ui, safe_update
from app.ui.view_actions import ViewAction

if TYPE_CHECKING:
    from app.ui.feature_context import FeatureContext


class CompareView(ft.Column):
    """双世界差异对比页：level.dat、玩家与区域文件。"""

    def __init__(self, app: "FeatureContext") -> None:
        """绑定应用与对比服务。

        Args:
            app: 应用组合根。
        """
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._task_scope = app.execution_runtime.create_scope("compare_view")
        self._service = app.world_compare
        self._state = initial_compare_state()
        self._build()

    def get_top_actions(self) -> list[ViewAction]:
        """顶栏「开始对比」动作。"""
        return [
            ViewAction(
                self.app.translate("top_bar.start_compare", "开始对比"),
                self._compare,
            )
        ]

    def _build(self) -> None:
        self.controls.clear()
        self._page_header = page_header(
            "存档对比",
            ft.Text(
                "比较两个世界的 level.dat、玩家数据和区域文件差异",
                size=12,
                color=THEME.text_muted,
            ),
            icon=IconSet.BALANCE,
        )
        self.controls.append(self._page_header)

        self._left_field = current_save_field(
            label="基准存档", hint_text="请通过侧边栏「设置当前存档」设置基准存档")
        self._right_field = text_field(
            label="目标存档",
            hint_text="指定要对比的目标存档目录",
            expand=False,
        )
        self._right_field.col = {"xs": 12, "sm": 9}
        browse_button = btn_ghost(
            "浏览对比目标",
            on_click=lambda e: self._pick(self._right_field),
        )
        browse_button.col = {"xs": 12, "sm": 3}
        picker = ft.Column([self._left_field,
                            ft.ResponsiveRow(
                                [self._right_field, browse_button],
                                columns=12,
                                spacing=10,
                                run_spacing=8,
                            ),
                            ft.Text("设置两份存档后，可通过标题栏“开始对比”执行。",
                                    size=12,
                                    color=THEME.text_muted),
                            ],
                           spacing=10)
        self.controls.append(card(picker, padding=16))

        self._summary = ft.Text(
            self._state.summary,
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
            if self._state.is_comparing:
                self.app.warn_dialog("提示", "对比正在进行中，请稍候。")
                return
            paths = self._validated_compare_paths()
            if paths is None:
                return
            self._state = begin_compare(self._state, *paths)
            generation = self._state.generation
            self._render_state()
            handle = self._task_scope.submit(
                "compare_worlds",
                lambda token: self._run_compare(*paths, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            handle.add_done_callback(
                lambda completed: self._finish_compare_task(
                    completed,
                    generation,
                )
            )
        except Exception as ex:
            self._handle_compare_error(ex, self._state.generation)

    def _validated_compare_paths(self) -> Optional[tuple[Path, Path]]:
        left_text = str(self._left_field.value or "").strip()
        right_text = str(self._right_field.value or "").strip()
        if not left_text:
            self.app.warn_dialog("提示", "请先通过侧边栏设置有效基准存档目录。")
            return None
        if not right_text:
            self.app.warn_dialog("提示", "请指定包含 level.dat 的有效目标存档目录。")
            return None
        return Path(left_text), Path(right_text)

    def _run_compare(
        self,
        left: Path,
        right: Path,
        token: CancellationToken,
    ) -> WorldCompareResult:
        """在 I/O 通道校验路径并生成纯对比结果。"""
        token.raise_if_cancelled()
        self._validate_world_path(left, "基准")
        self._validate_world_path(right, "目标")
        result = self._service.compare_worlds(left, right)
        token.raise_if_cancelled()
        return result

    @staticmethod
    def _validate_world_path(path: Path, label: str) -> None:
        if not (path / "level.dat").is_file():
            raise ValueError(f"{label}存档目录缺少 level.dat: {path}")

    def _finish_compare_task(
        self,
        handle: OperationHandle[WorldCompareResult],
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(
                self.app.page,
                self._handle_compare_error,
                error,
                generation,
            )
            return
        run_on_ui(
            self.app.page,
            self._apply_compare_result,
            result,
            generation,
        )

    def _apply_compare_result(
        self,
        result: WorldCompareResult,
        generation: int,
    ) -> None:
        next_state = complete_compare(self._state, result, generation)
        if next_state is self._state:
            return
        self._state = next_state
        self._render_state()

    def _handle_compare_error(
        self,
        error: Exception,
        generation: int,
    ) -> None:
        next_state = fail_compare(self._state, generation)
        if next_state is self._state:
            return
        self._state = next_state
        self._render_state()
        self.app.handle_exception(error, title="存档对比失败")

    def _render_state(self) -> None:
        self._summary.value = self._state.summary
        self._result.controls.clear()
        self._result.controls.extend(
            self._group(group)
            for group in self._state.groups
        )
        self.update()

    def _group(self, group: CompareGroupState) -> ft.Container:
        rows = []
        for item in group.items:
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
        return card(ft.Column([ft.Text(group.title,
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
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self._left_field)

    def dispose(self) -> None:
        """取消页面拥有的对比任务；可重复调用。"""
        self._state = invalidate_compare(self._state)
        self._task_scope.close()
