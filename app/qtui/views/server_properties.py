"""server.properties 图形编辑视图（Qt 版，对应 Flet 树同名视图）。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from pathlib import Path
from typing import Dict, Protocol

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.buttons import btn_ghost, btn_success
from app.qtui.components.cards import card, muted_label, section_title
from app.qtui.components.fields import dropdown, text_field
from app.qtui.components.layout import page_header
from app.qtui.context import (
    QtDialogPort,
    QtFileDialogPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.utils import run_on_ui
from app.qtui.view_actions import QtViewAction
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


class ServerPropertiesHost(
    QtTranslationPort,
    QtDialogPort,
    QtFileDialogPort,
    QtRuntimePort,
    Protocol,
):
    """编辑 server.properties 所需的端口。"""


class ServerPropertiesView(QScrollArea):
    """server.properties 图形编辑视图。

    支持选择服务器根目录、读取默认/现有配置项并写回文件。
    """

    def __init__(self, app: ServerPropertiesHost) -> None:
        """初始化视图并构建表单控件。

        Args:
            app: 页面所需的 UI 与运行时端口。
        """
        super().__init__()
        self.app = app
        self._task_scope = app.execution_runtime.create_scope(
            "server_properties_view"
        )
        self._service = get_server_properties_service(log=app.log)
        self._fields: Dict[str, QWidget] = {}
        self._path = Path("")
        self._generation = 0
        self._busy = False
        self._disposed = False

        self.setWidgetResizable(True)
        self._build()

    def get_top_actions(self) -> list[QtViewAction]:
        """返回壳层顶栏可消费的视图命令。"""
        return [
            QtViewAction(
                self.app.translate("top_bar.read_config", "读取配置"),
                self._load,
            )
        ]

    def _build(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        layout.addWidget(page_header(
            "server.properties 编辑器",
            "读取、编辑并保存 Minecraft 服务器配置文件",
            icon="📄",
        ))

        # 路径卡片
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(10)
        self._path_field = text_field(
            hint_text="选择服务器根目录",
        )
        self._browse_button = btn_ghost("浏览", width=90, on_click=self._pick)
        path_layout.addWidget(self._path_field, 1)
        path_layout.addWidget(self._browse_button)
        path_hint = muted_label(
            "选择路径后，可通过标题栏“读取配置”加载 server.properties。"
        )
        path_card_body = QWidget()
        path_card_layout = QVBoxLayout(path_card_body)
        path_card_layout.setContentsMargins(0, 0, 0, 0)
        path_card_layout.setSpacing(8)
        path_card_layout.addWidget(path_row)
        path_card_layout.addWidget(path_hint)
        layout.addWidget(card(path_card_body, padding=16))

        # 表单卡片
        self._form_grid = QGridLayout()
        self._form_grid.setContentsMargins(0, 0, 0, 0)
        self._form_grid.setHorizontalSpacing(14)
        self._form_grid.setVerticalSpacing(8)
        form_body = QWidget()
        form_layout = QVBoxLayout(form_body)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)
        form_layout.addWidget(section_title("配置项"))
        form_layout.addLayout(self._form_grid)
        self._save_button = btn_success("保存", width=100, on_click=self._save)
        save_row = QWidget()
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 0, 0, 0)
        save_layout.addWidget(self._save_button)
        save_layout.addStretch(1)
        form_layout.addWidget(save_row)
        layout.addWidget(card(form_body, padding=16))

        layout.addStretch(1)
        self.setWidget(content)
        self._populate(DEFAULT_SERVER_PROPERTIES.copy())

    # ─── 用户操作 ───────────────────────────────

    def _pick(self) -> None:
        if self._busy or self._disposed:
            return
        path = self.app.pick_directory()
        if path:
            self._path_field.setText(path)

    def _load(self) -> None:
        if self._busy or self._disposed:
            return
        target = Path(self._path_field.text().strip() or "")
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
            run_on_ui(
                self._apply_operation_error,
                error,
                generation,
                "读取 server.properties 失败",
            )
            return
        run_on_ui(self._apply_load_success, props, target, generation)

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
        self._clear_grid()
        for row, key in enumerate(props):
            value = props[key]
            desc = PROPERTY_DESCRIPTIONS.get(key, "自定义配置项")
            if key in BOOLEAN_PROPERTIES:
                check = QCheckBox(key)
                check.setChecked(str(value).lower() == "true")
                control: QWidget = check
            elif key in ENUM_PROPERTIES:
                control = dropdown(
                    options=list(ENUM_PROPERTIES[key]),
                    value=value,
                    width=220,
                )
            else:
                control = text_field(value=str(value), width=260)
            self._fields[key] = control
            self._form_grid.addWidget(control, row, 0)
            self._form_grid.addWidget(muted_label(desc), row, 1)
        self._form_grid.setColumnStretch(1, 1)

    def _clear_grid(self) -> None:
        """清空表单网格（幂等）。"""
        while self._form_grid.count():
            item = self._form_grid.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _save(self) -> None:
        if self._busy or self._disposed:
            return
        try:
            raw_target = self._path_field.text().strip()
            if not raw_target:
                self.app.warn_dialog("提示", "请先选择保存位置。")
                return
            target = Path(raw_target)
            props: Dict[str, str] = {}
            for key, control in self._fields.items():
                if isinstance(control, QCheckBox):
                    props[key] = "true" if control.isChecked() else "false"
                elif isinstance(control, QComboBox):
                    props[key] = control.currentText()
                elif isinstance(control, QLineEdit):
                    props[key] = control.text()
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
            run_on_ui(
                self._apply_operation_error,
                error,
                generation,
                "保存 server.properties 失败",
            )
            return
        run_on_ui(self._apply_save_success, generation)

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

    # ─── 状态与生命周期 ──────────────────────────

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._path_field.setEnabled(not busy)
        self._browse_button.setEnabled(not busy)
        self._save_button.setEnabled(not busy)
        for control in self._fields.values():
            control.setEnabled(not busy)

    def _is_current(self, generation: int) -> bool:
        return not self._disposed and generation == self._generation

    @staticmethod
    def _raise_if_cancelled(token: object) -> None:
        raise_if_cancelled = getattr(token, "raise_if_cancelled", None)
        if callable(raise_if_cancelled):
            raise_if_cancelled()

    def dispose(self) -> None:
        """取消页面任务并使迟到结果失效；可重复调用。"""
        if self._disposed:
            return
        self._disposed = True
        self._generation += 1
        self._busy = False
        self._task_scope.close()
