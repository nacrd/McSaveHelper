"""Migrator View —— 存档转换主界面"""
import flet as ft
from typing import TYPE_CHECKING, Optional, Any
from pathlib import Path

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox, label
from app.ui.components.cards import card, section_title

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


class MigratorView(ft.Column):
    """存档转换视图 — 左右两栏布局"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app: "Application" = app
        self._build()

    @property
    def _t(self):
        return self.app._t

    def _build(self) -> None:
        self.controls.clear()
        content = ft.Row(
            [self._build_left(), ft.Container(width=18), self._build_right()],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.controls.append(content)

    # ─── 左栏 ──────────────────────────────────

    def _build_left(self) -> ft.Column:
        col = ft.Column(spacing=18)
        col.expand = True
        col.controls.append(self._build_dir_card())
        col.controls.append(self._build_version_card())
        col.controls.append(self._build_player_card())
        return col

    def _build_dir_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("left_panel.archive_config", "📁 存档配置")))

        self._src_field = text_field(
            label=self._t("left_panel.client_archive", "源存档"),
            hint_text=self._t("left_panel.placeholder_select_world", "选择世界文件夹 (包含 level.dat)"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        s.controls.append(ft.Container(
            content=ft.Row([
                self._src_field,
                btn_ghost(self._t("left_panel.browse", "📂 浏览"), width=90, height=38,
                          on_click=lambda e: self.app.set_src()),
            ], spacing=10),
            padding=ft.Padding(left=20, right=20, bottom=8),
        ))

        self._dest_field = text_field(
            label=self._t("left_panel.server_root", "输出目录"),
            hint_text=self._t("left_panel.placeholder_default_dir", "默认为程序当前目录"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        s.controls.append(ft.Container(
            content=ft.Row([
                self._dest_field,
                btn_ghost(self._t("left_panel.browse", "📂 浏览"), width=90, height=38,
                          on_click=lambda e: self.app.set_dest()),
            ], spacing=10),
            padding=ft.Padding(left=20, right=20, bottom=8),
        ))

        self._name_field = text_field(
            label=self._t("left_panel.world_folder_name", "世界文件夹名"),
            hint_text=self._t("left_panel.placeholder_world_name", "例如: world"),
            value=mc.world_name or "world",
            on_change=lambda e: self._sync_field_to_config(),
        )
        s.controls.append(ft.Container(
            content=self._name_field,
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    def _build_version_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title("🔄 版本转换"))

        self._vc_platform_dd = ft.Dropdown(
            options=[ft.dropdown.Option(k, v) for k, v in PLATFORM_OPTIONS],
            value=mc.target_platform or "java",
            width=150,
            border_color=THEME.border_standard,
            text_size=13,
            on_select=lambda e: setattr(self.app.config.migration, "target_platform", e.control.value),
        )
        self._vc_version_dd = ft.Dropdown(
            options=[ft.dropdown.Option(
                str(ver), f"{name} (ID: {ver}){'  — ' + note if note else ''}"
            ) for name, ver, note in VERSION_OPTIONS],
            value=mc.target_version or str(VERSION_OPTIONS[0][1]),
            width=280,
            border_color=THEME.border_standard,
            text_size=13,
            on_select=self._on_version_change,
        )
        s.controls.append(ft.Container(
            content=ft.Row([
                ft.Column([label("目标平台"), self._vc_platform_dd], spacing=4),
                ft.Column([label("目标版本"), self._vc_version_dd], spacing=4),
            ], spacing=16),
            padding=ft.Padding(left=20, right=20, top=12, bottom=8),
        ))

        self._vc_strip_cb = ft.Checkbox(
            label="剥离 1.20.5+ 数据组件（降级到旧版时推荐）",
            value=True,
            label_style=ft.TextStyle(color=THEME.text_secondary),
        )
        self._vc_replace_cb = ft.Checkbox(
            label="将未知方块替换为 air",
            value=True,
            label_style=ft.TextStyle(color=THEME.text_secondary),
        )
        self._vc_options_col = ft.Column(
            [self._vc_strip_cb, self._vc_replace_cb], spacing=4,
        )
        s.controls.append(ft.Container(
            content=self._vc_options_col,
            padding=ft.Padding(left=20, right=20, bottom=8),
        ))

        self._vc_warn_box = ft.Text("", size=11, color=THEME.warning, visible=False)
        s.controls.append(ft.Container(
            content=self._vc_warn_box,
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    def _build_player_card(self) -> ft.Container:
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("left_panel.player_config", "👥 玩家配置")))

        self._manual_field = text_field(
            label="手动指定玩家 (选填)",
            hint_text=self._t("left_panel.placeholder_manual_names",
                              "多个玩家用英文逗号分隔，例如: Steve, Alex"),
            on_change=lambda e: self._sync_field_to_config(),
        )
        s.controls.append(ft.Container(
            content=self._manual_field,
            padding=ft.Padding(left=20, right=20, bottom=8),
        ))

        s.controls.append(ft.Container(
            content=ft.Text("UUID 查询", size=12, weight=ft.FontWeight.BOLD, color=THEME.text_secondary),
            padding=ft.Padding(left=20, right=20, bottom=4),
        ))
        self._query_field = text_field(
            hint_text="输入玩家名查询 UUID", expand=True,
        )
        s.controls.append(ft.Container(
            content=ft.Row([
                self._query_field,
                btn_primary("查询", width=90, height=38,
                            on_click=lambda e: self._query_uuid()),
            ], spacing=10),
            padding=ft.Padding(left=20, right=20, bottom=8),
        ))

        self._query_result = ft.Text(
            "在此显示查询结果",
            size=11, color=THEME.text_muted,
        )
        s.controls.append(ft.Container(
            content=ft.Container(
                content=self._query_result, bgcolor=THEME.log_bg,
                border=ft.Border(
                    left=ft.BorderSide(1, THEME.log_border),
                    top=ft.BorderSide(1, THEME.log_border),
                    right=ft.BorderSide(1, THEME.log_border),
                    bottom=ft.BorderSide(1, THEME.log_border),
                ),
                border_radius=8,
                padding=12, height=100,
            ),
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    # ─── 右栏 ──────────────────────────────────

    def _build_right(self) -> ft.Column:
        col = ft.Column(spacing=18)
        col.expand = True
        col.controls.append(self._build_mode_card())
        col.controls.append(self._build_options_card())
        col.controls.append(self._build_batch_card())
        return col

    def _build_mode_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("right_panel.mode_settings", "⚙️ 转换模式")))

        self._mode_fast = ft.Radio(value="fast",
                                    label=self._t("right_panel.fast_mode", "⚡ 快速模式"))
        self._mode_full = ft.Radio(value="full",
                                    label=self._t("right_panel.full_mode", "🧠 完整模式"))
        mode_group = ft.RadioGroup(
            content=ft.Row([self._mode_fast, self._mode_full], spacing=30),
            value=mc.mode, on_change=self._on_mode_change,
        )
        s.controls.append(ft.Container(
            content=mode_group,
            padding=ft.Padding(left=20, right=20, top=12, bottom=8),
        ))

        self._mode_desc = ft.Text(
            "⚡ 快速模式：仅复制UUID文件，速度最快",
            size=11, color=THEME.text_muted,
        )
        s.controls.append(ft.Container(
            content=self._mode_desc,
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    def _build_options_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("right_panel.migration_options", "📦 处理选项")))

        self._offline_cb = checkbox(
            self._t("right_panel.offline_mode", "离线模式（不请求 Mojang API）"),
            value=mc.offline_mode,
            on_change=lambda e: setattr(self.app.config.migration, 'offline_mode', e.control.value),
        )
        self._clean_cb = checkbox(
            self._t("right_panel.clean_mode", "精简存档（移除缓存/日志）"),
            value=mc.clean_mode,
            on_change=lambda e: setattr(self.app.config.migration, 'clean_mode', e.control.value),
        )
        self._pure_clean_cb = checkbox(
            self._t("right_panel.pure_clean_mode", "纯净扫描（移除模组方块/实体）"),
            value=mc.pure_clean_mode,
            on_change=lambda e: setattr(self.app.config.migration, 'pure_clean_mode', e.control.value),
        )

        cb_col = ft.Column(
            [self._offline_cb, self._clean_cb, self._pure_clean_cb],
            spacing=8,
        )
        s.controls.append(ft.Container(
            content=cb_col,
            padding=ft.Padding(left=20, right=20, top=12, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        return c

    def _build_batch_card(self) -> ft.Container:
        mc = self.app.config.migration
        s = ft.Column(spacing=0)
        s.controls.append(section_title("📦 批量处理"))

        self._batch_mode_cb = checkbox(
            self._t("right_panel.batch_mode", "启用批量模式（一次处理多个存档）"),
            value=mc.batch_mode,
            on_change=lambda e: self._toggle_batch(e.control.value),
        )
        s.controls.append(ft.Container(
            content=self._batch_mode_cb,
            padding=ft.Padding(left=20, right=20, top=12, bottom=8),
        ))

        self._batch_dir_field = text_field(
            label="批量存档目录",
            hint_text="选择包含多个世界存档的目录",
            on_change=lambda e: self._sync_field_to_config(),
        )
        self._batch_scan_btn = btn_primary("🔍 扫描", width=90, height=38,
                                            on_click=lambda e: self._scan_batch())
        self._batch_result = ft.Text("", size=11, color=THEME.text_muted)
        self._batch_detail_col = ft.Column([
            ft.Row([
                self._batch_dir_field,
                btn_ghost("📂 浏览", width=90, height=38,
                          on_click=lambda e: self.app.set_batch_dir()),
                self._batch_scan_btn,
            ], spacing=10),
            self._batch_result,
        ], spacing=8)
        s.controls.append(ft.Container(
            content=self._batch_detail_col,
            padding=ft.Padding(left=20, right=20, bottom=18),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self._batch_detail_col.visible = mc.batch_mode
        return c

    # ─── 联动回调 ──────────────────────────────

    def _on_mode_change(self, e: ft.ControlEvent) -> None:
        mc = self.app.config.migration
        mc.mode = e.control.value
        is_fast = e.control.value == "fast"

        self._mode_desc.value = (
            "⚡ 快速模式：仅复制UUID文件，速度最快"
            if is_fast
            else "🧠 完整模式：深度 NBT 修补 + 版本转换 + 物品ID迁移"
        )

        self._vc_options_col.disabled = is_fast
        if is_fast:
            self._vc_warn_box.visible = False
        else:
            self._on_version_update()

        self.update()

    def _on_version_change(self, e: ft.ControlEvent) -> None:
        self.app.config.migration.target_version = self._vc_version_dd.value or ""
        self._on_version_update()
        self.update()

    def _on_version_update(self) -> None:
        if self._mode_fast.value == "fast":
            return
        try:
            target_ver = int(self._vc_version_dd.value or "0")
            if target_ver < 2586:
                self._vc_warn_box.value = f"⚠️ 降到 ID {target_ver} 是较大跨度，部分新版本数据可能丢失。请确保已备份存档。"
                self._vc_warn_box.visible = True
                self._vc_strip_cb.value = True
                self._vc_replace_cb.value = True
            else:
                self._vc_warn_box.visible = False
        except (ValueError, TypeError):
            pass

    def _toggle_batch(self, enabled: bool) -> None:
        self.app.config.migration.batch_mode = enabled
        self._batch_detail_col.visible = enabled
        self._batch_detail_col.update()

    # ─── 工具回调 ──────────────────────────────

    def _sync_field_to_config(self) -> None:
        mc = self.app.config.migration
        mc.src_path = self._src_field.value or ""
        mc.dest_path = self._dest_field.value or ""
        mc.world_name = self._name_field.value or "world"
        mc.batch_dir_path = self._batch_dir_field.value or ""
        mc.manual_names = self._manual_field.value or ""
        mc.target_platform = self._vc_platform_dd.value or "java"
        mc.target_version = self._vc_version_dd.value or ""

    def _scan_batch(self) -> None:
        mc = self.app.config.migration
        result = self.app.migration.scan_batch_dir(mc.batch_dir_path)
        if result:
            self._batch_result.value = self.app.migration.scan_result
            self.app.log(self._t("messages.batch_scan_complete",
                                 "批量扫描完成: 找到 {count} 个世界存档",
                                 count=len(result)), "SUCCESS")
        else:
            self._batch_result.value = self._t("messages.no_valid_worlds",
                                               "未找到有效的世界存档")
            self.app.log(self._t("messages.batch_scan_no_worlds",
                                 "批量扫描: 未找到有效的世界存档"), "WARN")
        self._batch_result.update()

    def _query_uuid(self) -> None:
        name = self._query_field.value.strip()
        if not name:
            return
        offline_uuid = self.app.uuid.generate_offline_uuid(name)
        online_uuid, official_name = self.app.uuid.query_online_uuid(name, self.app.log)

        lines = [f"玩家: {name}"]
        lines.append(f"离线 UUID: {offline_uuid}")
        if online_uuid:
            lines.append(f"正版 UUID: {online_uuid}")
            if official_name and official_name != name:
                lines.append(f"官方名称: {official_name}")
        else:
            lines.append("正版 UUID: 未获取到（可能为离线账号）")

        self._query_result.value = "\n".join(lines)
        self._query_result.update()
