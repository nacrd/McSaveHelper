"""Unified icon system - replaces emoji with vector icons"""
from flet import Icons
import flet as ft
from typing import Optional


class IconSet:
    """Centralized icon definitions using Flet's Material Icons"""

    # Navigation & Tabs
    MAP = Icons.MAP_OUTLINED
    PACKAGE = Icons.INVENTORY_2_OUTLINED
    BUILD = Icons.BUILD_OUTLINED
    BALANCE = Icons.BALANCE_OUTLINED
    LINK = Icons.LINK_OUTLINED
    CLIPBOARD = Icons.DESCRIPTION_OUTLINED
    SETTINGS = Icons.SETTINGS_OUTLINED

    # Actions
    EXPLORE = Icons.EXPLORE_OUTLINED
    EARTH = Icons.PUBLIC_OUTLINED
    PERSON = Icons.PERSON_OUTLINE
    GRID = Icons.GRID_ON_OUTLINED
    STATS = Icons.BAR_CHART_OUTLINED
    SEARCH = Icons.SEARCH_OUTLINED
    DOCUMENT = Icons.ARTICLE_OUTLINED

    # Common UI
    PICKAXE = Icons.HARDWARE_OUTLINED
    FOLDER = Icons.FOLDER_OUTLINED
    FOLDER_OPEN = Icons.FOLDER_OPEN_OUTLINED
    SAVE = Icons.SAVE_OUTLINED
    REFRESH = Icons.REFRESH
    COPY = Icons.CONTENT_COPY_OUTLINED
    DELETE = Icons.DELETE_OUTLINE
    ERROR = Icons.ERROR_OUTLINE
    WARNING = Icons.WARNING_OUTLINED
    INFO = Icons.INFO_OUTLINED
    SUCCESS = Icons.CHECK_CIRCLE_OUTLINE
    CLOSE = Icons.CLOSE

    # Window Controls
    MINIMIZE = Icons.MINIMIZE
    MAXIMIZE = Icons.CHECK_BOX_OUTLINE_BLANK
    RESTORE = Icons.FILTER_NONE_OUTLINED

    # File Operations
    UPLOAD = Icons.UPLOAD_OUTLINED
    DOWNLOAD = Icons.DOWNLOAD_OUTLINED
    EXPORT = Icons.FILE_DOWNLOAD_OUTLINED
    IMPORT = Icons.FILE_UPLOAD_OUTLINED

    # Indicators
    ARROW_RIGHT = Icons.ARROW_FORWARD
    ARROW_LEFT = Icons.ARROW_BACK
    CHEVRON_RIGHT = Icons.CHEVRON_RIGHT
    CHEVRON_DOWN = Icons.KEYBOARD_ARROW_DOWN

    # Content
    BLOCK = Icons.VIEW_IN_AR_OUTLINED
    ENTITY = Icons.PETS_OUTLINED

    # Time
    CLOCK = Icons.ACCESS_TIME_OUTLINED
    HISTORY = Icons.HISTORY


def icon(
    name: str,
    size: Optional[float] = None,
    color: Optional[str] = None,
) -> ft.Icon:
    """Create a Flet Icon with consistent styling

    Args:
        name: Icon name from IconSet (e.g., IconSet.MAP)
        size: Icon size in pixels (default: 20)
        color: Icon color (default: None, inherits from theme)

    Returns:
        ft.Icon: Configured icon
    """
    return ft.Icon(
        name,
        size=size or 20,
        color=color,
    )


def icon_text(
    icon_name: str,
    text: str,
    icon_size: float = 16,
    text_size: float = 13,
    icon_color: Optional[str] = None,
    text_color: Optional[str] = None,
    spacing: float = 8,
) -> ft.Row:
    """Create an icon + text row with consistent spacing

    Args:
        icon_name: Icon name from IconSet
        text: Text to display
        icon_size: Icon size in pixels
        text_size: Text size in pixels
        icon_color: Icon color
        text_color: Text color
        spacing: Space between icon and text

    Returns:
        ft.Row: Icon and text row
    """
    return ft.Row(
        [
            icon(icon_name, size=icon_size, color=icon_color),
            ft.Text(
                text,
                size=text_size,
                color=text_color,
            ),
        ],
        spacing=spacing,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
