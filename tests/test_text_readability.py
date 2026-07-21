"""Global typography and contrast contracts for normal UI controls."""
from typing import cast

import flet as ft

from app.ui.components.buttons import btn_ghost
from app.ui.components.cards import placeholder, section_title
from app.ui.components.fields import checkbox, dropdown, label, text_field
from app.ui.components.layout import page_header
from app.ui.icons import IconSet
from app.ui.theme import (
    DARK_THEME,
    LIGHT_THEME,
    TEXT_BODY_SIZE,
    TEXT_LABEL_SIZE,
)


def test_shared_controls_use_readable_text_sizes() -> None:
    button = btn_ghost("操作")
    field = text_field(label="名称")
    select = dropdown(["a"], value="a")
    check = checkbox("启用")
    field_label = label("说明")
    heading = section_title("分组")
    empty = placeholder(title="暂无", subtitle="请先加载")

    button_content = cast(ft.Row, button._button.content)
    assert cast(ft.Text, button_content.controls[1]).size == TEXT_BODY_SIZE
    assert field.text_size == TEXT_BODY_SIZE
    assert select.text_size == TEXT_BODY_SIZE
    assert check.label_style is not None
    assert check.label_style.size == TEXT_BODY_SIZE
    assert field_label.size == TEXT_LABEL_SIZE
    assert isinstance(heading.content, ft.Row)
    heading_row = cast(ft.Row, heading.content)
    assert cast(ft.Text, heading_row.controls[1]).size == TEXT_BODY_SIZE
    assert isinstance(empty.content, ft.Column)
    empty_column = cast(ft.Column, empty.content)
    assert cast(ft.Text, empty_column.controls[4]).size == TEXT_BODY_SIZE


def test_page_header_raises_small_subtitles_to_secondary_size() -> None:
    subtitle = ft.Text("页面说明", size=10)

    page_header("标题", subtitle, IconSet.INFO)

    assert subtitle.size == 13


def test_muted_text_meets_normal_helper_contrast() -> None:
    def luminance(color: str) -> float:
        channels = [
            int(color[index:index + 2], 16) / 255
            for index in (1, 3, 5)
        ]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return sum(
            channel * weight
            for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722))
        )

    def contrast(first: str, second: str) -> float:
        light, dark = sorted(
            (luminance(first), luminance(second)),
            reverse=True,
        )
        return (light + 0.05) / (dark + 0.05)

    assert contrast(LIGHT_THEME.text_muted, LIGHT_THEME.bg_secondary) >= 4.5
    assert contrast(DARK_THEME.text_muted, DARK_THEME.bg_secondary) >= 4.5
