"""Player HUD Card component"""
import flet as ft
from typing import Any, Dict

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update


class PlayerHUDCard(ft.Column):
    """玩家状态快速视图"""

    def __init__(self, t_cb=None) -> None:
        super().__init__(spacing=8)
        self._t = t_cb or (lambda k, d="", **kw: d)
        self._attrs: Dict[str, ft.Text] = {}

        rows_data = [
            ("health", "生命值", "♥"),
            ("food", "饥饿值", "🍖"),
            ("level", "经验等级", "⭐"),
            ("air", "氧气", "🌊"),
            ("dimension", "维度", "🌍"),
            ("pos", "坐标", "📍"),
        ]

        self.controls.append(
            ft.Text(
                "玩家状态",
                size=16,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary))

        for key, label_text, icon in rows_data:
            lbl = ft.Text(
                f"{icon} {label_text}:",
                size=13,
                color=THEME.text_secondary)
            val = ft.Text(
                "--",
                size=13,
                weight=ft.FontWeight.BOLD,
                color=THEME.accent_light)
            self._attrs[key] = val
            self.controls.append(ft.Row([lbl, val], spacing=10))

    def update_from_nbt(self, player_data: Any) -> None:
        if player_data is None:
            return
        try:
            self._set_numeric_attribute(player_data, "Health", "health", " / 20")
            self._set_numeric_attribute(player_data, "foodLevel", "food", " / 20")
            self._set_numeric_attribute(player_data, "XpLevel", "level")
            self._set_numeric_attribute(player_data, "Air", "air")
            self._set_dimension_attribute(player_data.get("Dimension"))
            self._set_position_attribute(player_data.get("Pos"))
        except Exception:
            pass
        safe_update(self)

    def _set_numeric_attribute(
        self, player_data: Any, nbt_key: str, attribute: str, suffix: str = ""
    ) -> None:
        value = player_data.get(nbt_key)
        if value is not None:
            self._attrs[attribute].value = f"{int(value)}{suffix}"

    def _set_dimension_attribute(self, dimension: Any) -> None:
        if dimension is None:
            return
        dimension_name = str(dimension).lower()
        labels = (("overworld", "主世界"), ("nether", "下界"), ("end", "末地"))
        self._attrs["dimension"].value = next(
            (label for marker, label in labels if marker in dimension_name), dimension_name
        )

    def _set_position_attribute(self, position: Any) -> None:
        if position is None or len(position) < 3:
            return
        self._attrs["pos"].value = ", ".join(
            f"{float(position[index]):.1f}" for index in range(3)
        )
