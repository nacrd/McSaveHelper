"""Qt 迁移页面的表单区块构建器。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.models.config import MigrationConfig
from app.qtui.components.buttons import btn_ghost, btn_primary
from app.qtui.components.cards import card, muted_label, section_title
from app.qtui.views.migrator_options import mode_description


@dataclass(frozen=True)
class DirectoryControls:
    """源存档、目标目录与输出名称控件。"""

    card: QFrame
    source: QLineEdit
    destination: QLineEdit
    world_name: QLineEdit


@dataclass(frozen=True)
class VersionControls:
    """目标平台、版本和兼容选项控件。"""

    card: QFrame
    platform: QComboBox
    version: QComboBox
    strip_components: QCheckBox
    replace_unknown: QCheckBox
    warning: QLabel


@dataclass(frozen=True)
class PlayerControls:
    """玩家映射和 UUID 查询控件。"""

    card: QFrame
    manual_names: QLineEdit
    query_name: QLineEdit
    query_button: QPushButton
    query_result: QLabel


@dataclass(frozen=True)
class ModeControls:
    """快速/完整模式控件。"""

    card: QFrame
    group: QButtonGroup
    fast: QRadioButton
    full: QRadioButton
    description: QLabel


@dataclass(frozen=True)
class OptionControls:
    """迁移行为开关。"""

    card: QFrame
    offline: QCheckBox
    clean: QCheckBox
    pure_clean: QCheckBox


@dataclass(frozen=True)
class BatchControls:
    """批量迁移开关、路径和扫描状态控件。"""

    card: QFrame
    enabled: QCheckBox
    details: QWidget
    directory: QLineEdit
    browse_button: QPushButton
    scan_button: QPushButton
    result: QLabel


def _body() -> tuple[QWidget, QVBoxLayout]:
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return body, layout


def _path_row(field: QLineEdit, button: QPushButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(field, 1)
    layout.addWidget(button)
    return row


def build_directory_section(
    config: MigrationConfig,
    on_change: Callable[[], None],
    on_browse: Callable[[], None],
) -> DirectoryControls:
    """构建迁移路径区块。"""
    body, layout = _body()
    layout.addWidget(section_title("存档配置"))
    layout.addWidget(muted_label("设置要转换的源存档和输出位置"))
    source = QLineEdit(config.src_path)
    source.setPlaceholderText("请通过侧边栏设置当前存档")
    source.setReadOnly(True)
    destination = QLineEdit(config.dest_path)
    destination.setPlaceholderText("选择输出目录")
    browse = btn_ghost("浏览", width=86, on_click=on_browse)
    world_name = QLineEdit(config.world_name or "world")
    world_name.setPlaceholderText("世界文件夹名，例如 world")
    layout.addWidget(source)
    layout.addWidget(_path_row(destination, browse))
    layout.addWidget(world_name)
    destination.textChanged.connect(lambda _text: on_change())
    world_name.textChanged.connect(lambda _text: on_change())
    return DirectoryControls(
        card(body, padding=16), source, destination, world_name
    )


def build_version_section(
    config: MigrationConfig,
    on_change: Callable[[], None],
) -> VersionControls:
    """构建目标版本区块。"""
    body, layout = _body()
    layout.addWidget(section_title("版本转换"))
    layout.addWidget(muted_label("选择目标平台和目标数据版本"))
    selects = QWidget()
    selects_layout = QHBoxLayout(selects)
    selects_layout.setContentsMargins(0, 0, 0, 0)
    platform = QComboBox()
    platform.addItem("Java 版", "java")
    version = QComboBox()
    version.setEditable(True)
    version.addItem("保持源版本", "")
    if config.target_version:
        version.setEditText(config.target_version)
    selects_layout.addWidget(platform)
    selects_layout.addWidget(version, 1)
    layout.addWidget(selects)
    strip_components = QCheckBox("剥离 1.20.5+ 数据组件")
    strip_components.setChecked(True)
    replace_unknown = QCheckBox("将未知方块替换为 air")
    replace_unknown.setChecked(True)
    warning = QLabel("")
    warning.setProperty("role", "warning")
    warning.setWordWrap(True)
    warning.setVisible(False)
    layout.addWidget(strip_components)
    layout.addWidget(replace_unknown)
    layout.addWidget(warning)
    platform.currentIndexChanged.connect(lambda _index: on_change())
    version.currentTextChanged.connect(lambda _text: on_change())
    return VersionControls(
        card(body, padding=16),
        platform,
        version,
        strip_components,
        replace_unknown,
        warning,
    )


def build_player_section(
    config: MigrationConfig,
    on_change: Callable[[], None],
    on_query: Callable[[], None],
) -> PlayerControls:
    """构建玩家迁移与 UUID 查询区块。"""
    body, layout = _body()
    layout.addWidget(section_title("玩家配置"))
    manual_names = QLineEdit(config.manual_names)
    manual_names.setPlaceholderText("手动指定玩家，多个名称用英文逗号分隔")
    layout.addWidget(manual_names)
    layout.addWidget(muted_label("UUID 查询"))
    query_name = QLineEdit()
    query_name.setPlaceholderText("输入玩家名")
    query_button = btn_primary("查询", width=86, on_click=on_query)
    layout.addWidget(_path_row(query_name, query_button))
    query_result = QLabel("在此显示查询结果")
    query_result.setProperty("role", "result")
    query_result.setWordWrap(True)
    query_result.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
    )
    layout.addWidget(query_result)
    manual_names.textChanged.connect(lambda _text: on_change())
    query_name.returnPressed.connect(on_query)
    return PlayerControls(
        card(body, padding=16),
        manual_names,
        query_name,
        query_button,
        query_result,
    )


def build_mode_section(
    config: MigrationConfig,
    on_change: Callable[[str], None],
) -> ModeControls:
    """构建迁移模式区块。"""
    body, layout = _body()
    layout.addWidget(section_title("转换模式"))
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    fast = QRadioButton("快速模式")
    full = QRadioButton("完整模式")
    group = QButtonGroup(row)
    group.addButton(fast)
    group.addButton(full)
    (fast if config.mode != "full" else full).setChecked(True)
    row_layout.addWidget(fast)
    row_layout.addWidget(full)
    row_layout.addStretch(1)
    description = muted_label(mode_description(config.mode or "fast"))
    layout.addWidget(row)
    layout.addWidget(description)

    def on_mode_toggled(checked: bool, mode: str) -> None:
        if checked:
            on_change(mode)

    fast.toggled.connect(lambda checked: on_mode_toggled(checked, "fast"))
    full.toggled.connect(lambda checked: on_mode_toggled(checked, "full"))
    return ModeControls(
        card(body, padding=16), group, fast, full, description
    )


def build_options_section(
    config: MigrationConfig,
    on_change: Callable[[], None],
) -> OptionControls:
    """构建迁移选项区块。"""
    body, layout = _body()
    layout.addWidget(section_title("迁移选项"))
    offline = QCheckBox("离线 UUID 模式")
    offline.setChecked(config.offline_mode)
    clean = QCheckBox("迁移后清理临时文件")
    clean.setChecked(config.clean_mode)
    pure_clean = QCheckBox("纯净清理模式")
    pure_clean.setChecked(config.pure_clean_mode)
    for checkbox in (offline, clean, pure_clean):
        checkbox.toggled.connect(lambda _checked: on_change())
        layout.addWidget(checkbox)
    return OptionControls(card(body, padding=16), offline, clean, pure_clean)


def build_batch_section(
    config: MigrationConfig,
    on_change: Callable[[], None],
    on_toggle: Callable[[bool], None],
    on_browse: Callable[[], None],
    on_scan: Callable[[], None],
) -> BatchControls:
    """构建批量迁移区块。"""
    body, layout = _body()
    layout.addWidget(section_title("批量处理"))
    enabled = QCheckBox("启用批量模式（一次处理多个存档）")
    enabled.setChecked(config.batch_mode)
    layout.addWidget(enabled)
    details, details_layout = _body()
    directory = QLineEdit(config.batch_dir_path)
    directory.setPlaceholderText("包含多个世界存档的目录")
    browse = btn_ghost("浏览", width=80, on_click=on_browse)
    scan = btn_primary("扫描", width=80, on_click=on_scan)
    path_row = QWidget()
    path_layout = QHBoxLayout(path_row)
    path_layout.setContentsMargins(0, 0, 0, 0)
    path_layout.addWidget(directory, 1)
    path_layout.addWidget(browse)
    path_layout.addWidget(scan)
    result = muted_label("")
    result.setWordWrap(True)
    details_layout.addWidget(path_row)
    details_layout.addWidget(result)
    details.setVisible(config.batch_mode)
    layout.addWidget(details)
    enabled.toggled.connect(on_toggle)
    directory.textChanged.connect(lambda _text: on_change())
    return BatchControls(
        card(body, padding=16),
        enabled,
        details,
        directory,
        browse,
        scan,
        result,
    )
