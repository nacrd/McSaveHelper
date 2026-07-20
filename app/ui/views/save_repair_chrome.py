"""UI composition for the save repair view."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List

import flet as ft

from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.components.cards import card, section_title
from app.ui.components.fields import checkbox, current_save_field
from app.ui.components.layout import page_header
from app.ui.icons import IconSet
from app.ui.theme import THEME, mc_border

EventCallback = Callable[[Any], None]


@dataclass(frozen=True)
class SaveRepairChrome:
    controls: List[ft.Control]
    world_path_field: Any
    fix_chunks_checkbox: Any
    fix_players_checkbox: Any
    fix_level_dat_checkbox: Any
    backup_checkbox: Any
    log_column: ft.Column
    world_info_text: ft.Text
    world_info_card: ft.Container
    detect_result_text: ft.Text
    detect_result_card: ft.Container
    result_text: ft.Text
    detect_button: Any
    repair_button: Any
    cancel_button: Any


def build_save_repair_chrome(
    *,
    on_detect: EventCallback,
    on_repair: EventCallback,
    on_cancel: EventCallback,
) -> SaveRepairChrome:
    """Build save repair controls and return their stable references."""
    fields = _build_save_repair_fields(on_detect, on_repair, on_cancel)
    cards = _build_save_repair_cards(fields)
    return SaveRepairChrome(
        controls=[
            cards["header"],
            ft.Container(height=8),
            cards["config_card"],
            cards["world_info_card"],
            cards["detect_result_card"],
            cards["result_card"],
            cards["log_card"],
            cards["info_card"],
        ],
        world_path_field=fields["world_path_field"],
        fix_chunks_checkbox=fields["fix_chunks_checkbox"],
        fix_players_checkbox=fields["fix_players_checkbox"],
        fix_level_dat_checkbox=fields["fix_level_dat_checkbox"],
        backup_checkbox=fields["backup_checkbox"],
        log_column=fields["log_column"],
        world_info_text=fields["world_info_text"],
        world_info_card=cards["world_info_card"],
        detect_result_text=fields["detect_result_text"],
        detect_result_card=cards["detect_result_card"],
        result_text=fields["result_text"],
        detect_button=fields["detect_button"],
        repair_button=fields["repair_button"],
        cancel_button=fields["cancel_button"],
    )


def _build_save_repair_fields(
    on_detect: EventCallback,
    on_repair: EventCallback,
    on_cancel: EventCallback,
) -> dict[str, Any]:
    """Create form controls for the save-repair view."""
    world_path_field = current_save_field(
        hint_text="请通过侧边栏「设置当前存档」设置要修复的当前存档目录",
    )
    world_path_field.expand = True
    fix_chunks_checkbox = checkbox("修复区块", value=True)
    fix_players_checkbox = checkbox("修复玩家数据", value=True)
    fix_level_dat_checkbox = checkbox("修复 level.dat", value=True)
    backup_checkbox = checkbox("创建备份（推荐）", value=True)
    log_column = ft.Column(
        spacing=2,
        scroll=ft.ScrollMode.AUTO,
        height=200,
    )
    world_info_text = ft.Text(
        "",
        size=12,
        color=THEME.text_secondary,
        selectable=True,
    )
    detect_result_text = ft.Text(
        "",
        size=13,
        color=THEME.text_secondary,
        selectable=True,
    )
    result_text = ft.Text(
        "",
        size=13,
        color=THEME.text_secondary,
        selectable=True,
    )
    detect_button = btn_primary("检测存档", on_click=on_detect)
    repair_button = btn_primary("开始修复", on_click=on_repair)
    cancel_button = btn_ghost("取消", on_click=on_cancel)
    cancel_button.visible = False
    return {
        "world_path_field": world_path_field,
        "fix_chunks_checkbox": fix_chunks_checkbox,
        "fix_players_checkbox": fix_players_checkbox,
        "fix_level_dat_checkbox": fix_level_dat_checkbox,
        "backup_checkbox": backup_checkbox,
        "log_column": log_column,
        "world_info_text": world_info_text,
        "detect_result_text": detect_result_text,
        "result_text": result_text,
        "detect_button": detect_button,
        "repair_button": repair_button,
        "cancel_button": cancel_button,
    }


def _build_save_repair_cards(fields: dict[str, Any]) -> dict[str, Any]:
    """Assemble cards used by the save-repair layout."""
    header = page_header(
        "存档修复",
        ft.Text(
            "检测存档状态、修复损坏的区块、玩家数据、level.dat",
            size=12,
            color=THEME.text_muted,
        ),
        icon=IconSet.BUILD,
    )
    return {
        "header": header,
        "config_card": _build_save_repair_config_card(fields),
        "world_info_card": _result_card(
            "世界信息",
            fields["world_info_text"],
            visible=False,
        ),
        "detect_result_card": _result_card(
            "检测结果",
            fields["detect_result_text"],
            visible=False,
        ),
        "result_card": _result_card("修复结果", fields["result_text"]),
        "log_card": _build_save_repair_log_card(fields),
        "info_card": _build_save_repair_info_card(),
    }


def _build_save_repair_config_card(fields: dict[str, Any]) -> ft.Control:
    return card(
        ft.Column(
            [
                section_title("当前存档"),
                fields["world_path_field"],
                ft.Container(height=12),
                section_title("操作"),
                ft.Row(
                    [
                        fields["detect_button"],
                        fields["repair_button"],
                        fields["cancel_button"],
                    ],
                    spacing=12,
                ),
                ft.Container(height=12),
                section_title("修复选项"),
                ft.Column(
                    [
                        fields["fix_chunks_checkbox"],
                        fields["fix_players_checkbox"],
                        fields["fix_level_dat_checkbox"],
                        fields["backup_checkbox"],
                    ],
                    spacing=8,
                ),
            ],
            spacing=12,
        )
    )


def _build_save_repair_log_card(fields: dict[str, Any]) -> ft.Control:
    return card(
        ft.Column(
            [
                section_title("执行日志"),
                ft.Container(
                    content=fields["log_column"],
                    padding=8,
                    bgcolor=THEME.bg_secondary,
                    border_radius=4,
                    border=mc_border(1),
                ),
            ],
            spacing=12,
        )
    )


def _build_save_repair_info_card() -> ft.Control:
    return card(
        ft.Column(
            [
                section_title("使用说明"),
                ft.Text(
                    "• 检测存档：只读扫描，报告世界信息和潜在问题，不修改任何文件\n"
                    "• 修复区块：检测损坏的区块数据，隔离无法读取的区域文件\n"
                    "• 修复玩家数据：验证并补充缺失的必需字段（Pos/Health 等）\n"
                    "• 修复 level.dat：检查并从备份恢复，补充缺失的世界配置字段\n"
                    "• 建议先执行检测，确认问题后再进行修复",
                    size=12,
                    color=THEME.text_secondary,
                ),
            ],
            spacing=12,
        )
    )


def _result_card(
    title: str,
    text: ft.Text,
    *,
    visible: bool = True,
) -> ft.Container:
    return ft.Container(
        content=card(
            ft.Column(
                [
                    section_title(title),
                    ft.Container(
                        content=text,
                        padding=12,
                        bgcolor=THEME.bg_secondary,
                        border_radius=8,
                    ),
                ],
                spacing=12,
            )
        ),
        visible=visible,
    )
