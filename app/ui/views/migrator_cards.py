"""Migrator card builders — pure UI composition for MigratorView."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import flet as ft

from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.components.cards import card, section_title
from app.ui.components.fields import checkbox, current_save_field, label, text_field
from app.ui.theme import THEME, mc_border
from app.ui.views.migrator_options import (
    PLATFORM_OPTIONS,
    VERSION_OPTIONS,
    format_version_label,
    mode_description,
)


Translate = Callable[..., str]
SimpleCallback = Callable[[], None]
ValueCallback = Callable[[Any], None]


@dataclass
class DirectoryCardControls:
    container: ft.Container
    src_field: ft.Control
    dest_field: ft.Control
    name_field: ft.Control


@dataclass
class VersionCardControls:
    container: ft.Container
    platform_dd: ft.Dropdown
    version_dd: ft.Dropdown
    strip_cb: ft.Checkbox
    replace_cb: ft.Checkbox
    warn_box: ft.Text


@dataclass
class PlayerCardControls:
    container: ft.Container
    manual_field: ft.Control
    query_field: ft.Control
    query_result: ft.Text


@dataclass
class ModeCardControls:
    container: ft.Container
    mode_group: ft.RadioGroup
    mode_desc: ft.Text


@dataclass
class OptionsCardControls:
    container: ft.Container
    offline_cb: ft.Control
    clean_cb: ft.Control
    pure_clean_cb: ft.Control


@dataclass
class BatchCardControls:
    container: ft.Container
    batch_mode_cb: ft.Control
    batch_dir_field: ft.Control
    batch_scan_btn: ft.Control
    batch_result: ft.Text
    batch_detail_col: ft.Column


def build_guide_card() -> ft.Container:
    """Build the migrator usage guide card."""
    return ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    '📖 操作指南',
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                ft.Container(height=8),
                ft.Text(
                    (
                        '1. 设置源存档：在左侧边栏点击「设置当前存档」'
                        + '\n' + '2. 选择输出目录：点击「浏览」按钮选择目标位置'
                        + '\n' + '3. 选择目标版本：在版本转换区域选择目标 Minecraft 版本'
                        + '\n' + '4. 开始转换：点击顶部「开始转换」按钮'
                        + '\n' + '\n' + '💡 提示：转换前建议备份原始存档'
                    ),
                    size=12,
                    color=THEME.text_secondary,
                ),
            ]
        ),
        bgcolor=THEME.bg_secondary,
        padding=16,
        border_radius=8,
        border=ft.Border.all(1, THEME.border_subtle),
    )


def build_directory_card(
    *,
    translate: Translate,
    src_path: str,
    dest_path: str,
    world_name: str,
    on_field_change: SimpleCallback,
    on_browse_dest: SimpleCallback,
) -> DirectoryCardControls:
    """Build the source/destination directory configuration card."""
    section = ft.Column(spacing=0)
    section.controls.append(
        section_title(translate("left_panel.archive_config", "📁 存档配置"))
    )
    section.controls.append(
        ft.Container(
            content=ft.Text(
                "设置要转换的源存档和输出位置",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        )
    )

    src_field = current_save_field(
        label="当前源存档",
        hint_text="请通过侧边栏「设置当前存档」设置世界文件夹 (包含 level.dat)",
    )
    src_field.value = src_path
    src_field.on_change = lambda _e: on_field_change()
    section.controls.append(
        ft.Container(
            content=src_field,
            padding=ft.Padding(left=20, right=20, bottom=12),
        )
    )

    dest_field = text_field(
        label=translate("left_panel.server_root", "输出目录"),
        hint_text=translate(
            "left_panel.placeholder_default_dir",
            "默认为程序当前目录",
        ),
        value=dest_path,
        on_change=lambda _e: on_field_change(),
    )
    section.controls.append(
        ft.Container(
            content=ft.Row(
                [
                    dest_field,
                    btn_ghost(
                        translate("left_panel.browse", "📂 浏览"),
                        width=90,
                        height=38,
                        on_click=lambda _e: on_browse_dest(),
                    ),
                ],
                spacing=10,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        )
    )

    name_field = text_field(
        label=translate("left_panel.world_folder_name", "世界文件夹名"),
        hint_text=translate("left_panel.placeholder_world_name", "例如: world"),
        value=world_name or "world",
        on_change=lambda _e: on_field_change(),
    )
    section.controls.append(
        ft.Container(
            content=name_field,
            padding=ft.Padding(left=20, right=20, bottom=20),
        )
    )

    container = card(ft.Column(spacing=0), padding=0)
    container.content = section
    return DirectoryCardControls(
        container=container,
        src_field=src_field,
        dest_field=dest_field,
        name_field=name_field,
    )


def build_version_card(
    *,
    target_platform: str,
    target_version: str,
    on_platform_change: ValueCallback,
    on_version_change: SimpleCallback,
) -> VersionCardControls:
    """Build the target platform/version conversion card."""
    section = ft.Column(spacing=0)
    section.controls.append(section_title("🔄 版本转换"))
    section.controls.append(
        ft.Container(
            content=ft.Text(
                "选择目标平台和版本，配置转换选项",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        )
    )

    platform_dd = ft.Dropdown(
        options=[ft.dropdown.Option(k, v) for k, v in PLATFORM_OPTIONS],
        value=target_platform or "java",
        width=150,
        border_color=THEME.border_standard,
        text_size=13,
        on_select=lambda e: on_platform_change(e.control.value),
    )
    version_dd = ft.Dropdown(
        options=[
            ft.dropdown.Option(
                str(ver),
                format_version_label(name, ver, note),
            )
            for name, ver, note in VERSION_OPTIONS
        ],
        value=target_version or str(VERSION_OPTIONS[0][1]),
        width=280,
        border_color=THEME.border_standard,
        text_size=13,
        on_select=lambda _e: on_version_change(),
    )
    section.controls.append(
        ft.Container(
            content=ft.Row(
                [
                    ft.Column([label("目标平台"), platform_dd], spacing=4),
                    ft.Column([label("目标版本"), version_dd], spacing=4),
                ],
                spacing=16,
            ),
            padding=ft.Padding(left=20, right=20, top=12, bottom=12),
        )
    )

    strip_cb = ft.Checkbox(
        label="剥离 1.20.5+ 数据组件（降级到旧版时推荐）",
        value=True,
        label_style=ft.TextStyle(color=THEME.text_secondary),
    )
    replace_cb = ft.Checkbox(
        label="将未知方块替换为 air",
        value=True,
        label_style=ft.TextStyle(color=THEME.text_secondary),
    )
    section.controls.append(
        ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "高级选项",
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=THEME.text_secondary,
                    ),
                    ft.Container(height=8),
                    strip_cb,
                    replace_cb,
                    ft.Container(height=8),
                    ft.Text(
                        "💡 降级到旧版本时，建议启用这些选项以避免兼容性问题",
                        size=11,
                        color=THEME.text_muted,
                    ),
                ],
                spacing=8,
            ),
            padding=ft.Padding(left=12, right=12, top=12, bottom=12),
            bgcolor=THEME.bg_secondary,
            border_radius=6,
            margin=ft.Margin(left=12, right=12, top=0, bottom=0),
        )
    )

    warn_box = ft.Text("", size=11, color=THEME.warning, visible=False)
    section.controls.append(
        ft.Container(
            content=warn_box,
            padding=ft.Padding(left=20, right=20, bottom=20),
        )
    )

    container = card(ft.Column(spacing=0), padding=0)
    container.content = section
    return VersionCardControls(
        container=container,
        platform_dd=platform_dd,
        version_dd=version_dd,
        strip_cb=strip_cb,
        replace_cb=replace_cb,
        warn_box=warn_box,
    )


def build_player_card(
    *,
    translate: Translate,
    manual_names: str,
    on_field_change: SimpleCallback,
    on_query_uuid: SimpleCallback,
) -> PlayerCardControls:
    """Build the player configuration and UUID query card."""
    section = ft.Column(spacing=0)
    section.controls.append(
        section_title(translate("left_panel.player_config", "👥 玩家配置"))
    )
    section.controls.append(
        ft.Container(
            content=ft.Text(
                "配置玩家数据转换和 UUID 映射",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        )
    )

    manual_field = text_field(
        label="手动指定玩家 (选填)",
        hint_text=translate(
            "left_panel.placeholder_manual_names",
            "多个玩家用英文逗号分隔，例如: Steve, Alex",
        ),
        value=manual_names,
        on_change=lambda _e: on_field_change(),
    )
    section.controls.append(
        ft.Container(
            content=manual_field,
            padding=ft.Padding(left=20, right=20, bottom=12),
        )
    )
    section.controls.append(
        ft.Container(
            content=ft.Divider(height=1, color=THEME.border_subtle),
            padding=ft.Padding(left=20, right=20, top=8, bottom=8),
        )
    )
    section.controls.append(
        ft.Container(
            content=ft.Text(
                "UUID 查询",
                size=12,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_secondary,
            ),
            padding=ft.Padding(left=20, right=20, bottom=8),
        )
    )
    section.controls.append(
        ft.Container(
            content=ft.Text(
                "输入玩家名查询对应的 UUID，用于离线模式玩家数据转换",
                size=11,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=8),
        )
    )

    query_field = text_field(hint_text="输入玩家名查询 UUID", expand=True)
    section.controls.append(
        ft.Container(
            content=ft.Row(
                [
                    query_field,
                    btn_primary(
                        "查询",
                        width=90,
                        height=38,
                        on_click=lambda _e: on_query_uuid(),
                    ),
                ],
                spacing=10,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        )
    )

    query_result = ft.Text("在此显示查询结果", size=11, color=THEME.text_muted)
    section.controls.append(
        ft.Container(
            content=ft.Container(
                content=query_result,
                bgcolor=THEME.log_bg,
                border=mc_border(2),
                border_radius=6,
                padding=12,
                height=120,
            ),
            padding=ft.Padding(left=20, right=20, bottom=20),
        )
    )

    container = card(ft.Column(spacing=0), padding=0)
    container.content = section
    return PlayerCardControls(
        container=container,
        manual_field=manual_field,
        query_field=query_field,
        query_result=query_result,
    )


def build_mode_card(
    *,
    translate: Translate,
    mode: str,
    on_mode_change: ValueCallback,
) -> ModeCardControls:
    """Build the conversion mode selection card."""
    section = ft.Column(spacing=0)
    section.controls.append(
        section_title(translate("right_panel.mode_settings", "⚙️ 转换模式"))
    )
    section.controls.append(
        ft.Container(
            content=ft.Text(
                "选择转换模式，影响转换速度和完整性",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=12),
        )
    )

    mode_fast = ft.Radio(
        value="fast",
        label=translate("right_panel.fast_mode", "⚡ 快速模式"),
    )
    mode_full = ft.Radio(
        value="full",
        label=translate("right_panel.full_mode", "🧠 完整模式"),
    )
    mode_group = ft.RadioGroup(
        content=ft.Row([mode_fast, mode_full], spacing=30),
        value=mode,
        on_change=lambda _: on_mode_change(mode_group.value or "fast"),
    )
    section.controls.append(
        ft.Container(
            content=mode_group,
            padding=ft.Padding(left=20, right=20, top=12, bottom=12),
        )
    )

    mode_desc = ft.Text(mode_description(mode or "fast"), size=11, color=THEME.text_muted)
    section.controls.append(
        ft.Container(
            content=mode_desc,
            padding=ft.Padding(left=20, right=20, bottom=20),
        )
    )

    container = card(ft.Column(spacing=0), padding=0)
    container.content = section
    return ModeCardControls(
        container=container,
        mode_group=mode_group,
        mode_desc=mode_desc,
    )


def build_options_card(
    *,
    translate: Translate,
    offline_mode: bool,
    clean_mode: bool,
    pure_clean_mode: bool,
    on_offline_change: ValueCallback,
    on_clean_change: ValueCallback,
    on_pure_clean_change: ValueCallback,
) -> OptionsCardControls:
    """Build the migration processing options card."""
    section = ft.Column(spacing=0)
    section.controls.append(
        section_title(translate("right_panel.migration_options", "📦 处理选项"))
    )

    offline_cb = checkbox(
        translate("right_panel.offline_mode", "离线模式（不请求 Mojang API）"),
        value=offline_mode,
        on_change=lambda e: on_offline_change(e.control.value),
    )
    clean_cb = checkbox(
        translate("right_panel.clean_mode", "精简存档（移除缓存/日志）"),
        value=clean_mode,
        on_change=lambda e: on_clean_change(e.control.value),
    )
    pure_clean_cb = checkbox(
        translate("right_panel.pure_clean_mode", "纯净扫描（移除模组方块/实体）"),
        value=pure_clean_mode,
        on_change=lambda e: on_pure_clean_change(e.control.value),
    )

    section.controls.append(
        ft.Container(
            content=ft.Column([offline_cb, clean_cb, pure_clean_cb], spacing=8),
            padding=ft.Padding(left=20, right=20, top=12, bottom=18),
        )
    )

    container = card(ft.Column(spacing=0), padding=0)
    container.content = section
    return OptionsCardControls(
        container=container,
        offline_cb=offline_cb,
        clean_cb=clean_cb,
        pure_clean_cb=pure_clean_cb,
    )


def build_batch_card(
    *,
    translate: Translate,
    batch_mode: bool,
    batch_dir_path: str,
    on_toggle_batch: ValueCallback,
    on_field_change: SimpleCallback,
    on_browse_batch: SimpleCallback,
    on_scan_batch: SimpleCallback,
) -> BatchCardControls:
    """Build the batch processing card."""
    section = ft.Column(spacing=0)
    section.controls.append(section_title("📦 批量处理"))

    batch_mode_cb = checkbox(
        translate("right_panel.batch_mode", "启用批量模式（一次处理多个存档）"),
        value=batch_mode,
        on_change=lambda e: on_toggle_batch(e.control.value),
    )
    section.controls.append(
        ft.Container(
            content=batch_mode_cb,
            padding=ft.Padding(left=20, right=20, top=12, bottom=8),
        )
    )

    batch_dir_field = text_field(
        label="批量存档目录",
        hint_text="包含多个世界存档的目录",
        value=batch_dir_path,
        on_change=lambda _e: on_field_change(),
    )
    batch_scan_btn = btn_primary(
        "🔍 扫描",
        width=90,
        height=38,
        on_click=lambda _e: on_scan_batch(),
    )
    batch_result = ft.Text("", size=11, color=THEME.text_muted)
    batch_detail_col = ft.Column(
        [
            ft.Row(
                [
                    batch_dir_field,
                    btn_ghost(
                        "📂 浏览",
                        width=90,
                        height=38,
                        on_click=lambda _e: on_browse_batch(),
                    ),
                    batch_scan_btn,
                ],
                spacing=10,
            ),
            batch_result,
        ],
        spacing=8,
    )
    batch_detail_col.visible = batch_mode
    section.controls.append(
        ft.Container(
            content=batch_detail_col,
            padding=ft.Padding(left=20, right=20, bottom=18),
        )
    )

    container = card(ft.Column(spacing=0), padding=0)
    container.content = section
    return BatchCardControls(
        container=container,
        batch_mode_cb=batch_mode_cb,
        batch_dir_field=batch_dir_field,
        batch_scan_btn=batch_scan_btn,
        batch_result=batch_result,
        batch_detail_col=batch_detail_col,
    )
