"""Qt Explorer 玩家 HUD、编辑表单与容器只读投影。"""
from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.presenters.player_presenter import format_player_summary_text
from app.qtui.components.buttons import btn_ghost, btn_primary
from app.qtui.components.cards import muted_label, section_title
from app.qtui.views.player_tasks import PlayerDetailResult
from app.services.player.models import (
    PLAYER_EDIT_SPECS,
    PlayerContainersView,
    PlayerEditSpec,
    PlayerSummary,
)
from app.services.player_service import PlayerService
from core.nbt import Compound
from core.omni.player_manager import PlayerAttribute, PlayerEffect


Translate = Callable[..., str]
Command = Callable[[], None]

_FORM_FIELD_IDS = (
    "Health",
    "foodLevel",
    "foodSaturationLevel",
    "XpLevel",
    "XpTotal",
    "XpP",
    "Air",
    "Pos.0",
    "Pos.1",
    "Pos.2",
    "Dimension",
    "playerGameType",
    "SelectedItemSlot",
    "SpawnX",
    "SpawnY",
    "SpawnZ",
    "SpawnDimension",
    "SpawnForced",
    "abilities.flying",
    "abilities.mayfly",
    "abilities.instabuild",
    "abilities.invulnerable",
    "abilities.mayBuild",
)

_FIELD_LABELS: dict[str, tuple[str, str]] = {
    "Health": ("player.edit.health", "生命值"),
    "foodLevel": ("player.edit.food", "饥饿值"),
    "foodSaturationLevel": ("player.edit.saturation", "饱和度"),
    "XpLevel": ("player.edit.xp_level", "经验等级"),
    "XpTotal": ("player.edit.xp_total", "总经验"),
    "XpP": ("player.edit.xp_p", "经验进度"),
    "Air": ("player.edit.air", "氧气"),
    "Pos.0": ("player.edit.pos_x", "X"),
    "Pos.1": ("player.edit.pos_y", "Y"),
    "Pos.2": ("player.edit.pos_z", "Z"),
    "Dimension": ("player.edit.dimension", "维度"),
    "playerGameType": ("player.edit.game_type", "游戏模式"),
    "SelectedItemSlot": ("player.edit.selected_slot", "选中槽"),
    "SpawnX": ("player.edit.spawn_x", "出生 X"),
    "SpawnY": ("player.edit.spawn_y", "出生 Y"),
    "SpawnZ": ("player.edit.spawn_z", "出生 Z"),
    "SpawnDimension": ("player.edit.spawn_dimension", "出生维度"),
    "SpawnForced": ("player.edit.spawn_forced", "强制出生"),
    "abilities.flying": ("player.edit.flying", "飞行中"),
    "abilities.mayfly": ("player.edit.mayfly", "可飞行"),
    "abilities.instabuild": ("player.edit.instabuild", "瞬间建造"),
    "abilities.invulnerable": ("player.edit.invulnerable", "无敌"),
    "abilities.mayBuild": ("player.edit.may_build", "可建造"),
}

_GAME_TYPES = {
    0: ("player.game_type.survival", "生存"),
    1: ("player.game_type.creative", "创造"),
    2: ("player.game_type.adventure", "冒险"),
    3: ("player.game_type.spectator", "旁观"),
}

_SECTION_DEFS = (
    (0, "player.section.vitals", "生命/经验"),
    (1, "player.section.world", "坐标/出生"),
    (2, "player.section.abilities", "能力"),
    (3, "player.section.advanced", "属性/效果"),
    (4, "player.section.containers", "容器"),
)


