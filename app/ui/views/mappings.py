"""Mappings View —— 映射管理（UUID 映射 + 物品映射）。"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Dict, Optional, Protocol, TypeVar

import flet as ft

from app.services.asset_import import (
    AssetImportCounts,
    configured_minecraft_dir,
    current_save_start_path,
    import_assets_from_sources,
    pick_asset_sources,
    preferred_mc_locale,
)
from app.services.execution_runtime import (
    CancellationToken,
)
from app.presenters.mappings_view_state import (
    MappingsViewState,
    dispose_mappings_state,
    set_item_busy,
)
from app.ui.components.buttons import btn_ghost, btn_primary, btn_success
from app.ui.components.cards import card, placeholder, section_title
from app.ui.components.fields import text_field
from app.ui.components.layout import page_header
from app.ui.components.uuid_table import UUIDMappingTable
from app.ui.feature_context import (
    FeatureDialogPort,
    FeatureFileDialogPort,
    FeaturePagePort,
    FeatureRuntimePort,
    FeatureTranslationPort,
)
from app.ui.icons import IconSet
from app.ui.theme import THEME
from app.ui.utils import run_on_ui, safe_update
from app.ui.view_actions import ViewAction
from app.ui.views.mappings_operations import (
    _DebouncedLatestSave,
    _LatestOperationGroup,
)

if TYPE_CHECKING:
    from app.services.config_service import ConfigService
    from app.services.item_service import ItemService
    from app.services.texture_service import TextureService


class MappingsHost(
    FeaturePagePort,
    FeatureTranslationPort,
    FeatureDialogPort,
    FeatureFileDialogPort,
    FeatureRuntimePort,
    Protocol,
):
    """Ports required by the mappings view."""

    @property
    def config(self) -> ConfigService:
        """Return application mapping configuration."""
        ...

    @property
    def item(self) -> ItemService:
        """Return the item metadata service."""
        ...

    @property
    def texture(self) -> TextureService:
        """Return the texture service."""
        ...


ResultT = TypeVar("ResultT")


class MappingsView(ft.Column):
    """映射管理视图 — UUID映射 + 物品映射"""

    _UUID_SAVE_DEBOUNCE_SECONDS = 0.15

    def __init__(self, app: "MappingsHost") -> None:
        """初始化映射管理视图。

        Args:
            app: 映射页面所需的配置、服务和 UI 端口。
        """
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._item_service = app.item
        self._operations = _LatestOperationGroup(
            app.execution_runtime,
            "mappings_view",
            lambda callback: run_on_ui(
                getattr(self.app, "page", None),
                callback,
            ),
        )
        self._item_mutation_lock = Lock()
        self._state = MappingsViewState()
        self._uuid_saver = _DebouncedLatestSave(
            self._operations,
            lambda: self.app.config.save(),
        )
        self._build()

    @property
    def _t(self):
        return self.app.translate

    def get_top_actions(self) -> list[ViewAction]:
        """返回应用壳层顶栏可消费的视图命令。

        Returns:
            list[ViewAction]: 导入语言文件等动作。
        """
        return [
            ViewAction(
                self._t("top_bar.import_lang", "导入语言文件"),
                self._import_lang,
            )
        ]

    def _build(self) -> None:
        self.controls.clear()

        self._page_header = page_header(
            self._t("mappings.title", "映射管理"),
            ft.Text(
                "管理 UUID 映射和物品映射，用于存档转换和存档浏览器。",
                size=12,
                color=THEME.text_muted,
            ),
            icon=IconSet.LINK,
        )
        self.controls.append(self._page_header)

        self._build_uuid_section()
        self._build_item_section()

    def _build_uuid_section(self) -> None:
        s = ft.Column(spacing=0)
        s.controls.append(section_title(
            self._t("mappings.uuid_title", "UUID 映射")))

        s.controls.append(ft.Container(
            content=ft.Text(
                self._t("mappings.uuid_description",
                        "管理玩家名与 UUID 的映射，用于离线模式下的玩家数据转换。"),
                size=12, color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=10, top=10),
        ))

        self._table: UUIDMappingTable = UUIDMappingTable(
            mappings=self.app.config.custom_uuid_mappings,
            on_mappings_change=self._queue_uuid_mappings,
            on_import_click=self._on_uuid_import,
            on_export_click=self._on_uuid_export,
        )
        s.controls.append(ft.Container(
            content=self._table,
            padding=ft.Padding(left=20, right=20, bottom=12),
        ))

        s.controls.append(ft.Container(
            content=ft.Text(
                "提示：您可以通过\"导入名单\"批量导入映射，或手动添加每一行。映射数据会实时保存到配置文件。",
                size=11, color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=20),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self.controls.append(
            ft.Container(
                content=c,
                padding=ft.Padding(
                    bottom=16)))

    def _build_item_section(self) -> None:
        s = ft.Column(spacing=0)
        s.controls.append(section_title("物品 ID 映射"))
        s.controls.append(ft.Container(
            content=ft.Text(
                "管理物品 ID 与显示名称的映射。支持导入语言文件或自定义 JSON 映射。",
                size=12, color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, top=10, bottom=10),
        ))
        s.controls.extend(self._item_import_controls())
        s.controls.extend(self._item_add_controls())
        s.controls.extend(self._item_search_controls())
        self._render_item_table("")
        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self.controls.append(
            ft.Container(
                content=c,
                padding=ft.Padding(bottom=16),
            )
        )

    def _item_import_controls(self) -> list[ft.Control]:
        import_row = ft.Row(
            [
                btn_primary(
                    "导入 JSON",
                    width=110,
                    on_click=self._import_json,
                ),
                btn_ghost(
                    "导出 JSON",
                    width=110,
                    on_click=self._export_json,
                ),
                btn_ghost(
                    self._t("mappings.import_assets", "导入语言/贴图"),
                    width=150,
                    on_click=self._import_assets,
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        return [
            ft.Container(
                content=import_row,
                padding=ft.Padding(left=20, right=20, bottom=12),
            ),
            ft.Container(
                content=ft.Text(
                    self._t(
                        "mappings.assets_hint",
                        "可多选语言 JSON 与客户端/模组 JAR；JAR 会同时导入 lang 与 textures。",
                    ),
                    size=11,
                    color=THEME.text_muted,
                ),
                padding=ft.Padding(left=20, right=20, bottom=8),
            ),
        ]

    def _item_add_controls(self) -> list[ft.Control]:
        self._item_id_field = text_field(
            label="物品 ID",
            hint_text="modid:item_name",
            expand=False,
            width=260,
        )
        self._item_name_field = text_field(
            label="显示名称",
            hint_text="显示在物品栏中的名称",
            expand=False,
            width=200,
        )
        self._item_mapping_status = ft.Text(
            "", size=11, color=THEME.text_muted
        )
        add_row = ft.Row([
            self._item_id_field,
            self._item_name_field,
            btn_success("添加", width=80, on_click=self._add_item_mapping),
            self._item_mapping_status,
        ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
        )
        return [
            ft.Container(
                content=add_row,
                padding=ft.Padding(left=20, right=20, bottom=12),
            )
        ]

    def _item_search_controls(self) -> list[ft.Control]:
        self._item_search_field = text_field(
            label="搜索物品 ID 或名称",
            on_change=lambda _: self._on_item_search(),
        )
        self._item_table_container = ft.Container()
        return [
            ft.Container(
                content=ft.Column([
                    self._item_search_field,
                    self._item_table_container,
                ], spacing=8),
                padding=ft.Padding(left=20, right=20, bottom=20),
            )
        ]

    def _render_item_table(self, filter_text: str) -> None:
        mappings = self._item_service.get_custom_item_mappings()
        if not mappings:
            self._item_table_container.content = placeholder(
                icon=IconSet.PACKAGE,
                title="暂无自定义物品映射",
                subtitle="可通过导入语言文件、导入 JSON 或手动添加映射",
                height=120,
            )
            return

        rows = self._build_item_mapping_rows(mappings, filter_text)
        if not rows:
            self._item_table_container.content = placeholder(
                icon=IconSet.SEARCH,
                title="没有匹配的映射",
                subtitle="尝试更换物品 ID 或显示名称关键词",
                height=110,
            )
            return

        self._item_table_container.content = self._build_item_mapping_table(rows)

    def _build_item_mapping_rows(
        self,
        mappings: dict[str, str],
        filter_text: str,
    ) -> list[ft.DataRow]:
        """Filter custom mappings into table rows."""
        rows: list[ft.DataRow] = []
        filter_lower = filter_text.lower()
        for item_id, display_name in sorted(mappings.items()):
            if (
                filter_lower
                and filter_lower not in item_id.lower()
                and filter_lower not in display_name.lower()
            ):
                continue
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.Text(
                                item_id,
                                size=12,
                                color=THEME.text_secondary,
                                font_family="monospace",
                            )
                        ),
                        ft.DataCell(
                            ft.Text(
                                display_name,
                                size=12,
                                color=THEME.text_primary,
                            )
                        ),
                        ft.DataCell(
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color=THEME.mc_redstone,
                                icon_size=18,
                                tooltip="删除",
                                on_click=lambda e, iid=item_id: (
                                    self._delete_item_mapping(iid)
                                ),
                            )
                        ),
                    ]
                )
            )
        return rows

    def _build_item_mapping_table(self, rows: list[ft.DataRow]) -> ft.Container:
        """Wrap mapping rows in a fixed-height DataTable container."""
        return ft.Container(
            content=ft.DataTable(
                columns=[
                    ft.DataColumn(
                        label=ft.Text(
                            "物品 ID",
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.mc_gold,
                        )
                    ),
                    ft.DataColumn(
                        label=ft.Text(
                            "显示名称",
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.mc_gold,
                        )
                    ),
                    ft.DataColumn(
                        label=ft.Text(
                            "操作",
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.mc_gold,
                        )
                    ),
                ],
                rows=rows,
                heading_row_color=THEME.bg_secondary,
                data_row_color=THEME.bg_card,
                border=ft.Border(
                    left=ft.BorderSide(1, THEME.border_subtle),
                    top=ft.BorderSide(1, THEME.border_subtle),
                    right=ft.BorderSide(1, THEME.border_subtle),
                    bottom=ft.BorderSide(1, THEME.border_subtle),
                ),
                column_spacing=20,
            ),
            height=min(350, 40 + len(rows) * 42),
        )

    def _on_item_search(self) -> None:
        if not self._state.can_edit_items:
            return
        self._render_item_table(self._item_search_field.value or "")
        safe_update(self._item_table_container)

    def _add_item_mapping(self, e: ft.ControlEvent) -> None:
        del e
        if not self._state.can_edit_items:
            return
        item_id = (self._item_id_field.value or "").strip()
        display_name = (self._item_name_field.value or "").strip()
        if not item_id or not display_name:
            self._item_mapping_status.value = "物品 ID 和显示名称不能为空。"
            self._item_mapping_status.color = THEME.warning
            self._item_mapping_status.update()
            return
        self._item_service.set_item_mapping(item_id, display_name)
        self._item_id_field.value = ""
        self._item_name_field.value = ""
        self._item_mapping_status.value = f"已添加: {item_id}"
        self._item_mapping_status.color = THEME.mc_grass
        self._render_item_table(self._item_search_field.value or "")
        self.update()

    def _delete_item_mapping(self, item_id: str) -> None:
        if not self._state.can_edit_items:
            return
        removed = self._item_service.delete_item_mapping(item_id)
        self._item_mapping_status.value = (
            f"已删除: {item_id}"
            if removed
            else f"未找到自定义映射: {item_id}"
        )
        self._item_mapping_status.color = THEME.mc_grass if removed else THEME.warning
        self._render_item_table(self._item_search_field.value or "")
        safe_update(self._item_table_container)
        safe_update(self._item_mapping_status)

    def _import_lang(self, e: ft.ControlEvent) -> None:
        """Top-bar entry — same unified assets importer."""
        self._import_assets(e)

    def _import_assets(self, e: Optional[ft.ControlEvent] = None) -> None:
        """选择资源来源并在共享 I/O 通道导入语言与贴图。"""
        del e
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

        self._set_item_busy(True)
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
        self._set_item_busy(False)
        self._set_asset_import_status(
            counts.lang_count,
            counts.texture_count,
            counts.jar_count,
            locale,
        )
        self._render_item_table(self._item_search_field.value or "")
        safe_update(self)

    def _set_asset_import_status(
        self,
        lang_count: int,
        texture_count: int,
        jar_count: int,
        locale: str,
    ) -> None:
        if lang_count <= 0 and texture_count <= 0:
            self._item_mapping_status.value = self._t(
                "mappings.import_assets_empty",
                "未导入语言或贴图。可多选 JSON/JAR，或取消选择以尝试本机客户端。",
            )
            self._item_mapping_status.color = THEME.warning
            return
        parts = []
        if lang_count > 0:
            parts.append(f"语言 {lang_count}")
        if texture_count > 0:
            parts.append(f"贴图 {texture_count}（{max(1, jar_count)} jar）")
        self._item_mapping_status.value = (
            f"导入完成：{'；'.join(parts)}（优先 {locale}）。"
        )
        self._item_mapping_status.color = THEME.mc_grass

    def _import_from_local_minecraft(self, e: Optional[ft.ControlEvent] = None) -> None:
        """Back-compat: unified importer with empty selection falls back to local."""
        self._import_assets(e)

    def _import_from_jar_file(self, e: Optional[ft.ControlEvent] = None) -> None:
        """Back-compat alias for the unified assets importer."""
        self._import_assets(e)

    def _import_json(self, e: ft.ControlEvent) -> None:
        del e
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
        self._set_item_busy(True)
        self._operations.submit(
            "item_import",
            lambda token: self._run_item_operation(
                token,
                lambda: self._item_service.load_custom_mapping_file(
                    source_path
                ),
            ),
            self._apply_item_json_import_success,
            lambda error: self._apply_item_io_error(error, failure_title),
        )

    def _apply_item_json_import_success(self, count: int) -> None:
        """在 UI 线程刷新 JSON 导入结果。"""
        self._set_item_busy(False)
        self._item_mapping_status.value = f"已导入 {count} 个映射。"
        self._item_mapping_status.color = THEME.mc_grass
        self._render_item_table(self._item_search_field.value or "")
        safe_update(self)

    def _export_json(self, e: ft.ControlEvent) -> None:
        del e
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
        self._set_item_busy(True)
        self._operations.submit(
            "item_export",
            lambda token: self._run_item_operation(
                token,
                lambda: self._item_service.save_custom_mapping_file(
                    output_path
                ),
            ),
            lambda _: self._apply_item_json_export_success(output_path),
            lambda error: self._apply_item_io_error(error, failure_title),
        )

    def _apply_item_json_export_success(self, output_path: Path) -> None:
        """在 UI 线程完成 JSON 导出反馈。"""
        self._set_item_busy(False)
        self.app.info_dialog("成功", f"映射已导出到 {output_path}")

    def _apply_item_io_error(self, error: Exception, title: str) -> None:
        """恢复物品控件并显示后台 I/O 错误。"""
        self._set_item_busy(False)
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

    def _set_item_busy(self, busy: bool) -> None:
        """切换物品映射控件的后台操作状态。"""
        self._state = set_item_busy(self._state, busy)

    def refresh_mappings(self) -> None:
        """从应用配置重新加载 UUID 映射表并刷新表格。"""
        if self._state.is_disposed:
            return
        self._table.set_mappings(self.app.config.custom_uuid_mappings)

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
                lambda: UUIDMappingTable.read_mappings_file(source_path),
            ),
            self._table.merge_mappings,
            lambda error: self.app.handle_exception(error, title=failure_title),
        )
        return None

    def _on_uuid_export(self, mappings: Dict[str, str]) -> Optional[str]:
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
                lambda: UUIDMappingTable.write_mappings_file(
                    output_path,
                    snapshot,
                ),
            ),
            None,
            lambda error: self.app.handle_exception(error, title=failure_title),
        )
        return None

    @staticmethod
    def _run_io(token: CancellationToken, operation: Callable[[], ResultT]) -> ResultT:
        """在磁盘操作前后执行协作取消检查。"""
        token.raise_if_cancelled()
        result = operation()
        token.raise_if_cancelled()
        return result

    def _queue_uuid_mappings(self, mappings: Dict[str, str]) -> None:
        """立即更新内存，并合并连续输入为一次后台配置保存。"""
        if self._state.is_disposed:
            return
        self.app.config.custom_uuid_mappings = dict(mappings)
        failure_title = self._t("mappings.error.uuid_save", "保存 UUID 映射失败")
        self._uuid_saver.schedule(
            self._UUID_SAVE_DEBOUNCE_SECONDS,
            lambda error: self.app.handle_exception(error, title=failure_title),
        )

    def dispose(self) -> None:
        """取消后台操作并使已经排队的 UI 回调失效；可重复调用。"""
        if self._state.is_disposed:
            return
        self._state = dispose_mappings_state(self._state)
        self._operations.close()
        self._uuid_saver.flush()
