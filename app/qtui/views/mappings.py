"""映射管理视图（Qt 版，对应 Flet 树同名视图）。

UUID 映射 + 物品映射；领域逻辑复用 asset_import、item_service、
uuid_service 与 uuid_query_presenter。
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Optional, Protocol, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.presenters.mappings_view_state import (
    MappingsViewState,
    dispose_mappings_state,
    set_item_busy,
)
from app.presenters.uuid_query_presenter import (
    format_name_history_query,
    normalize_query_uuid,
)
from app.qtui.components.buttons import btn_ghost, btn_primary, btn_success
from app.qtui.components.cards import card, muted_label, section_title
from app.qtui.components.fields import text_field
from app.qtui.components.layout import page_header
from app.qtui.components.uuid_table import (
    QtUuidMappingTable,
    read_mappings_file,
    write_mappings_file,
)
from app.qtui.context import (
    QtDialogPort,
    QtFileDialogPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.theme import get_theme_manager
from app.qtui.utils import run_on_ui
from app.qtui.view_actions import QtViewAction
from app.qtui.views.mappings_operations import (
    DebouncedLatestSave,
    LatestOperationGroup,
)
from app.services.asset_import import (
    AssetImportCounts,
    configured_minecraft_dir,
    current_save_start_path,
    import_assets_from_sources,
    pick_asset_sources,
    preferred_mc_locale,
)
from app.services.execution_runtime import CancellationToken
from core.uuid_utils import NameHistoryEntry

if TYPE_CHECKING:
    from app.services.config_service import ConfigService
    from app.services.item_service import ItemService
    from app.services.texture_service import TextureService
    from app.services.uuid_service import UUIDService

ResultT = TypeVar("ResultT")


class MappingsHost(
    QtTranslationPort,
    QtDialogPort,
    QtFileDialogPort,
    QtRuntimePort,
    Protocol,
):
    """映射页面所需的配置、服务和 UI 端口。"""

    @property
    def config(self) -> ConfigService:
        """返回应用映射配置。"""
        ...

    @property
    def item(self) -> ItemService:
        """返回物品元数据服务。"""
        ...

    @property
    def texture(self) -> TextureService:
        """返回纹理服务。"""
        ...

    @property
    def uuid(self) -> UUIDService:
        """返回 UUID 查询服务。"""
        ...


class MappingsView(QScrollArea):
    """映射管理视图 — UUID 映射 + 物品映射。"""

    _UUID_SAVE_DEBOUNCE_SECONDS = 0.15

    def __init__(self, app: MappingsHost) -> None:
        """初始化映射管理视图。

        Args:
            app: 映射页面所需的配置、服务和 UI 端口。
        """
        super().__init__()
        self.app = app
        self._item_service = app.item
        self._operations = LatestOperationGroup(
            app.execution_runtime,
            "mappings_view",
            lambda callback: run_on_ui(callback),
        )
        self._item_mutation_lock = Lock()
        self._state = MappingsViewState()
        self._uuid_saver = DebouncedLatestSave(
            self._operations,
            lambda: self.app.config.save(),
        )

        self.setWidgetResizable(True)
        self._build()

    def get_top_actions(self) -> list[QtViewAction]:
        """返回顶栏可消费的视图命令。"""
        return [
            QtViewAction(
                self._t("top_bar.import_lang", "导入语言文件"),
                self._import_assets,
            )
        ]

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self.app.translate(key, default, **kwargs)

    def _build(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(page_header(
            self._t("mappings.title", "映射管理"),
            "管理 UUID 映射和物品映射，用于存档转换和存档浏览器。",
            icon="🔗",
        ))

        self._build_uuid_query_section(layout)
        self._build_uuid_section(layout)
        self._build_item_section(layout)

        layout.addStretch(1)
        self.setWidget(content)

    # ─── UUID 查询 ───────────────────────────────

    def _build_uuid_query_section(self, layout: QVBoxLayout) -> None:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        body_layout.addWidget(section_title(
            self._t("mappings.uuid_query_title", "UUID 查询")
        ))
        body_layout.addWidget(muted_label(
            self._t(
                "mappings.uuid_query_description",
                "输入玩家 UUID，通过 Mojang 官方 API 查询当前名称与曾用名。",
            )
        ))

        query_row = QWidget()
        query_layout = QHBoxLayout(query_row)
        query_layout.setContentsMargins(0, 0, 0, 0)
        query_layout.setSpacing(10)
        self._uuid_query_field = text_field(
            hint_text=self._t(
                "mappings.uuid_query_hint",
                "32 位十六进制，可带连字符",
            ),
        )
        query_button = btn_primary(
            self._t("mappings.uuid_query_button", "查询"),
            width=90,
            on_click=self._on_uuid_query,
        )
        query_layout.addWidget(self._uuid_query_field, 1)
        query_layout.addWidget(query_button)
        body_layout.addWidget(query_row)

        self._uuid_query_result = QLabel(
            self._t("mappings.uuid_query_placeholder", "在此显示查询结果")
        )
        self._uuid_query_result.setProperty("role", "muted")
        self._uuid_query_result.setWordWrap(True)
        self._uuid_query_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        result_box = QWidget()
        result_layout = QVBoxLayout(result_box)
        result_layout.setContentsMargins(12, 12, 12, 12)
        result_layout.addWidget(self._uuid_query_result)
        theme = get_theme_manager().current
        result_box.setStyleSheet(
            f"background-color: {theme.log_bg};"
            f"border: 2px solid {theme.border_standard};"
            f"border-radius: 6px;"
        )
        body_layout.addWidget(result_box)

        layout.addWidget(card(body, padding=16))

    def _on_uuid_query(self) -> None:
        """在后台查询 UUID 的当前名与曾用名，只投递最新一次结果。"""
        if self._state.is_disposed:
            return
        raw = self._uuid_query_field.text().strip()
        if not raw:
            return
        normalized = normalize_query_uuid(raw)
        if normalized is None:
            self._uuid_query_result.setText(self._t(
                "mappings.uuid_query_invalid",
                "UUID 格式无效，请输入 32 位十六进制字符（可带连字符）",
            ))
            return
        self._uuid_query_result.setText(
            self._t("mappings.uuid_query_loading", "正在查询...")
        )
        failure_title = self._t("mappings.error.uuid_query", "UUID 查询失败")
        self._operations.submit(
            "uuid_name_query",
            lambda token: self._run_io(
                token,
                lambda: self.app.uuid.query_name_history(
                    normalized,
                    self.app.log,
                ),
            ),
            lambda history: self._apply_uuid_query_success(raw, history),
            lambda error: self._apply_uuid_query_error(error, failure_title),
        )

    def _apply_uuid_query_success(
        self,
        raw_uuid: str,
        history: Optional[list[NameHistoryEntry]],
    ) -> None:
        """在 UI 线程投影姓名历史查询结果。"""
        self._uuid_query_result.setText(format_name_history_query(raw_uuid, history))
        self._uuid_query_result.setStyleSheet("")

    def _apply_uuid_query_error(self, error: Exception, title: str) -> None:
        """显示查询失败提示并交由应用异常处理。"""
        self._uuid_query_result.setText(
            self._t("mappings.uuid_query_error", "UUID 查询失败，请稍后重试")
        )
        self.app.handle_exception(error, title=title)

    # ─── UUID 映射 ───────────────────────────────

    def _build_uuid_section(self, layout: QVBoxLayout) -> None:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        body_layout.addWidget(section_title(
            self._t("mappings.uuid_title", "UUID 映射")
        ))
        body_layout.addWidget(muted_label(
            self._t(
                "mappings.uuid_description",
                "管理玩家名与 UUID 的映射，用于离线模式下的玩家数据转换。",
            )
        ))

        self._table = QtUuidMappingTable(
            mappings=self.app.config.custom_uuid_mappings,
            on_mappings_change=self._queue_uuid_mappings,
            on_import_click=self._on_uuid_import,
            on_export_click=self._on_uuid_export,
        )
        body_layout.addWidget(self._table)
        body_layout.addWidget(muted_label(
            "提示：您可以通过\"导入名单\"批量导入映射，或手动添加每一行。"
            "映射数据会实时保存到配置文件。"
        ))
        layout.addWidget(card(body, padding=16))

    def _queue_uuid_mappings(self, mappings: dict[str, str]) -> None:
        """立即更新内存，并合并连续输入为一次后台配置保存。"""
        if self._state.is_disposed:
            return
        self.app.config.custom_uuid_mappings = dict(mappings)
        failure_title = self._t("mappings.error.uuid_save", "保存 UUID 映射失败")
        self._uuid_saver.schedule(
            self._UUID_SAVE_DEBOUNCE_SECONDS,
            lambda error: self.app.handle_exception(error, title=failure_title),
        )

    def _on_uuid_import(self) -> Optional[str]:
        if self._state.is_disposed:
            return None
        path = self.app.pick_file(
            title="导入映射文件",
            file_types=[
                ("文本文件 (*.txt)", "*.txt"),
                ("CSV 文件 (*.csv)", "*.csv"),
                ("所有文件 (*.*)", "*.*"),
            ],
        )
        if not path:
            return None
        source_path = Path(path)
        failure_title = self._t("mappings.error.uuid_import", "导入 UUID 映射失败")
        self._operations.submit(
            "uuid_import",
            lambda token: self._run_io(
                token,
                lambda: read_mappings_file(source_path),
            ),
            self._table.merge_mappings,
            lambda error: self.app.handle_exception(error, title=failure_title),
        )
        return None

    def _on_uuid_export(self, mappings: dict[str, str]) -> Optional[str]:
        if not mappings or self._state.is_disposed:
            return None
        path = self.app.save_file(
            title="导出映射文件",
            default_ext=".txt",
            file_types=[
                ("文本文件 (*.txt)", "*.txt"),
                ("所有文件 (*.*)", "*.*"),
            ],
        )
        if not path:
            return None
        output_path = Path(path)
        snapshot = dict(mappings)
        failure_title = self._t("mappings.error.uuid_export", "导出 UUID 映射失败")
        self._operations.submit(
            "uuid_export",
            lambda token: self._run_io(
                token,
                lambda: write_mappings_file(
                    output_path,
                    snapshot,
                ),
            ),
            None,
            lambda error: self.app.handle_exception(error, title=failure_title),
        )
        return None

    def refresh_mappings(self) -> None:
        """从应用配置重新加载 UUID 映射表并刷新表格。"""
        if self._state.is_disposed:
            return
        self._table.set_mappings(self.app.config.custom_uuid_mappings)

    # ─── 物品映射 ───────────────────────────────

    def _build_item_section(self, layout: QVBoxLayout) -> None:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        body_layout.addWidget(section_title("物品 ID 映射"))
        body_layout.addWidget(muted_label(
            "管理物品 ID 与显示名称的映射。支持导入语言文件或自定义 JSON 映射。"
        ))

        # 导入 / 导出
        import_row = QWidget()
        import_layout = QHBoxLayout(import_row)
        import_layout.setContentsMargins(0, 0, 0, 0)
        import_layout.setSpacing(8)
        import_layout.addWidget(
            btn_primary("导入 JSON", width=110, on_click=self._import_json)
        )
        import_layout.addWidget(
            btn_ghost("导出 JSON", width=110, on_click=self._export_json)
        )
        import_layout.addWidget(
            btn_ghost(
                self._t("mappings.import_assets", "导入语言/贴图"),
                width=150,
                on_click=self._import_assets,
            )
        )
        import_layout.addStretch(1)
        body_layout.addWidget(import_row)
        body_layout.addWidget(muted_label(
            self._t(
                "mappings.assets_hint",
                "可多选语言 JSON 与客户端/模组 JAR；JAR 会同时导入 lang 与 textures。",
            )
        ))

        # 手动添加
        add_row = QWidget()
        add_layout = QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(10)
        self._item_id_field = text_field(hint_text="modid:item_name", width=260)
        self._item_name_field = text_field(
            hint_text="显示在物品栏中的名称",
            width=200,
        )
        add_layout.addWidget(self._item_id_field)
        add_layout.addWidget(self._item_name_field)
        add_layout.addWidget(
            btn_success("添加", width=80, on_click=self._add_item_mapping)
        )
        self._item_mapping_status = QLabel("")
        self._item_mapping_status.setProperty("role", "muted")
        add_layout.addWidget(self._item_mapping_status)
        add_layout.addStretch(1)
        body_layout.addWidget(add_row)

        # 搜索 + 表格
        self._item_search_field = text_field(
            hint_text="搜索物品 ID 或名称",
            on_changed=lambda _text: self._on_item_search(),
        )
        body_layout.addWidget(self._item_search_field)
        self._item_table = QTableWidget(0, 3)
        self._item_table.setHorizontalHeaderLabels(["物品 ID", "显示名称", "操作"])
        self._item_table.verticalHeader().setVisible(False)
        self._item_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._item_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._item_table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        body_layout.addWidget(self._item_table)

        layout.addWidget(card(body, padding=16))
        self._render_item_table("")

    def _on_item_search(self) -> None:
        if not self._state.can_edit_items:
            return
        self._render_item_table(self._item_search_field.text())

    def _render_item_table(self, filter_text: str) -> None:
        mappings = self._item_service.get_custom_item_mappings()
        self._item_table.setRowCount(0)
        filter_lower = filter_text.lower()
        theme = get_theme_manager().current
        inserted = 0
        for item_id, display_name in sorted(mappings.items()):
            if (
                filter_lower
                and filter_lower not in item_id.lower()
                and filter_lower not in display_name.lower()
            ):
                continue
            self._item_table.insertRow(inserted)
            id_item = QTableWidgetItem(item_id)
            id_item.setForeground(QColor(theme.text_secondary))
            name_item = QTableWidgetItem(display_name)
            name_item.setForeground(QColor(theme.text_primary))
            self._item_table.setItem(inserted, 0, id_item)
            self._item_table.setItem(inserted, 1, name_item)
            delete_button = QPushButton("🗑️")
            delete_button.setFixedWidth(34)
            delete_button.setToolTip("删除")
            delete_button.clicked.connect(
                lambda _checked, iid=item_id: self._delete_item_mapping(iid)
            )
            self._item_table.setCellWidget(inserted, 2, delete_button)
            inserted += 1
        if self._item_table.rowCount() == 0:
            placeholder_text = (
                "暂无自定义物品映射 — 可通过导入语言文件、导入 JSON 或手动添加映射"
                if not mappings
                else "没有匹配的映射 — 尝试更换物品 ID 或显示名称关键词"
            )
            self._item_table.insertRow(0)
            hint_item = QTableWidgetItem(placeholder_text)
            hint_item.setForeground(QColor(theme.text_muted))
            self._item_table.setItem(0, 0, hint_item)
            self._item_table.setSpan(0, 0, 1, 3)

    def _add_item_mapping(self) -> None:
        if not self._state.can_edit_items:
            return
        item_id = self._item_id_field.text().strip()
        display_name = self._item_name_field.text().strip()
        if not item_id or not display_name:
            self._set_item_status("物品 ID 和显示名称不能为空。", "warning")
            return
        self._item_service.set_item_mapping(item_id, display_name)
        self._item_id_field.clear()
        self._item_name_field.clear()
        self._set_item_status(f"已添加: {item_id}", "success")
        self._render_item_table(self._item_search_field.text())

    def _delete_item_mapping(self, item_id: str) -> None:
        if not self._state.can_edit_items:
            return
        removed = self._item_service.delete_item_mapping(item_id)
        self._set_item_status(
            f"已删除: {item_id}" if removed else f"未找到自定义映射: {item_id}",
            "success" if removed else "warning",
        )
        self._render_item_table(self._item_search_field.text())

    def _set_item_status(self, message: str, kind: str) -> None:
        theme = get_theme_manager().current
        color = theme.success if kind == "success" else theme.warning
        self._item_mapping_status.setText(message)
        self._item_mapping_status.setStyleSheet(f"color: {color};")

    # ─── 资源导入 ───────────────────────────────

    def _import_assets(self) -> None:
        """选择资源来源并在共享 I/O 通道导入语言与贴图。"""
        if not self._state.can_edit_items:
            return
        failure_title = self._t("mappings.error.import_assets", "导入语言/贴图失败")
        try:
            title = self._t(
                "mappings.import_assets_title",
                "选择语言 JSON / Minecraft 或模组 JAR（可多选）",
            )
            paths = tuple(pick_asset_sources(self.app, title))
            locale = preferred_mc_locale(self.app)
            configured_dir = configured_minecraft_dir(self.app)
            start_path = current_save_start_path(self.app)
        except Exception as error:
            self.app.handle_exception(error, title=failure_title)
            return

        self._state = set_item_busy(self._state, True)
        self._operations.submit(
            "item_import",
            lambda token: self._run_item_operation(
                token,
                lambda: import_assets_from_sources(
                    item_service=self._item_service,
                    texture_service=self.app.texture,
                    paths=paths,
                    locale=locale,
                    configured_dir=configured_dir,
                    start_path=start_path,
                    empty_paths_fallback=True,
                ),
            ),
            lambda counts: self._apply_asset_import_success(counts, locale),
            lambda error: self._apply_item_io_error(error, failure_title),
        )

    def _apply_asset_import_success(
        self,
        counts: AssetImportCounts,
        locale: str,
    ) -> None:
        """在 UI 线程投影资源导入结果。"""
        self._state = set_item_busy(self._state, False)
        self._set_asset_import_status(
            counts.lang_count,
            counts.texture_count,
            counts.jar_count,
            locale,
        )
        self._render_item_table(self._item_search_field.text())

    def _set_asset_import_status(
        self,
        lang_count: int,
        texture_count: int,
        jar_count: int,
        locale: str,
    ) -> None:
        if lang_count <= 0 and texture_count <= 0:
            self._set_item_status(
                self._t(
                    "mappings.import_assets_empty",
                    "未导入语言或贴图。可多选 JSON/JAR，或取消选择以尝试本机客户端。",
                ),
                "warning",
            )
            return
        parts: list[str] = []
        if lang_count > 0:
            parts.append(f"语言 {lang_count}")
        if texture_count > 0:
            parts.append(f"贴图 {texture_count}（{max(1, jar_count)} jar）")
        self._set_item_status(
            f"导入完成：{'；'.join(parts)}（优先 {locale}）。",
            "success",
        )

    # ─── JSON 导入 / 导出 ────────────────────────

    def _import_json(self) -> None:
        if not self._state.can_edit_items:
            return
        failure_title = self._t("mappings.error.import_json", "导入 JSON 映射失败")
        try:
            path = self.app.pick_file(
                title="选择 JSON 映射文件",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
        except Exception as error:
            self.app.handle_exception(error, title=failure_title)
            return
        if not path:
            return

        source_path = Path(path)
        self._state = set_item_busy(self._state, True)
        self._operations.submit(
            "item_import",
            lambda token: self._run_item_operation(
                token,
                lambda: self._item_service.load_custom_mapping_file(source_path),
            ),
            self._apply_item_json_import_success,
            lambda error: self._apply_item_io_error(error, failure_title),
        )

    def _apply_item_json_import_success(self, count: int) -> None:
        """在 UI 线程刷新 JSON 导入结果。"""
        self._state = set_item_busy(self._state, False)
        self._set_item_status(f"已导入 {count} 个映射。", "success")
        self._render_item_table(self._item_search_field.text())

    def _export_json(self) -> None:
        if not self._state.can_edit_items:
            return
        failure_title = self._t("mappings.error.export_json", "导出映射失败")
        try:
            path = self.app.save_file(
                title="导出物品映射",
                default_ext=".json",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
        except Exception as error:
            self.app.handle_exception(error, title=failure_title)
            return
        if not path:
            return

        output_path = Path(path)
        self._state = set_item_busy(self._state, True)
        self._operations.submit(
            "item_export",
            lambda token: self._run_item_operation(
                token,
                lambda: self._item_service.save_custom_mapping_file(output_path),
            ),
            lambda _result: self._apply_item_json_export_success(output_path),
            lambda error: self._apply_item_io_error(error, failure_title),
        )

    def _apply_item_json_export_success(self, output_path: Path) -> None:
        """在 UI 线程完成 JSON 导出反馈。"""
        self._state = set_item_busy(self._state, False)
        self.app.info_dialog("成功", f"映射已导出到 {output_path}")

    def _apply_item_io_error(self, error: Exception, title: str) -> None:
        """恢复物品控件并显示后台 I/O 错误。"""
        self._state = set_item_busy(self._state, False)
        self.app.handle_exception(error, title=title)

    def _run_item_operation(
        self,
        token: CancellationToken,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        """串行访问共享可变物品服务，并在边界协作取消。"""
        token.raise_if_cancelled()
        with self._item_mutation_lock:
            token.raise_if_cancelled()
            result = operation()
            token.raise_if_cancelled()
            return result

    @staticmethod
    def _run_io(token: CancellationToken, operation: Callable[[], ResultT]) -> ResultT:
        """在磁盘操作前后执行协作取消检查。"""
        token.raise_if_cancelled()
        result = operation()
        token.raise_if_cancelled()
        return result

    # ─── 生命周期 ───────────────────────────────

    def dispose(self) -> None:
        """取消后台操作并使已经排队的 UI 回调失效；可重复调用。"""
        if self._state.is_disposed:
            return
        self._state = dispose_mappings_state(self._state)
        self._operations.close()
        self._uuid_saver.flush()
