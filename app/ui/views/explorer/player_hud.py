"""Player HUD Card component."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import flet as ft

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update

Translate = Callable[..., str]

_GAME_TYPES = {
    0: ("player.game_type.survival", "生存"),
    1: ("player.game_type.creative", "创造"),
    2: ("player.game_type.adventure", "冒险"),
    3: ("player.game_type.spectator", "旁观"),
}


class PlayerHUDCard(ft.Column):
    """Player status quick view with optional avatar image."""

    def __init__(self, t_cb: Optional[Translate] = None) -> None:
        super().__init__(spacing=8)
        self._t = t_cb or (lambda key, default="", **_kw: default or key)
        self._attrs: Dict[str, ft.Text] = {}

        self._avatar = ft.CircleAvatar(
            content=ft.Text("?", size=16, color=THEME.text_primary),
            radius=22,
            bgcolor=THEME.bg_secondary,
        )
        self._name_text = ft.Text(
            "--",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_primary,
            expand=True,
        )
        self._uuid_text = ft.Text(
            "",
            size=11,
            color=THEME.text_muted,
            expand=True,
        )

        self.controls.append(
            ft.Text(
                self._t("explorer.player_status", "玩家状态"),
                size=16,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            )
        )
        self.controls.append(
            ft.Row(
                [
                    self._avatar,
                    ft.Column(
                        [self._name_text, self._uuid_text],
                        spacing=2,
                        expand=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

        rows_data = [
            ("health", "explorer.health", "生命值", "♥"),
            ("food", "explorer.food", "饥饿值", "🍖"),
            ("level", "explorer.level", "经验等级", "⭐"),
            ("air", "explorer.air", "氧气", "🌊"),
            ("game_type", "player.hud.game_type", "游戏模式", "🎮"),
            ("dimension", "explorer.dimension", "维度", "🌍"),
            ("pos", "explorer.position", "坐标", "📍"),
            ("spawn", "player.hud.spawn", "出生点", "🛏️"),
            ("death", "player.hud.death", "死亡位置", "💀"),
            ("selected", "player.hud.selected_slot", "选中槽", "🔢"),
        ]

        for key, i18n_key, default_label, icon in rows_data:
            lbl = ft.Text(
                f"{icon} {self._t(i18n_key, default_label)}:",
                size=13,
                color=THEME.text_secondary,
            )
            val = ft.Text(
                "--",
                size=13,
                weight=ft.FontWeight.BOLD,
                color=THEME.accent_light,
                expand=True,
            )
            self._attrs[key] = val
            self.controls.append(ft.Row([lbl, val], spacing=10))

    def set_avatar_src(self, avatar_src: Optional[str], initial: str = "?") -> None:
        """Update only the avatar art, keeping name/uuid labels."""
        if avatar_src:
            self._avatar.content = ft.Image(
                src=avatar_src,
                width=44,
                height=44,
                fit=ft.BoxFit.COVER,
                border_radius=22,
            )
        else:
            letter = (initial or "?")[:1].upper()
            self._avatar.content = ft.Text(
                letter,
                size=16,
                color=THEME.text_primary,
            )
        safe_update(self)

    def set_identity(
        self,
        name: str,
        uuid_text: str,
        *,
        avatar_src: Optional[str] = None,
        initial: str = "?",
    ) -> None:
        self._name_text.value = name or "--"
        self._uuid_text.value = uuid_text or ""
        if avatar_src:
            self._avatar.content = ft.Image(
                src=avatar_src,
                width=44,
                height=44,
                fit=ft.BoxFit.COVER,
                border_radius=22,
            )
        else:
            letter = (initial or name or "?")[:1].upper()
            self._avatar.content = ft.Text(
                letter,
                size=16,
                color=THEME.text_primary,
            )
        safe_update(self)

    def update_from_summary(self, summary: Any) -> None:
        """Update HUD from a PlayerSummary-like object."""
        if summary is None:
            return
        try:
            state = summary.state
            pose = summary.pose
            spawn = summary.spawn
            death = summary.death
            ref = summary.ref

            self.set_identity(
                ref.display_name,
                ref.uuid_hyphen or ref.uuid_norm,
                initial=(ref.name or ref.uuid_norm or "?")[:1],
            )

            self._set_text(
                "health",
                self._fmt_ratio(state.health, 20),
            )
            self._set_text(
                "food",
                self._fmt_ratio(state.food_level, 20),
            )
            self._set_text("level", self._fmt(state.xp_level))
            self._set_text("air", self._fmt(state.air))
            self._set_game_type(state.game_type)
            self._set_dimension(state.dimension)
            self._set_pos(pose.x, pose.y, pose.z)
            self._set_text(
                "spawn",
                self._fmt_xyz_dim(spawn.x, spawn.y, spawn.z, spawn.dimension),
            )
            if death is None:
                self._set_text("death", "--")
            else:
                self._set_text(
                    "death",
                    self._fmt_xyz_dim(
                        death.x, death.y, death.z, death.dimension
                    ),
                )
            self._set_text("selected", self._fmt(state.selected_slot))
        except (TypeError, ValueError, AttributeError):
            pass
        safe_update(self)

    def update_from_nbt(self, player_data: Any) -> None:
        """Legacy path: update from raw NBT compound."""
        if player_data is None:
            return
        try:
            self._set_numeric_attribute(player_data, "Health", "health", " / 20")
            self._set_numeric_attribute(
                player_data, "foodLevel", "food", " / 20"
            )
            self._set_numeric_attribute(player_data, "XpLevel", "level")
            self._set_numeric_attribute(player_data, "Air", "air")
            self._set_game_type(
                self._as_int(
                    player_data.get(
                        "playerGameType", player_data.get("GameType")
                    )
                )
            )
            self._set_dimension_attribute(player_data.get("Dimension"))
            self._set_position_attribute(player_data.get("Pos"))
            spawn_x = player_data.get("SpawnX")
            if spawn_x is not None:
                self._set_text(
                    "spawn",
                    self._fmt_xyz_dim(
                        self._as_float(spawn_x),
                        self._as_float(player_data.get("SpawnY")),
                        self._as_float(player_data.get("SpawnZ")),
                        str(player_data.get("SpawnDimension") or ""),
                    ),
                )
            selected = player_data.get("SelectedItemSlot")
            if selected is not None:
                self._set_text("selected", str(int(selected)))
        except (TypeError, ValueError, AttributeError):
            pass
        safe_update(self)

    def _set_numeric_attribute(
        self,
        player_data: Any,
        nbt_key: str,
        attribute: str,
        suffix: str = "",
    ) -> None:
        value = player_data.get(nbt_key)
        if value is not None:
            self._attrs[attribute].value = f"{int(value)}{suffix}"

    def _set_dimension_attribute(self, dimension: Any) -> None:
        self._set_dimension(str(dimension) if dimension is not None else None)

    def _set_position_attribute(self, position: Any) -> None:
        if position is None or len(position) < 3:
            return
        self._set_pos(
            float(position[0]),
            float(position[1]),
            float(position[2]),
        )

    def _set_dimension(self, dimension: Optional[str]) -> None:
        if not dimension:
            return
        dimension_name = str(dimension).lower()
        labels = (
            ("overworld", self._t("player.dim.overworld", "主世界")),
            ("nether", self._t("player.dim.nether", "下界")),
            ("end", self._t("player.dim.end", "末地")),
        )
        self._attrs["dimension"].value = next(
            (
                label
                for marker, label in labels
                if marker in dimension_name
            ),
            dimension_name,
        )

    def _set_game_type(self, game_type: Optional[int]) -> None:
        if game_type is None:
            return
        key_default = _GAME_TYPES.get(int(game_type))
        if key_default is None:
            self._attrs["game_type"].value = str(game_type)
            return
        key, default = key_default
        self._attrs["game_type"].value = self._t(key, default)

    def _set_pos(
        self,
        x: Optional[float],
        y: Optional[float],
        z: Optional[float],
    ) -> None:
        if x is None or y is None or z is None:
            return
        self._attrs["pos"].value = f"{x:.1f}, {y:.1f}, {z:.1f}"

    def _set_text(self, key: str, value: str) -> None:
        if key in self._attrs:
            self._attrs[key].value = value

    @staticmethod
    def _fmt(value: Any) -> str:
        if value is None:
            return "--"
        return str(value)

    @staticmethod
    def _fmt_ratio(value: Any, total: int) -> str:
        if value is None:
            return "--"
        try:
            return f"{int(float(value))} / {total}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _fmt_xyz_dim(
        x: Any,
        y: Any,
        z: Any,
        dimension: Any,
    ) -> str:
        if x is None and y is None and z is None:
            return "--"
        try:
            coords = f"{float(x):.1f}, {float(y):.1f}, {float(z):.1f}"
        except (TypeError, ValueError):
            coords = f"{x}, {y}, {z}"
        if dimension:
            return f"{coords} @ {dimension}"
        return coords

    @staticmethod
    def _as_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