class QtPlayerEditor(QWidget):
    """玩家 HUD、分类编辑表单与只读容器投影。"""

    def __init__(
        self,
        translate: Translate,
        on_refresh: Command,
        on_stage: Command,
        on_teleport: Command,
        on_export: Command,
    ) -> None:
        """构建玩家编辑区。

        Args:
            translate: UI 翻译回调。
            on_refresh: 从当前 NBT 回填表单。
            on_stage: 把表单差异暂存到 NBT 区。
            on_teleport: 暂存传送到死亡点。
            on_export: 导出玩家摘要。
        """
        super().__init__()
        self._translate = translate
        self._on_refresh = on_refresh
        self._on_stage = on_stage
        self._on_teleport = on_teleport
        self._on_export = on_export
        self._player_data: Optional[Compound] = None
        self._summary: Optional[PlayerSummary] = None
        self._fields: dict[str, QLineEdit] = {}
        self._section_buttons: list = []
        self._build()
        self.show_empty()

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._translate(key, default, **kwargs)

    @property
    def player_data(self) -> Optional[Compound]:
        """返回当前已加载的玩家 NBT 根。"""
        return self._player_data

    @property
    def summary(self) -> Optional[PlayerSummary]:
        """返回当前玩家摘要。"""
        return self._summary

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)
        self._title = section_title(self._t("player.export.title", "玩家摘要"))
        layout.addWidget(self._title)
        self._uuid_label = muted_label("")
        layout.addWidget(self._uuid_label)
        self._hud = muted_label("")
        self._hud.setWordWrap(True)
        layout.addWidget(self._hud)
        layout.addLayout(self._build_actions())
        layout.addLayout(self._build_section_chips())
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_form_section((
            "Health",
            "foodLevel",
            "foodSaturationLevel",
            "Air",
            "XpLevel",
            "XpTotal",
            "XpP",
            "playerGameType",
            "SelectedItemSlot",
        )))
        self._stack.addWidget(self._build_form_section((
            "Pos.0",
            "Pos.1",
            "Pos.2",
            "Dimension",
            "SpawnX",
            "SpawnY",
            "SpawnZ",
            "SpawnDimension",
            "SpawnForced",
        )))
        self._stack.addWidget(self._build_form_section((
            "abilities.flying",
            "abilities.mayfly",
            "abilities.instabuild",
            "abilities.invulnerable",
            "abilities.mayBuild",
        )))
        self._stack.addWidget(self._build_advanced_section())
        self._stack.addWidget(self._build_containers_section())
        layout.addWidget(self._stack, 1)
        self._set_section(0)

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._export_btn = btn_ghost(
            self._t("player.export_action", "导出"),
            on_click=self._on_export,
        )
        self._teleport_btn = btn_ghost(
            self._t("player.teleport_death", "死亡点"),
            on_click=self._on_teleport,
        )
        self._refresh_btn = btn_ghost(
            self._t("player.edit.refresh", "刷新表单"),
            on_click=self._on_refresh,
        )
        self._stage_btn = btn_primary(
            self._t("player.edit.stage", "暂存修改"),
            on_click=self._on_stage,
        )
        for button in (
            self._export_btn,
            self._teleport_btn,
            self._refresh_btn,
            self._stage_btn,
        ):
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _build_section_chips(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._section_buttons = []
        for index, key, default in _SECTION_DEFS:
            button = btn_ghost(
                self._t(key, default),
                on_click=lambda i=index: self._set_section(i),
            )
            self._section_buttons.append(button)
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _build_form_section(self, field_ids: Sequence[str]) -> QWidget:
        host = QWidget()
        form = QFormLayout(host)
        form.setContentsMargins(0, 4, 0, 4)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for field_id in field_ids:
            key, default = _FIELD_LABELS.get(
                field_id, (f"player.edit.{field_id}", field_id)
            )
            field = QLineEdit()
            field.setClearButtonEnabled(True)
            self._fields[field_id] = field
            form.addRow(self._t(key, default), field)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        return scroll

    def _build_advanced_section(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        layout.addWidget(section_title(self._t(
            "player.attributes.title", "属性 Attributes"
        )))
        self._attributes = QListWidget()
        layout.addWidget(self._attributes, 1)
        layout.addWidget(section_title(self._t(
            "player.effects.title", "状态效果"
        )))
        self._effects = QListWidget()
        layout.addWidget(self._effects, 1)
        return host

    def _build_containers_section(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        self._inventory_title = section_title(self._t(
            "player.export.inventory", "背包:"
        ))
        layout.addWidget(self._inventory_title)
        self._inventory = QListWidget()
        layout.addWidget(self._inventory, 1)
        self._equipment_title = section_title(self._t(
            "player.export.equipment", "装备:"
        ))
        layout.addWidget(self._equipment_title)
        self._equipment = QListWidget()
        layout.addWidget(self._equipment, 1)
        self._ender_title = section_title(self._t(
            "player.export.ender", "末影箱:"
        ))
        layout.addWidget(self._ender_title)
        self._ender = QListWidget()
        layout.addWidget(self._ender, 1)
        return host

    def show_empty(self) -> None:
        """恢复未选择玩家的空状态。"""
        self._player_data = None
        self._summary = None
        self._title.setText(self._t("player.export.title", "玩家摘要"))
        self._uuid_label.clear()
        self.show_message(self._t(
            "player.summary_placeholder", "选择玩家后显示摘要"
        ))
        self._clear_fields()
        self._attributes.clear()
        self._effects.clear()
        self._inventory.clear()
        self._equipment.clear()
        self._ender.clear()
        self._set_enabled(False)

    def show_message(self, message: str) -> None:
        """在 HUD 区域显示纯文本提示。"""
        self._hud.setText(message)

    def show_loading(self, uuid: str) -> None:
        """显示选中玩家详情加载状态。"""
        self._player_data = None
        self._summary = None
        self._uuid_label.setText(uuid)
        self._hud.setText(self._t(
            "player.loading_summary", "正在加载玩家摘要..."
        ))
        self._clear_fields()
        self._attributes.clear()
        self._effects.clear()
        self._inventory.clear()
        self._equipment.clear()
        self._ender.clear()
        self._set_enabled(False)

    def show_unavailable(self, uuid: str) -> None:
        """显示玩家文件已消失或无法读取的状态。"""
        self._player_data = None
        self._summary = None
        self._uuid_label.setText(uuid)
        self._hud.setText(self._t(
            "player.summary_unavailable", "无法读取该玩家的摘要"
        ))
        self._clear_fields()
        self._set_enabled(False)

    def show_detail(self, detail: PlayerDetailResult) -> None:
        """投影完整玩家详情到 HUD、表单与容器列表。"""
        self._player_data = detail.player_data
        self._summary = detail.summary
        if detail.summary is None:
            self.show_unavailable("")
            return
        summary = detail.summary
        self._title.setText(summary.ref.display_name)
        self._uuid_label.setText(
            summary.ref.uuid_hyphen or summary.ref.uuid_norm
        )
        self._hud.setText(self._format_hud(summary))
        self.refresh_form_from_data()
        self._show_attributes(detail.attributes)
        self._show_effects(detail.effects)
        self._show_containers(detail.containers)
        self._set_enabled(True)

    def refresh_form_from_data(self) -> None:
        """用当前玩家 NBT 回填表单字段。"""
        if self._player_data is None:
            self._clear_fields()
            return
        values = PlayerService().form_values_from_data(
            self._player_data,
            specs=self.active_specs(),
        )
        self.apply_field_values(values)

    def apply_field_values(self, values: Mapping[str, str]) -> None:
        """把字段映射写入表单控件。"""
        for field_id, field in self._fields.items():
            field.setText(values.get(field_id, ""))

    def collect_field_values(self) -> dict[str, str]:
        """收集非空表单字段值。"""
        values: dict[str, str] = {}
        for field_id, field in self._fields.items():
            text = field.text().strip()
            if text:
                values[field_id] = text
        return values

    def active_specs(self) -> tuple[PlayerEditSpec, ...]:
        """返回当前表单使用的可编辑规格。"""
        allowed = set(_FORM_FIELD_IDS)
        return tuple(
            spec for spec in PLAYER_EDIT_SPECS if spec.field_id in allowed
        )

    def summary_text(self) -> str:
        """返回 HUD/摘要纯文本，供测试断言。"""
        if self._summary is None:
            return self._hud.text()
        return format_player_summary_text(
            self._summary, translate=self._translate
        )

    def _format_hud(self, summary: PlayerSummary) -> str:
        state = summary.state
        pose = summary.pose
        game_type = state.game_type
        if isinstance(game_type, int) and game_type in _GAME_TYPES:
            key, default = _GAME_TYPES[game_type]
            game_label = self._t(key, default)
        else:
            game_label = "--" if game_type is None else str(game_type)
        pos = (
            f"{_fmt(pose.x)}, {_fmt(pose.y)}, {_fmt(pose.z)}"
            if pose.x is not None
            else "--"
        )
        spawn = summary.spawn
        spawn_text = (
            f"{_fmt(spawn.x)}, {_fmt(spawn.y)}, {_fmt(spawn.z)}"
            if spawn.x is not None
            else "--"
        )
        death = summary.death
        death_text = (
            f"{_fmt(death.dimension)} "
            f"({_fmt(death.x)}, {_fmt(death.y)}, {_fmt(death.z)})"
            if death is not None
            else "--"
        )
        lines = [
            format_player_summary_text(summary, translate=self._translate),
            "",
            (
                f"{self._t('player.hud.game_type', '模式')}: {game_label} · "
                f"{self._t('explorer.position', '坐标')}: {pos}"
            ),
            (
                f"{self._t('player.hud.spawn', '出生')}: {spawn_text} · "
                f"{self._t('player.hud.death', '死亡')}: {death_text}"
            ),
        ]
        return "\n".join(lines)

    def _show_attributes(self, attributes: Sequence[PlayerAttribute]) -> None:
        self._attributes.clear()
        if not attributes:
            self._attributes.addItem(self._t(
                "player.attributes.empty", "无属性数据"
            ))
            return
        for attr in attributes:
            text = (
                f"{attr.name}: base={_fmt(attr.base)} "
                f"mods={attr.modifiers}"
            )
            self._attributes.addItem(QListWidgetItem(text))

    def _show_effects(self, effects: Sequence[PlayerEffect]) -> None:
        self._effects.clear()
        if not effects:
            self._effects.addItem(self._t(
                "player.effects.empty", "无状态效果"
            ))
            return
        for effect in effects:
            text = (
                f"{effect.id} · amp={effect.amplifier} · "
                f"dur={effect.duration}"
            )
            self._effects.addItem(QListWidgetItem(text))

    def _show_containers(
        self,
        containers: Optional[PlayerContainersView],
    ) -> None:
        self._fill_item_list(
            self._inventory,
            () if containers is None else containers.inventory,
            empty_key=("player.inventory.empty", "背包为空"),
        )
        self._fill_item_list(
            self._equipment,
            () if containers is None else containers.equipment,
            empty_key=("player.equipment.empty", "无装备"),
        )
        self._fill_item_list(
            self._ender,
            () if containers is None else containers.ender_items,
            empty_key=("player.ender.empty", "末影箱为空"),
        )
        inv = 0 if containers is None else len(containers.inventory)
        eq = 0 if containers is None else len(containers.equipment)
        ender = 0 if containers is None else len(containers.ender_items)
        self._inventory_title.setText(
            f"{self._t('player.export.inventory', '背包:')} ({inv})"
        )
        self._equipment_title.setText(
            f"{self._t('player.export.equipment', '装备:')} ({eq})"
        )
        self._ender_title.setText(
            f"{self._t('player.export.ender', '末影箱:')} ({ender})"
        )

    def _fill_item_list(
        self,
        widget: QListWidget,
        items: Sequence[Mapping[str, object]],
        *,
        empty_key: tuple[str, str],
    ) -> None:
        widget.clear()
        if not items:
            widget.addItem(self._t(empty_key[0], empty_key[1]))
            return
        for item in items:
            slot = item.get("slot", "?")
            item_id = item.get("id", "?")
            count = item.get("count", 1)
            widget.addItem(QListWidgetItem(f"[{slot}] {item_id} x{count}"))

    def _clear_fields(self) -> None:
        for field in self._fields.values():
            field.clear()

    def _set_enabled(self, enabled: bool) -> None:
        for button in (
            self._export_btn,
            self._teleport_btn,
            self._refresh_btn,
            self._stage_btn,
            *self._section_buttons,
        ):
            button.setEnabled(enabled)
        for field in self._fields.values():
            field.setEnabled(enabled)
        self._stack.setEnabled(enabled)

    def _set_section(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for position, button in enumerate(self._section_buttons):
            button.setProperty("role", "primary" if position == index else "ghost")
            button.style().unpolish(button)
            button.style().polish(button)


def _fmt(value: object) -> str:
    if value is None:
        return "--"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


__all__ = ["QtPlayerEditor", "_FORM_FIELD_IDS"]
