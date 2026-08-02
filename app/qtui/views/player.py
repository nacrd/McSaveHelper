"""Qt Explorer 玩家列表与编辑面板。"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.presenters.player_list_state import (
    PlayerListViewState,
    build_player_list_state,
)
from app.qtui.components.cards import muted_label, section_title
from app.qtui.views.player_editor import QtPlayerEditor
from app.qtui.views.player_tasks import PlayerDetailResult
from app.services.player.models import PlayerRef


Translate = Callable[..., str]
PlayerSelected = Callable[[str], None]
Command = Callable[[], None]


class QtPlayerPanel(QWidget):
    """提供玩家筛选、分页、选择与详情编辑。"""

    _PAGE_SIZE = 40

    def __init__(
        self,
        translate: Translate,
        on_player_selected: PlayerSelected,
        on_refresh: Command,
        on_stage: Command,
        on_teleport: Command,
        on_export: Command,
    ) -> None:
        """构建玩家面板。

        Args:
            translate: UI 翻译回调。
            on_player_selected: 玩家 UUID 选择回调。
            on_refresh: 刷新表单命令。
            on_stage: 暂存表单修改命令。
            on_teleport: 暂存传送到死亡点命令。
            on_export: 导出玩家摘要命令。
        """
        super().__init__()
        self._translate = translate
        self._on_player_selected = on_player_selected
        self._refs: tuple[PlayerRef, ...] = ()
        self._page_index = 0
        self._current_uuid: Optional[str] = None
        self._list_state = build_player_list_state(())
        self._editor = QtPlayerEditor(
            translate,
            on_refresh,
            on_stage,
            on_teleport,
            on_export,
        )
        self._build()
        self.show_empty()

    @property
    def current_uuid(self) -> Optional[str]:
        """返回当前选中玩家的规范化 UUID。"""
        return self._current_uuid

    @property
    def list_state(self) -> PlayerListViewState:
        """返回当前筛选与分页投影，供测试和状态检查。"""
        return self._list_state

    @property
    def editor(self) -> QtPlayerEditor:
        """返回右侧玩家编辑器。"""
        return self._editor

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._translate(key, default, **kwargs)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_player_list())
        splitter.addWidget(self._editor)
        splitter.setSizes([300, 780])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    def _build_player_list(self) -> QWidget:
        host = QWidget()
        host.setMinimumWidth(220)
        host.setMaximumWidth(380)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(8)
        layout.addWidget(section_title(self._t(
            "explorer.select_player", "选择玩家"
        )))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(self._t(
            "player.filter", "搜索玩家"
        ))
        self._filter.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._filter)
        self._list = QListWidget()
        self._list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, 1)
        pager = QHBoxLayout()
        self._previous = QPushButton(self._t("player.page_prev", "上一页"))
        self._previous.clicked.connect(self._previous_page)
        pager.addWidget(self._previous)
        self._page_status = muted_label("")
        self._page_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pager.addWidget(self._page_status, 1)
        self._next = QPushButton(self._t("player.page_next", "下一页"))
        self._next.clicked.connect(self._next_page)
        pager.addWidget(self._next)
        layout.addLayout(pager)
        return host

    def show_loading(self) -> None:
        """清除旧世界并显示玩家列表加载状态。"""
        self._refs = ()
        self._page_index = 0
        self._current_uuid = None
        self._list.clear()
        self._filter.setEnabled(False)
        self._page_status.setText(self._t(
            "player.loading_list", "正在加载玩家列表..."
        ))
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        self._editor.show_empty()

    def show_players(self, refs: Sequence[PlayerRef]) -> None:
        """投影玩家列表并在有数据时选择首项。"""
        self._refs = tuple(refs)
        self._page_index = 0
        self._filter.setEnabled(True)
        self._apply_list()
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._current_uuid = None
            self._editor.show_empty()
            self._editor.show_message(self._t(
                "player.no_players", "当前存档没有玩家数据"
            ))

    def show_empty(self) -> None:
        """恢复未加载世界的空状态。"""
        self._refs = ()
        self._page_index = 0
        self._current_uuid = None
        self._list.clear()
        self._filter.clear()
        self._filter.setEnabled(False)
        self._page_status.setText(self._t(
            "player.no_world", "加载存档后可查看玩家"
        ))
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        self._editor.show_empty()

    def show_list_error(self) -> None:
        """显示玩家列表读取失败状态。"""
        self._refs = ()
        self._list.clear()
        self._filter.setEnabled(True)
        self._page_status.setText(self._t(
            "player.list_load_error", "玩家列表加载失败"
        ))
        self._previous.setEnabled(False)
        self._next.setEnabled(False)

    def show_detail_loading(self, uuid: str) -> None:
        """显示选中玩家详情加载状态。"""
        self._editor.show_loading(uuid)

    def show_detail(self, detail: PlayerDetailResult) -> None:
        """投影玩家详情到编辑器。"""
        self._editor.show_detail(detail)

    def show_detail_unavailable(self, uuid: str) -> None:
        """显示玩家详情不可用状态。"""
        self._editor.show_unavailable(uuid)

    def _on_filter_changed(self, _query: str) -> None:
        self._page_index = 0
        self._apply_list()

    def _apply_list(self) -> None:
        state = build_player_list_state(
            self._refs,
            query=self._filter.text(),
            page_index=self._page_index,
            page_size=self._PAGE_SIZE,
        )
        self._list_state = state
        self._page_index = state.page_index
        refs_by_uuid = {ref.uuid_norm: ref for ref in self._refs}
        self._list.blockSignals(True)
        self._list.clear()
        for player in state.items:
            ref = refs_by_uuid.get(player.uuid)
            if ref is None:
                continue
            name = ref.name or self._t(
                "explorer.unknown_player", "未知玩家"
            )
            item = QListWidgetItem(
                f"{name}\n{ref.uuid_hyphen or ref.uuid_norm}"
            )
            item.setData(Qt.ItemDataRole.UserRole, ref.uuid_norm)
            item.setSizeHint(QSize(0, 44))
            item.setToolTip(ref.uuid_hyphen or ref.uuid_norm)
            self._list.addItem(item)
            if ref.uuid_norm == self._current_uuid:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)
        self._page_status.setText(self._t(
            "player.page_status",
            "第 {page}/{pages} 页 · {total} 人",
            page=state.page_index + 1,
            pages=state.page_count,
            total=state.total_count,
        ))
        self._previous.setEnabled(state.page_index > 0)
        self._next.setEnabled(state.page_index < state.page_count - 1)

    def _on_item_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        uuid = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(uuid, str) or uuid == self._current_uuid:
            return
        self._current_uuid = uuid
        self._on_player_selected(uuid)

    def _previous_page(self) -> None:
        self._page_index = max(0, self._page_index - 1)
        self._apply_list()

    def _next_page(self) -> None:
        self._page_index += 1
        self._apply_list()


__all__ = ["QtPlayerPanel"]
