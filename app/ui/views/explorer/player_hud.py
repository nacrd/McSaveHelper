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
            h = player_data.get("Health")
            if h is not None:
                self._attrs["health"].value = f"{int(h)} / 20"
            f = player_data.get("foodLevel")
            if f is not None:
                self._attrs["food"].value = f"{int(f)} / 20"
            lvl = player_data.get("XpLevel")
            if lvl is not None:
                self._attrs["level"].value = str(int(lvl))
            a = player_data.get("Air")
            if a is not None:
                self._attrs["air"].value = str(int(a))
            dim = player_data.get("Dimension")
            if dim is not None:
                ds = str(dim).lower()
                if "overworld" in ds:
                    self._attrs["dimension"].value = "主世界"
                elif "nether" in ds:
                    self._attrs["dimension"].value = "下界"
                elif "end" in ds:
                    self._attrs["dimension"].value = "末地"
                else:
                    self._attrs["dimension"].value = ds
            pos = player_data.get("Pos")
            if pos is not None and len(pos) >= 3:
                self._attrs["pos"].value = f"{
                    float(
                        pos[0]):.1f}, {
                    float(
                        pos[1]):.1f}, {
                    float(
                        pos[2]):.1f}"
        except Exception:
            pass
        safe_update(self)
