"""server.properties 图形编辑视图。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from pathlib import Path
from typing import Callable, Dict, Protocol

import flet as ft

from app.services.execution_runtime import (
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
)
from app.services.server_properties_service import (
    BOOLEAN_PROPERTIES,
    DEFAULT_SERVER_PROPERTIES,
    ENUM_PROPERTIES,
    PROPERTY_DESCRIPTIONS,
    get_server_properties_service,
)
from app.ui.components.buttons import btn_ghost, btn_success
from app.ui.components.cards import card, section_title
from app.ui.components.fields import dropdown, text_field
from app.ui.feature_context import (
    FeatureDialogPort,
    FeatureFileDialogPort,
    FeatureRuntimePort,
    FeatureTranslationPort,
)
from app.ui.components.layout import page_header
from app.ui.icons import IconSet
from app.ui.theme import THEME
from app.ui.utils import run_on_ui, safe_update
from app.ui.view_actions import ViewAction


class ServerPropertiesHost(
    FeatureTranslationPort,
    FeatureDialogPort,
    FeatureFileDialogPort,
    FeatureRuntimePort,
    Protocol,
):
    """Ports required to edit a server.properties file."""


class ServerPropertiesView(ft.Column):
    """server.properties 图形编辑视图。

    支持选择服务器根目录、读取默认/现有配置项并写回文件。
    """

    def __init__(self, app: "ServerPropertiesHost") -> None:
        """初始化视图并构建表单控件。

        Args:
            app: server.properties 页面所需的 UI 与运行时端口。
        """
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._task_scope = app.execution_runtime.create_scope(
            "server_properties_view"
        )
        self._service = get_server_properties_service(log=app.log)
        self._fields: Dict[str, ft.Control] = {}
        self._path = Path("")
        self._generation = 0
        self._busy = False
        self._disposed = False
        self._build()

    def get_top_actions(self) -> list[ViewAction]:
        """返回应用壳层顶栏可消费的视图命令。

        Returns:
            list[ViewAction]: 当前视图暴露的顶栏动作列表。
        """
        return [
            ViewAction(
                self.app.translate("top_bar.read_config", "读取配置"),
                self._load,
            )
        ]

    def _build(self) -> None:
        self.controls.clear()
        self._page_header = page_header(
            "server.properties 编辑器",
            ft.Text(
                "读取、编辑并保存 Minecraft 服务器配置文件",
                size=12,
                color=THEME.text_muted,
            ),
            icon=IconSet.CLIPBOARD,
        )
        self.controls.append(self._page_header)
        self._path_field = text_field(
            label="服务器根目录或 server.properties",
            hint_text="选择服务器根目录",
        )
        self._browse_button = btn_ghost(
            "浏览",
            width=90,
            on_click=self._pick,
        )
        self.controls.append(card(ft.Column([
            ft.Row(
                [self._path_field, self._browse_button],
                spacing=10,
            ),
            ft.Text(
                "选择路径后，可通过标题栏“读取配置”加载 server.properties。",
                size=12,
                color=THEME.text_muted,
            ),
        ], spacing=10), padding=16))
        self._form = ft.Column(spacing=10)
        self._save_button = btn_success(
            "保存",
            width=100,
            on_click=self._save,
        )
        self.controls.append(card(ft.Column([
            section_title("配置项"),
            self._form,
            self._save_button,
        ], spacing=10), padding=0))
        self._populate(DEFAULT_SERVER_PROPERTIES.copy())

    def _pick(self, e: ft.ControlEvent) -> None:
        del e
        if self._busy or self._disposed:
            return
        path = self.app.pick_directory()
        if path:
            self._path_field.value = path
            self._path_field.update()

    def _load(self, e: ft.ControlEvent) -> None:
        del e
        if self._busy or self._disposed:
            return
        target = Path(self._path_field.value or "")
        self._generation += 1
        generation = self._generation
        self._set_busy(True)
        try:
            handle = self._task_scope.submit(
                "load",
                lambda token: self._load_worker(target, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            handle.add_done_callback(
                lambda completed: self._finish_load(
                    completed,
                    target,
                    generation,
                )
            )
        except Exception as error:
            self._apply_operation_error(
                error,
                generation,
                "读取 server.properties 失败",
            )

    def _load_worker(
        self,
        target: Path,
        token: object,
    ) -> Dict[str, str]:
        """在 I/O 通道读取并解析 server.properties。"""
        self._raise_if_cancelled(token)
        props = self._service.load(target)
        self._raise_if_cancelled(token)
        return props

    def _finish_load(
        self,
        handle: OperationHandle[Dict[str, str]],
        target: Path,
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            props = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._post_to_ui(
                self._apply_operation_error,
                error,
                generation,
                "读取 server.properties 失败",
            )
            return
        self._post_to_ui(
            self._apply_load_success,
            props,
            target,
            generation,
        )

    def _apply_load_success(
        self,
        props: Dict[str, str],
        target: Path,
        generation: int,
    ) -> None:
        if not self._is_current(generation):
            return
        self._path = target
        self._set_busy(False)
        self._populate(props)
        self.app.info_dialog("成功", "已读取 server.properties。")

    def _populate(self, props: Dict[str, str]) -> None:
        self._fields.clear()
        self._form.controls.clear()
        for key, value in props.items():
            desc = PROPERTY_DESCRIPTIONS.get(key, "自定义配置项")
            if key in BOOLEAN_PROPERTIES:
                control: ft.Control = ft.Checkbox(
                    label=key,
                    value=str(value).lower() == "true",
                    label_style=ft.TextStyle(
                        color=THEME.text_secondary))
            elif key in ENUM_PROPERTIES:
                control = dropdown(
                    options=[ft.dropdown.Option(v) for v in ENUM_PROPERTIES[key]],
                    value=value,
                    expand=False,
                    width=220,
                )
            else:
                control = text_field(
                    value=str(value),
                    label=key,
                    expand=False,
                    width=260)
            self._fields[key] = control
            self._form.controls.append(ft.Row([
                control,
                ft.Text(desc, size=11, color=THEME.text_muted),
            ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                scroll=ft.ScrollMode.AUTO,
            ))
        safe_update(self)

    def _save(self, e: ft.ControlEvent) -> None:
        del e
        if self._busy or self._disposed:
            return
        try:
            raw_target = (self._path_field.value or "").strip()
            if not raw_target:
                self.app.warn_dialog("提示", "请先选择保存位置。")
                return
            target = Path(raw_target)
            props: Dict[str, str] = {}
            for key, control in self._fields.items():
                if isinstance(control, ft.Checkbox):
                    props[key] = "true" if control.value else "false"
                else:
                    props[key] = str(getattr(control, "value", ""))
        except Exception as error:
            self.app.handle_exception(error, title="保存 server.properties 失败")
            return

        self._generation += 1
        generation = self._generation
        self._set_busy(True)
        try:
            handle = self._task_scope.submit(
                "save",
                lambda token: self._save_worker(target, props, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            handle.add_done_callback(
                lambda completed: self._finish_save(completed, generation)
            )
        except Exception as error:
            self._apply_operation_error(
                error,
                generation,
                "保存 server.properties 失败",
            )

    def _save_worker(
        self,
        target: Path,
        props: Dict[str, str],
        token: object,
    ) -> None:
        """在 I/O 通道校验并原子保存 server.properties。"""
        self._raise_if_cancelled(token)
        self._service.save(target, props)
        self._raise_if_cancelled(token)

    def _finish_save(
        self,
        handle: OperationHandle[None],
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._post_to_ui(
                self._apply_operation_error,
                error,
                generation,
                "保存 server.properties 失败",
            )
            return
        self._post_to_ui(self._apply_save_success, generation)

    def _apply_save_success(self, generation: int) -> None:
        if not self._is_current(generation):
            return
        self._set_busy(False)
        self.app.info_dialog("成功", "server.properties 已保存。")

    def _apply_operation_error(
        self,
        error: Exception,
        generation: int,
        title: str,
    ) -> None:
        if not self._is_current(generation):
            return
        self._set_busy(False)
        self.app.handle_exception(error, title=title)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._path_field.disabled = busy
        self._browse_button.disabled = busy
        self._save_button.disabled = busy
        for control in self._fields.values():
            control.disabled = busy
        safe_update(self)

    def _is_current(self, generation: int) -> bool:
        return not self._disposed and generation == self._generation

    @staticmethod
    def _raise_if_cancelled(token: object) -> None:
        raise_if_cancelled = getattr(token, "raise_if_cancelled", None)
        if callable(raise_if_cancelled):
            raise_if_cancelled()

    def _post_to_ui(
        self,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        """投递后台完成结果；无页面测试环境直接执行。"""
        page = getattr(self.app, "page", None)
        if page is None:
            callback(*args)
            return
        run_on_ui(page, callback, *args)

    def dispose(self) -> None:
        """取消页面任务并使迟到结果失效；可重复调用。"""
        if self._disposed:
            return
        self._disposed = True
        self._generation += 1
        self._busy = False
        self._task_scope.close()
