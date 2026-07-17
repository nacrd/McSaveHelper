"""server.properties 图形编辑视图。"""
from pathlib import Path
from typing import TYPE_CHECKING, Dict

import flet as ft

from app.services.server_properties_service import (
    BOOLEAN_PROPERTIES,
    DEFAULT_SERVER_PROPERTIES,
    ENUM_PROPERTIES,
    PROPERTY_DESCRIPTIONS,
    get_server_properties_service,
)
from app.ui.components.buttons import btn_ghost, btn_success
from app.ui.components.cards import card, section_title
from app.ui.icons import IconSet
from app.ui.components.fields import text_field, dropdown
from app.ui.components.layout import page_header
from app.ui.theme import THEME
from app.ui.view_actions import ViewAction

if TYPE_CHECKING:
    from app.application import Application


class ServerPropertiesView(ft.Column):
    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._service = get_server_properties_service(log=app.log)
        self._fields: Dict[str, ft.Control] = {}
        self._path = Path("")
        self._build()

    def get_top_actions(self) -> list[ViewAction]:
        return [
            ViewAction(
                self.app.translate("top_bar.read_config", "读取配置"),
                self._load,
            )
        ]

    def _build(self) -> None:
        self.controls.clear()
        self.controls.append(
            page_header(
                "server.properties 编辑器",
                ft.Text(
                    "读取、编辑并保存 Minecraft 服务器配置文件",
                    size=12,
                    color=THEME.text_muted),
                icon=IconSet.CLIPBOARD,
            ))
        self._path_field = text_field(
            label="服务器根目录或 server.properties",
            hint_text="选择服务器根目录")
        self.controls.append(card(ft.Column([
            ft.Row([self._path_field, btn_ghost("浏览", width=90, on_click=self._pick)], spacing=10),
            ft.Text("选择路径后，可通过顶栏“读取配置”加载 server.properties。", size=11, color=THEME.text_muted),
        ], spacing=10), padding=16))
        self._form = ft.Column(spacing=10)
        self.controls.append(card(ft.Column([section_title("配置项"), self._form, btn_success(
            "保存", width=100, on_click=self._save)], spacing=10), padding=0))
        self._populate(DEFAULT_SERVER_PROPERTIES.copy())

    def _pick(self, e: ft.ControlEvent) -> None:
        path = self.app.pick_directory()
        if path:
            self._path_field.value = path
            self._path_field.update()

    def _load(self, e: ft.ControlEvent) -> None:
        try:
            self._path = Path(self._path_field.value or "")
            props = self._service.load(self._path)
            self._populate(props)
            self.app.info_dialog("成功", "已读取 server.properties。")
        except Exception as ex:
            self.app.handle_exception(ex, title="读取 server.properties 失败")

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
            ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        try:
            self.update()
        except RuntimeError:
            pass

    def _save(self, e: ft.ControlEvent) -> None:
        try:
            target = Path(self._path_field.value or "")
            if not target:
                self.app.warn_dialog("提示", "请先选择保存位置。")
                return
            props: Dict[str, str] = {}
            for key, control in self._fields.items():
                if isinstance(control, ft.Checkbox):
                    props[key] = "true" if control.value else "false"
                else:
                    props[key] = str(getattr(control, "value", ""))
            self._service.save(target, props)
            self.app.info_dialog("成功", "server.properties 已保存。")
        except Exception as ex:
            self.app.handle_exception(ex, title="保存 server.properties 失败")
