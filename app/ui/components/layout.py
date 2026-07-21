"""Shared layout helpers for application workspaces."""
from __future__ import annotations

from typing import Callable, Iterable, List, NamedTuple

import flet as ft

from app.ui.theme import THEME, TEXT_SECONDARY_SIZE, mc_border
from app.ui.icons import IconSet


class TabSpec(NamedTuple):
    """Small descriptor for a segmented tab in a view."""

    label: str
    icon: ft.IconData


class PageHeader(ft.Container):
    """Page title and contextual command host."""

    def __init__(
        self,
        title: str,
        subtitle: ft.Control,
        icon: ft.IconData,
        actions: ft.Control | None = None,
        status: ft.Control | None = None,
    ) -> None:
        """Build a responsive header with commands adjacent to its title."""
        if isinstance(subtitle, ft.Text):
            current_size = float(subtitle.size or 0)
            if current_size < TEXT_SECONDARY_SIZE:
                subtitle.size = TEXT_SECONDARY_SIZE
        self.action_row = ft.Row(
            spacing=6,
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        if actions is not None:
            self.action_row.controls = [actions]
        self.status_host = ft.Container(
            content=status,
            visible=status is not None,
        )
        self._trailing = ft.Row(
            [self.status_host, self.action_row],
            spacing=10,
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._identity = _build_page_identity(title, subtitle, icon)
        self._identity.expand = True
        self._layout = ft.Row(
            [self._identity, self._trailing],
            spacing=10,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        super().__init__(
            content=self._layout,
            padding=ft.Padding(left=0, right=0, top=0, bottom=14),
            border=ft.Border(
                bottom=ft.BorderSide(1, THEME.border_subtle),
            ),
        )

    def set_compact_layout(self, compact: bool) -> None:
        """Keep title, status, and commands visible in constrained widths.

        Args:
            compact: Whether the header should stack its trailing controls.
        """
        self._trailing.alignment = (
            ft.MainAxisAlignment.START
            if compact
            else ft.MainAxisAlignment.END
        )


def _build_page_identity(
    title: str,
    subtitle: ft.Control,
    icon: ft.IconData,
) -> ft.Row:
    """Build the stable identity group shared by page headers."""
    return ft.Row(
        [
            ft.Container(
                content=ft.Icon(icon, size=20, color=THEME.accent),
                width=40,
                height=40,
                alignment=ft.Alignment(0, 0),
                bgcolor=THEME.bg_elevated,
                border=ft.Border.all(1, THEME.border_standard),
                border_radius=6,
            ),
            ft.Column(
                [
                    ft.Text(
                        title,
                        size=20,
                        weight=ft.FontWeight.W_600,
                        color=THEME.text_primary,
                    ),
                    subtitle,
                ],
                spacing=2,
            ),
        ],
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def page_header(
    title: str,
    subtitle: ft.Control,
    icon: ft.IconData = IconSet.SETTINGS,
    actions: ft.Control | None = None,
    status: ft.Control | None = None,
) -> PageHeader:
    """Create the shared page title bar used by full-page views."""
    return PageHeader(title, subtitle, icon, actions, status)


def panel(
    content: ft.Control,
    padding: int = 12,
    bgcolor: str | None = None,
) -> ft.Container:
    """Create a bordered layout panel for grouping page sections."""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=bgcolor or THEME.bg_card,
        border=mc_border(1),
        border_radius=6,
    )


def section_header(title: str, subtitle: str = "") -> ft.Row:
    """Create a compact section header with optional helper text."""
    controls: List[ft.Control] = [
        ft.Container(width=3, height=18, bgcolor=THEME.accent, border_radius=2),
        ft.Text(
            title,
            size=14,
            weight=ft.FontWeight.W_600,
            color=THEME.text_primary,
        ),
    ]
    if subtitle:
        controls.append(
            ft.Text(
                subtitle,
                size=TEXT_SECONDARY_SIZE,
                color=THEME.text_muted,
            )
        )
    return ft.Row(
        controls,
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def segmented_tab_bar(
    tabs: Iterable[TabSpec],
    selected_index: int,
    on_select: Callable[[int], None],
) -> tuple[ft.Container, ft.Row, List[ft.Container], List[ft.Text]]:
    """Build a compact Minecraft-style segmented tab bar.

    Returns the bar plus internals that existing responsive code can adjust.
    """
    labels: List[ft.Text] = []
    buttons: List[ft.Container] = []
    controls: List[ft.Control] = []

    for idx, tab in enumerate(tabs):
        selected = idx == selected_index
        label = ft.Text(
            tab.label,
            size=TEXT_SECONDARY_SIZE,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_primary if selected else THEME.text_secondary,
        )
        button = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        tab.icon,
                        size=17,
                        color=THEME.accent if selected else THEME.text_muted,
                    ),
                    label,
                ],
                spacing=7,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=100,
            height=44,
            alignment=ft.Alignment(0, 0),
            padding=ft.Padding(left=10, right=10, top=6, bottom=6),
            bgcolor=THEME.bg_elevated if selected else ft.Colors.TRANSPARENT,
            border=ft.Border.all(
                1,
                THEME.border_standard if selected else ft.Colors.TRANSPARENT,
            ),
            border_radius=6,
            on_click=lambda e, i=idx: on_select(i),
            ink=True,
        )
        labels.append(label)
        buttons.append(button)
        controls.append(button)

    row = ft.Row(controls, spacing=4, scroll=ft.ScrollMode.AUTO)
    bar = ft.Container(
        content=row,
        padding=4,
        bgcolor=THEME.bg_secondary,
        border=ft.Border.all(1, THEME.border_subtle),
        border_radius=6,
    )
    return bar, row, buttons, labels
