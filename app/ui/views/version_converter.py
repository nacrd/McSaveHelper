"""版本升降级视图。"""
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from app.ui.components.buttons import btn_ghost, btn_primary, btn_success, btn_danger
from app.ui.components.cards import card, section_title
from app.ui.theme import THEME

if TYPE_CHECKING:
    from app.application import Application


VERSION_OPTIONS = [
    ("1.21.4", 3953, "最新正式版"),
    ("1.21.0", 3952, ""),
    ("1.20.6", 3839, "数据组件重构"),
    ("1.20.4", 3700, ""),
    ("1.20.2", 3698, ""),
    ("1.20.0", 3692, ""),
    ("1.19.4", 3337, ""),
    ("1.19.2", 3120, ""),
    ("1.18.2", 2975, ""),
    ("1.17.1", 2730, ""),
    ("1.16.5", 2586, ""),
    ("1.12.2", 1343, "扁平化前"),
]

PLATFORM_OPTIONS = [
    ("java", "Java 版"),
    ("bedrock", "基岩版"),
]

WARNINGS = {
    (0, 1343): "从 1.21.x 降到 1.12.2 非常激进，数据组件、新方块和实体都会丢失。",
    (0, 2586): "从 1.21.x 降到 1.16.5，需注意 1.17+ 新增的深板岩、铜等方块会被替换。",
    (0, 2975): "1.18+ 深度扩展到 -64，降级后 y<0 的区块可能异常。",
    (1343, 0): "1.12 -> 新版需要经过扁平化（1.13）和数据组件迁移（1.20.5）。",
}


class VersionConverterView(ft.Column):
    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._build()

    def _build(self) -> None:
        self.controls.clear()
        self.controls.append(ft.Text("版本升降级", size=22, weight=ft.FontWeight.BOLD, color=THEME.text_primary))
        self.controls.append(ft.Text(
            "将存档转换到目标版本。此操作会直接修改文件，请确保已备份。",
            size=12, color=THEME.text_muted,
        ))

        self._src_field = ft.TextField(
            label="源存档目录", hint_text="选择存档目录",
            border_color=THEME.border_tertiary, focused_border_color=THEME.mc_diamond,
            text_size=13, color=THEME.text_primary, bgcolor=THEME.bg_secondary,
            border_radius=0, expand=True,
        )
        self._dst_field = ft.TextField(
            label="输出目录", hint_text="转换后的存档将保存到此处",
            border_color=THEME.border_tertiary, focused_border_color=THEME.mc_diamond,
            text_size=13, color=THEME.text_primary, bgcolor=THEME.bg_secondary,
            border_radius=0, expand=True,
        )
        self.controls.append(card(ft.Column([
            ft.Row([self._src_field, btn_ghost("浏览", width=90, on_click=lambda e: self._pick(self._src_field))], spacing=10),
            ft.Row([self._dst_field, btn_ghost("浏览", width=90, on_click=lambda e: self._pick(self._dst_field))], spacing=10),
        ], spacing=10), padding=16))

        self._platform_dd = ft.Dropdown(
            label="目标平台",
            options=[ft.dropdown.Option(k, v) for k, v in PLATFORM_OPTIONS],
            value="java",
            width=200,
            border_color=THEME.border_standard,
            text_size=13,
        )
        self._version_dd = ft.Dropdown(
            label="目标版本",
            options=[ft.dropdown.Option(str(ver), f"{name} (ID: {ver}){'  — ' + note if note else ''}") for name, ver, note in VERSION_OPTIONS],
            value=str(VERSION_OPTIONS[0][1]),
            width=360,
            border_color=THEME.border_standard,
            text_size=13,
        )
        self._strip_components_cb = ft.Checkbox(
            label="剥离 1.20.5+ 数据组件（降级到旧版时推荐）",
            value=True,
            label_style=ft.TextStyle(color=THEME.text_secondary),
        )
        self._replace_unknown_cb = ft.Checkbox(
            label="将未知方块替换为 air",
            value=True,
            label_style=ft.TextStyle(color=THEME.text_secondary),
        )

        options_row = ft.Row([self._platform_dd, self._version_dd], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.controls.append(card(ft.Column([
            section_title("转换选项"),
            options_row,
            self._strip_components_cb,
            self._replace_unknown_cb,
        ], spacing=10), padding=0))

        self._warn_box = ft.Container(
            content=ft.Text("", size=12, color=THEME.warning),
            padding=ft.Padding(left=16, right=16, top=10, bottom=10),
            bgcolor=THEME.bg_secondary,
            visible=False,
        )
        self.controls.append(self._warn_box)

        btn_row = ft.Row([
            btn_primary("开始转换", width=140, on_click=self._convert),
        ], spacing=10)
        self.controls.append(btn_row)

        self._result_text = ft.Text("", size=13, color=THEME.text_secondary)
        self.controls.append(card(ft.Column([
            section_title("结果"),
            self._result_text,
        ], spacing=6), padding=0))

        self._version_dd.on_change = self._update_warning

    def _pick(self, field: ft.TextField) -> None:
        path = self.app.pick_directory()
        if path:
            field.value = path
            field.update()

    def _update_warning(self, e=None) -> None:
        try:
            target_ver = int(self._version_dd.value or "0")
            if target_ver < 2586:
                self._warn_box.content = ft.Text(
                    f"⚠️ 降到 ID {target_ver} 是一个较大跨度，部分新版本数据可能丢失。请确保已备份存档。",
                    size=12, color=THEME.warning,
                )
                self._warn_box.visible = True
            else:
                self._warn_box.visible = False
            self._warn_box.update()
        except (ValueError, TypeError):
            pass

    def _convert(self, e: ft.ControlEvent) -> None:
        src = Path(self._src_field.value or "")
        dst = Path(self._dst_field.value or "")
        if not (src / "level.dat").exists():
            self.app.warn_dialog("提示", "请选择包含 level.dat 的有效源存档目录。")
            return
        if not dst or str(dst) == ".":
            self.app.warn_dialog("提示", "请选择输出目录。")
            return
        if src.resolve() == dst.resolve():
            self.app.warn_dialog("提示", "源目录和输出目录不能相同。")
            return

        platform = self._platform_dd.value or "java"
        target_version = int(self._version_dd.value or "0")

        self._result_text.value = "正在转换，请稍候..."
        self._result_text.color = THEME.accent
        self._result_text.update()

        try:
            from core.converter import convert_world
            success = convert_world(
                src_path=src,
                dst_path=dst,
                target_platform=platform,
                target_version=target_version,
            )
            if success:
                self._result_text.value = f"✅ 转换完成！输出目录: {dst}"
                self._result_text.color = THEME.success
            else:
                self._result_text.value = "❌ 转换失败，请查看日志。"
                self._result_text.color = THEME.error
        except Exception as ex:
            self._result_text.value = f"❌ 转换出错: {ex}"
            self._result_text.color = THEME.error
            self.app.handle_exception(ex, title="版本转换失败")
        self._result_text.update()
