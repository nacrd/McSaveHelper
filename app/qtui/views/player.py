"""Qt Explorer 玩家列表与编辑面板。"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
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

from app.presenters.player_avatar_state import (
    AvatarRequestKind,
    PlayerAvatarState,
    avatar_generation,
    begin_avatar_requests,
    close_avatar_requests,
    invalidate_avatar_requests,
    owns_avatar_request,
)
from app.presenters.player_list_state import (
    PlayerListViewState,
    build_player_list_state,
)
from app.qtui.components.buttons import btn_ghost
from app.qtui.components.cards import muted_label, section_title
from app.qtui.utils import run_on_ui
from app.qtui.views.player_editor import QtPlayerEditor
from app.qtui.views.player_tasks import PlayerDetailResult
from app.services.item_service import ItemService
from app.services.player.models import PlayerRef
from app.services.player_avatar_service import PlayerAvatarService
from app.services.player_service import PlayerService
from app.services.texture_service import TextureService


Translate = Callable[..., str]
PlayerSelected = Callable[[str], None]
Command = Callable[[], None]

_LIST_AVATAR_SIZE = 32
_UUID_ROLE = int(Qt.ItemDataRole.UserRole)


class QtPlayerPanel(QWidget):
    """提供玩家筛选、分页、选择、头像与详情编辑。"""

    _PAGE_SIZE = 40

    def __init__(
        self,
        translate: Translate,
        on_player_selected: PlayerSelected,
        on_refresh: Command,
        on_stage: Command,
        on_teleport: Command,
        on_export: Command,
        *,
        on_import_usercache: Command | None = None,
        on_lookup_names: Command | None = None,
        item_service: ItemService | None = None,
        texture_service: TextureService | None = None,
        player_service: PlayerService | None = None,
        avatar_service: PlayerAvatarService | None = None,
    ) -> None:
        """构建玩家面板。"""
        super().__init__()
        self._translate = translate
        self._on_player_selected = on_player_selected
        self._on_import_usercache = on_import_usercache
        self._on_lookup_names = on_lookup_names
        self._avatar_service = avatar_service
        self._avatar_state = PlayerAvatarState()
        self._avatar_paths: dict[str, str] = {}
        self._name_lookup_pending = False
        self._name_lookup_attempted: set[str] = set()
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
            item_service=item_service,
            texture_service=texture_service,
            player_service=player_service,
        )
        self._build()
        self.show_empty()

    @property
    def current_uuid(self) -> Optional[str]:
        """返回当前选中玩家的规范化 UUID。"""
        return self._current_uuid

    @property
    def list_state(self) -> PlayerListViewState:
        """返回当前筛选与分页投影。"""
        return self._list_state

    @property
    def editor(self) -> QtPlayerEditor:
        """返回右侧玩家编辑器。"""
        return self._editor

    @property
    def player_refs(self) -> tuple[PlayerRef, ...]:
        """返回当前玩家引用快照。"""
        return self._refs

    @property
    def name_lookup_pending(self) -> bool:
        """是否正在在线查询名称。"""
        return self._name_lookup_pending

    def unknown_name_uuids(self, *, only_unattempted: bool = False) -> tuple[str, ...]:
        """返回尚无名称的玩家 UUID。"""
        result: list[str] = []
        for ref in self._refs:
            if ref.name:
                continue
            if only_unattempted and ref.uuid_norm in self._name_lookup_attempted:
                continue
            result.append(ref.uuid_norm)
        return tuple(result)

    def mark_name_lookup_attempted(self, uuids: Sequence[str]) -> None:
        """记录已尝试在线查询的 UUID，避免同世界重复自动查询。"""
        self._name_lookup_attempted.update(uuids)

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

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._import_usercache_btn = btn_ghost(
            self._t("explorer.import_usercache", "导入 usercache"),
            on_click=self._handle_import_usercache,
        )
        self._lookup_names_btn = btn_ghost(
            self._t("player.lookup_names", "在线查询名称"),
            on_click=self._handle_lookup_names,
        )
        actions.addWidget(self._import_usercache_btn)
        actions.addWidget(self._lookup_names_btn)
        layout.addLayout(actions)
        self._name_status = muted_label("")
        self._name_status.setWordWrap(True)
        layout.addWidget(self._name_status)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.setIconSize(QSize(_LIST_AVATAR_SIZE, _LIST_AVATAR_SIZE))
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, 1)
        pager = QHBoxLayout()
        self._previous = QPushButton(self._t("player.page_prev", "上一页"))
        self._previous.setProperty("role", "ghost")
        self._previous.setCursor(Qt.CursorShape.PointingHandCursor)
        self._previous.clicked.connect(self._previous_page)
        pager.addWidget(self._previous)
        self._page_status = muted_label("")
        self._page_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pager.addWidget(self._page_status, 1)
        self._next = QPushButton(self._t("player.page_next", "下一页"))
        self._next.setProperty("role", "ghost")
        self._next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next.clicked.connect(self._next_page)
        pager.addWidget(self._next)
        layout.addLayout(pager)
        return host

    def show_loading(self) -> None:
        """清除旧世界并显示玩家列表加载状态。"""
        self._invalidate_avatars()
        self._refs = ()
        self._page_index = 0
        self._current_uuid = None
        self._name_lookup_attempted.clear()
        self.set_name_lookup_busy(False)
        self.set_name_lookup_status("")
        self._list.clear()
        self._filter.setEnabled(False)
        self._import_usercache_btn.setEnabled(False)
        self._lookup_names_btn.setEnabled(False)
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
        self._import_usercache_btn.setEnabled(True)
        self._lookup_names_btn.setEnabled(not self._name_lookup_pending)
        self._apply_list()
        if self._list.count() > 0:
            if self._current_uuid is None:
                self._list.setCurrentRow(0)
            else:
                self._select_uuid_row(self._current_uuid)
        else:
            self._current_uuid = None
            self._editor.show_empty()
            self._editor.show_message(self._t(
                "player.no_players", "当前存档没有玩家数据"
            ))

    def show_empty(self) -> None:
        """恢复未加载世界的空状态。"""
        self._invalidate_avatars()
        self._refs = ()
        self._page_index = 0
        self._current_uuid = None
        self._name_lookup_attempted.clear()
        self.set_name_lookup_busy(False)
        self.set_name_lookup_status("")
        self._list.clear()
        self._filter.clear()
        self._filter.setEnabled(False)
        self._import_usercache_btn.setEnabled(False)
        self._lookup_names_btn.setEnabled(False)
        self._page_status.setText(self._t(
            "player.no_world", "加载存档后可查看玩家"
        ))
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        self._editor.show_empty()

    def dispose(self) -> None:
        """释放编辑器与头像回调。"""
        self._avatar_state = close_avatar_requests(self._avatar_state)
        self._avatar_paths.clear()
        if self._avatar_service is not None:
            self._avatar_service.close()
        self._editor.dispose()

    def show_list_error(self) -> None:
        """显示玩家列表读取失败状态。"""
        self._refs = ()
        self._list.clear()
        self._filter.setEnabled(True)
        self._import_usercache_btn.setEnabled(True)
        self._lookup_names_btn.setEnabled(not self._name_lookup_pending)
        self._page_status.setText(self._t(
            "player.list_load_error", "玩家列表加载失败"
        ))
        self._previous.setEnabled(False)
        self._next.setEnabled(False)

    def show_detail_loading(self, uuid: str) -> None:
        """显示选中玩家详情加载状态。"""
        self._editor.show_loading(uuid)

    def show_detail(self, detail: PlayerDetailResult) -> None:
        """投影玩家详情到编辑器，并异步加载头像。"""
        self._editor.show_detail(detail)
        if detail.summary is not None:
            self._load_detail_avatar(
                detail.summary.ref.uuid_norm,
                detail.summary.ref.name,
            )

    def show_detail_unavailable(self, uuid: str) -> None:
        """显示玩家详情不可用状态。"""
        self._editor.show_unavailable(uuid)

    def set_name_lookup_busy(self, pending: bool) -> None:
        """切换在线名称查询忙碌状态。"""
        self._name_lookup_pending = pending
        enabled = self._filter.isEnabled() and not pending
        self._lookup_names_btn.setEnabled(enabled)

    def set_name_lookup_status(self, text: str, *, is_error: bool = False) -> None:
        """更新名称查询状态行。"""
        del is_error
        self._name_status.setText(text)

    def apply_resolved_names(self, resolved: dict[str, str]) -> None:
        """用在线/usercache 解析结果刷新列表显示名。"""
        if not resolved:
            return
        updated: list[PlayerRef] = []
        for ref in self._refs:
            name = resolved.get(ref.uuid_norm)
            if name and name != ref.name:
                updated.append(PlayerRef(
                    uuid_norm=ref.uuid_norm,
                    uuid_hyphen=ref.uuid_hyphen,
                    name=name,
                    dat_path=ref.dat_path,
                ))
            else:
                updated.append(ref)
        self._refs = tuple(updated)
        self._apply_list()
        if self._current_uuid:
            self._select_uuid_row(self._current_uuid)

    def _handle_import_usercache(self) -> None:
        if self._on_import_usercache is not None:
            self._on_import_usercache()

    def _handle_lookup_names(self) -> None:
        if self._on_lookup_names is not None:
            self._on_lookup_names()

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
        self._avatar_state = begin_avatar_requests(
            self._avatar_state,
            AvatarRequestKind.LIST,
        )
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
            item.setData(_UUID_ROLE, ref.uuid_norm)
            item.setSizeHint(QSize(0, 48))
            item.setToolTip(ref.uuid_hyphen or ref.uuid_norm)
            cached = self._avatar_paths.get(ref.uuid_norm)
            if cached:
                item.setIcon(self._icon_from_path(cached))
            self._list.addItem(item)
            if ref.uuid_norm == self._current_uuid:
                self._list.setCurrentItem(item)
            self._load_list_avatar(ref)
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

    def _load_list_avatar(self, ref: PlayerRef) -> None:
        service = self._avatar_service
        if service is None:
            return
        generation = avatar_generation(
            self._avatar_state,
            AvatarRequestKind.LIST,
        )

        def on_loaded(path: Optional[str]) -> None:
            def apply() -> None:
                if not owns_avatar_request(
                    self._avatar_state,
                    AvatarRequestKind.LIST,
                    generation,
                ):
                    return
                if not path:
                    return
                self._avatar_paths[ref.uuid_norm] = path
                self._set_list_item_icon(ref.uuid_norm, path)

            run_on_ui(apply)

        service.load_avatar_async(ref.uuid_norm, on_loaded)

    def _load_detail_avatar(
        self,
        uuid_norm: str,
        name: Optional[str],
    ) -> None:
        service = self._avatar_service
        if service is None:
            self._editor.set_avatar_path(None, initial=(name or uuid_norm or "?")[:1])
            return
        self._avatar_state = begin_avatar_requests(
            self._avatar_state,
            AvatarRequestKind.DETAIL,
        )
        generation = avatar_generation(
            self._avatar_state,
            AvatarRequestKind.DETAIL,
        )
        initial = (name or uuid_norm or "?")[:1]
        cached = self._avatar_paths.get(uuid_norm)
        if cached:
            self._editor.set_avatar_path(cached, initial=initial)

        def on_loaded(path: Optional[str]) -> None:
            def apply() -> None:
                if not owns_avatar_request(
                    self._avatar_state,
                    AvatarRequestKind.DETAIL,
                    generation,
                ):
                    return
                if path:
                    self._avatar_paths[uuid_norm] = path
                    self._editor.set_avatar_path(path, initial=initial)
                    self._set_list_item_icon(uuid_norm, path)

            run_on_ui(apply)

        service.load_avatar_async(uuid_norm, on_loaded)

    def _set_list_item_icon(self, uuid_norm: str, path: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is None:
                continue
            if item.data(_UUID_ROLE) == uuid_norm:
                item.setIcon(self._icon_from_path(path))
                break

    @staticmethod
    def _icon_from_path(path: str) -> QIcon:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return QIcon()
        scaled = pixmap.scaled(
            _LIST_AVATAR_SIZE,
            _LIST_AVATAR_SIZE,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QIcon(scaled)

    def _select_uuid_row(self, uuid: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is not None and item.data(_UUID_ROLE) == uuid:
                self._list.blockSignals(True)
                self._list.setCurrentItem(item)
                self._list.blockSignals(False)
                return

    def _invalidate_avatars(self) -> None:
        self._avatar_state = invalidate_avatar_requests(self._avatar_state)
        self._avatar_paths.clear()

    def _on_item_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        uuid = current.data(_UUID_ROLE)
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
