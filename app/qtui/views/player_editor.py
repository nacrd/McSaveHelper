"""Qt Explorer 玩家 HUD、编辑表单与物品格子投影。"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QHBoxLayout,
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
from app.qtui.views.equipment_preview import QtEquipmentPreview
from app.qtui.views.inventory_grid import QtInventoryGrid
from app.qtui.views.player_tasks import PlayerDetailResult
from app.services.item_service import ItemService
from app.services.player.models import (
    PLAYER_EDIT_SPECS,
    PlayerContainersView,
    PlayerEditSpec,
    PlayerSummary,
)
from app.services.player_service import PlayerService
from app.services.texture_service import TextureService
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
    """玩家 HUD、分类编辑表单与物品格子投影。"""

    def __init__(
        self,
        translate: Translate,
        on_refresh: Command,
        on_stage: Command,
        on_teleport: Command,
        on_export: Command,
        *,
        item_service: ItemService | None = None,
        texture_service: TextureService | None = None,
        player_service: PlayerService | None = None,
    ) -> None:
        """构建玩家编辑区。

        Args:
            translate: UI 翻译回调。
            on_refresh: 从当前 NBT 回填表单。
            on_stage: 把表单差异暂存到 NBT 区。
            on_teleport: 暂存传送到死亡点。
            on_export: 导出玩家摘要。
            item_service: 物品解析服务（格子投影）。
            texture_service: 可选贴图服务。
            player_service: 潜影盒等嵌套容器解析。
        """
        super().__init__()
        self._translate = translate
        self._on_refresh = on_refresh
        self._on_stage = on_stage
        self._on_teleport = on_teleport
        self._on_export = on_export
        self._item_service = item_service or ItemService()
        self._texture_service = texture_service
        self._player_service = player_service or PlayerService()
        self._player_data: Optional[Compound] = None
        self._summary: Optional[PlayerSummary] = None
        self._fields: dict[str, QLineEdit] = {}
        self._section_buttons: list = []
        self._container_tab = 0
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
        identity = QHBoxLayout()
        identity.setSpacing(10)
        self._avatar = QLabel("?")
        self._avatar.setFixedSize(48, 48)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setStyleSheet(
            "QLabel { background:#2a2a2e; border-radius:24px; font-size:18px; }"
        )
        identity.addWidget(self._avatar)
        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        self._title = section_title(self._t("player.export.title", "玩家摘要"))
        name_col.addWidget(self._title)
        self._uuid_label = muted_label("")
        name_col.addWidget(self._uuid_label)
        identity.addLayout(name_col, 1)
        layout.addLayout(identity)
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
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)
        self._equipment = QtEquipmentPreview(
            self._item_service,
            self._texture_service,
            slot_size=40,
            translate=self._translate,
        )
        layout.addWidget(self._equipment)
        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self._inv_tab_btn = btn_ghost(
            self._t("player.tab.inventory", "主背包"),
            on_click=lambda: self._switch_container_tab(0),
        )
        self._ender_tab_btn = btn_ghost(
            self._t("player.tab.ender", "末影箱"),
            on_click=lambda: self._switch_container_tab(1),
        )
        tabs.addWidget(self._inv_tab_btn)
        tabs.addWidget(self._ender_tab_btn)
        tabs.addStretch(1)
        layout.addLayout(tabs)
        self._inventory = QtInventoryGrid(
            self._item_service,
            self._texture_service,
            layout="main",
            slot_size=40,
            translate=self._translate,
            on_slot_click=self._on_inventory_slot_click,
        )
        layout.addWidget(self._inventory)
        self._ender = QtInventoryGrid(
            self._item_service,
            self._texture_service,
            layout="ender",
            slot_size=40,
            translate=self._translate,
            on_slot_click=self._on_inventory_slot_click,
        )
        layout.addWidget(self._ender)
        self._container_preview = QtInventoryGrid(
            self._item_service,
            self._texture_service,
            layout="shulker",
            slot_size=36,
            translate=self._translate,
            title=self._t("player.container.preview_title", "容器内容"),
        )
        self._container_preview.hide()
        layout.addWidget(self._container_preview)
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._switch_container_tab(0)
        return host

    def show_empty(self) -> None:
        """恢复未选择玩家的空状态。"""
        self._player_data = None
        self._summary = None
        self._title.setText(self._t("player.export.title", "玩家摘要"))
        self._uuid_label.clear()
        self.set_avatar_path(None)
        self.show_message(self._t(
            "player.summary_placeholder", "选择玩家后显示摘要"
        ))
        self._clear_fields()
        self._attributes.clear()
        self._effects.clear()
        self._clear_containers()
        self._set_enabled(False)

    def show_message(self, message: str) -> None:
        """在 HUD 区域显示纯文本提示。"""
        self._hud.setText(message)

    def show_loading(self, uuid: str) -> None:
        """显示选中玩家详情加载状态。"""
        self._player_data = None
        self._summary = None
        self._uuid_label.setText(uuid)
        self.set_avatar_path(None, initial=(uuid or "?")[:1])
        self._hud.setText(self._t(
            "player.loading_summary", "正在加载玩家摘要..."
        ))
        self._clear_fields()
        self._attributes.clear()
        self._effects.clear()
        self._clear_containers()
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
        self.set_avatar_path(
            None,
            initial=(summary.ref.name or summary.ref.uuid_norm or "?")[:1],
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
        inv = () if containers is None else containers.inventory
        equipment = () if containers is None else containers.equipment
        ender = () if containers is None else containers.ender_items
        selected = None if containers is None else containers.selected_slot
        # 装备栏同时接受装备槽与背包中的装备条目，兼容旧投影。
        equip_source = list(equipment) + list(inv)
        self._equipment.set_equipment(equip_source)
        self._inventory.set_inventory(list(inv), selected_slot=selected)
        self._ender.set_inventory(list(ender))
        self._container_preview.clear()
        self._container_preview.hide()

    def _clear_containers(self) -> None:
        self._equipment.clear()
        self._inventory.clear()
        self._ender.clear()
        self._container_preview.clear()
        self._container_preview.hide()

    def _switch_container_tab(self, index: int) -> None:
        self._container_tab = index
        show_inv = index == 0
        self._inventory.setVisible(show_inv)
        self._ender.setVisible(not show_inv)
        for position, button in enumerate(
            (self._inv_tab_btn, self._ender_tab_btn)
        ):
            button.setProperty(
                "role",
                "primary" if position == index else "ghost",
            )
            button.style().unpolish(button)
            button.style().polish(button)

    def _on_inventory_slot_click(
        self,
        slot: int,
        item: Optional[dict[str, Any]],
    ) -> None:
        del slot
        if not item:
            return
        nested = self._player_service.open_nested_container(item)
        if nested is None:
            return
        item_id = str(item.get("id", "") or "")
        title = (
            f"{self._t('player.container.preview_title', '容器内容')}: "
            f"{item_id or self._t('player.inventory.shulker', '潜影盒内容')}"
        )
        self._container_preview.set_title(title)
        self._container_preview.set_inventory(nested)
        self._container_preview.show()

    def set_avatar_path(
        self,
        path: str | None,
        *,
        initial: str = "?",
    ) -> None:
        """更新详情区圆形头像；无路径时显示首字母占位。"""
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    48,
                    48,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._avatar.setPixmap(scaled)
                self._avatar.setText("")
                return
        self._avatar.setPixmap(QPixmap())
        letter = (initial or "?")[:1].upper()
        self._avatar.setText(letter or "?")

    def dispose(self) -> None:
        """释放格子贴图回调。"""
        self._equipment.dispose()
        self._inventory.dispose()
        self._ender.dispose()
        self._container_preview.dispose()

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
