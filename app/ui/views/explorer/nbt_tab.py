"""NBT tab mixin for ExplorerView - 三栏布局版本"""
from typing import Any, List, Optional

import flet as ft

from app.models.nbt_edit import (
    ChunkNbtTarget,
    NbtEditFormat,
    NbtPathPart,
    NbtTarget,
)
from app.ui.views.explorer.nbt import (
    NbtDataLoader,
    NbtStageManager,
    ChunkOperations,
    NbtCommitHandler,
)
from app.ui.views.explorer.mixin_context import ExplorerMixinHost
from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.nbt_tab_chrome import (
    NbtTabCallbacks,
    build_nbt_tab_chrome,
)
from core.omni.world_session import WorldSession


class NbtTabMixin(ExplorerMixinHost):
    """NBT 页签主协调器 - 三栏布局：左侧导航 + 中央查看器 + 右侧暂存区"""

    def _build_nbt_tab(self) -> None:
        """构建 NBT 页签 UI - 三栏布局"""
        self._nbt_left_collapsed = False
        self._nbt_right_collapsed = False
        chrome = self._create_nbt_chrome()
        self._bind_nbt_chrome(chrome)
        self._wire_nbt_coordinators()
        self._stage_manager.update_stage_status()
        self._chunk_ops.render_chunk_object_rows([])

    def _create_nbt_chrome(self) -> Any:
        """Build static chrome controls for the NBT tab."""
        return build_nbt_tab_chrome(
            current_label=self._current_nbt_label,
            callbacks=NbtTabCallbacks(
                load_target=self._load_selected_nbt_target,
                load_player=self._load_current_player_nbt,
                load_level=self._load_level_nbt,
                load_chunk=self._load_chunk_nbt,
                fill_world_coords=self._fill_chunk_from_world_coords_nbt,
                load_world_coords=self._load_chunk_from_world_coords_nbt,
                query_block=self._query_block_at_current_coords,
                replace_block=self._replace_block_at_current_coords,
                filter_chunk_objects=self._on_chunk_object_filter,
                search=self._on_nbt_search,
                expand_all=self._expand_all_nbt,
                collapse_all=self._collapse_all_nbt,
                export_json=self._export_nbt_json,
                stage_change=self._stage_nbt_change,
                commit=self._commit_nbt_changes,
                discard=self._discard_nbt_changes,
            ),
        )

    def _bind_nbt_chrome(self, chrome: Any) -> None:
        """Attach chrome controls to mixin state."""
        self._nbt_root = chrome.root
        self._nbt_left_panel = chrome.left_panel
        self._nbt_center_panel = chrome.center_panel
        self._nbt_right_panel = chrome.right_panel
        self._nbt_target_dropdown = chrome.target_dropdown
        self._region_file_field = chrome.region_file_field
        self._chunk_x_field = chrome.chunk_x_field
        self._chunk_z_field = chrome.chunk_z_field
        self._world_x_field = chrome.world_x_field
        self._world_z_field = chrome.world_z_field
        self._block_y_field = chrome.block_y_field
        self._block_query_result = chrome.block_query_result
        self._block_replace_name_field = chrome.block_replace_name_field
        self._chunk_objects_list = chrome.chunk_objects_list
        self._nbt_target_label = chrome.target_label
        self._nbt_tree = chrome.nbt_tree
        self._nbt_stage_status = chrome.stage_status
        self._nbt_stage_list = chrome.stage_list
        self._tab_nbt.content = chrome.root
        self._set_nbt_compact_layout(
            bool(getattr(self, "_compact_mode", False))
        )

    def _set_nbt_compact_layout(self, compact: bool) -> None:
        """Stack NBT panels in narrow windows and keep each panel scrollable."""
        root = getattr(self, "_nbt_root", None)
        if root is None:
            return
        left = self._nbt_left_panel
        center = self._nbt_center_panel
        right = self._nbt_right_panel
        if compact:
            for panel, height in ((left, 420), (center, 420), (right, 300)):
                panel.width = None
                panel.height = height
                panel.expand = False
            root.content = ft.Column(
                [left, center, right],
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
            root.padding = 6
        else:
            left.width = 280
            left.height = None
            left.expand = False
            center.width = None
            center.height = None
            center.expand = True
            right.width = 300
            right.height = None
            right.expand = False
            root.content = ft.Row(
                [left, center, right],
                spacing=8,
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
            root.padding = 10
        safe_update(root)

    def _wire_nbt_coordinators(self) -> None:
        """Create stage/chunk/data/commit coordinators after chrome exists."""
        self._stage_manager = self._create_nbt_stage_manager()
        self._chunk_ops = self._create_nbt_chunk_ops()
        self._data_loader = self._create_nbt_data_loader()
        self._commit_handler = self._create_nbt_commit_handler()

    def _create_nbt_stage_manager(self) -> NbtStageManager:
        return NbtStageManager(
            store=self._nbt_stage_store,
            status_control=self._nbt_stage_status,
            list_control=self._nbt_stage_list,
            get_current_target=lambda: self._current_nbt_target,
            get_current_label=lambda: self._current_nbt_label,
            get_current_format=lambda: self._current_edit_format,
            reload_current_target=self._reload_current_nbt_target,
            warn=self.app.warn_dialog,
            info=self.app.info_dialog,
            handle_error=lambda ex, title: self.app.handle_exception(
                ex, title=title
            ),
            log=self.app.log,
        )

    def _create_nbt_chunk_ops(self) -> ChunkOperations:
        from core.mca.block_data_service import BlockDataService

        return ChunkOperations(
            objects_list=self._chunk_objects_list,
            nbt_tree=self._nbt_tree,
            target_label=self._nbt_target_label,
            world_x_field=self._world_x_field,
            world_z_field=self._world_z_field,
            block_y_field=self._block_y_field,
            block_result=self._block_query_result,
            block_name_field=self._block_replace_name_field,
            get_chunk_target=lambda: self._current_chunk_target,
            set_view_state=self._set_nbt_view_state,
            stage_change=self._stage_manager.stage_change,
            warn=self.app.warn_dialog,
            info=self.app.info_dialog,
            handle_error=lambda ex, title: self.app.handle_exception(
                ex, title=title
            ),
            block_service=BlockDataService(),
        )

    def _create_nbt_data_loader(self) -> NbtDataLoader:
        return NbtDataLoader(
            get_world_session=lambda: self.world_session,
            get_current_uuid=lambda: self.current_uuid,
            get_current_target=lambda: self._current_nbt_target,
            get_current_label=lambda: self._current_nbt_label,
            get_dimension=lambda: self._current_dimension,
            set_target_state=self._set_nbt_target_state,
            load_player_data=self._load_player_data,
            render_chunk_objects=self._chunk_ops.render_chunk_objects,
            query_current_block=lambda: (
                self._chunk_ops.query_block_at_current_coords(silent=True)
            ),
            target_dropdown=self._nbt_target_dropdown,
            target_label=self._nbt_target_label,
            region_file_field=self._region_file_field,
            chunk_x_field=self._chunk_x_field,
            chunk_z_field=self._chunk_z_field,
            world_x_field=self._world_x_field,
            world_z_field=self._world_z_field,
            nbt_tree=self._nbt_tree,
            warn=self.app.warn_dialog,
            info=self.app.info_dialog,
            handle_error=lambda ex, title: self.app.handle_exception(
                ex, title=title
            ),
            save_file=self.app.save_file,
        )

    def _create_nbt_commit_handler(self) -> NbtCommitHandler:
        return NbtCommitHandler(
            store=self._nbt_stage_store,
            get_world_session=lambda: self.world_session,
            replace_world_session=self._replace_world_session,
            get_page=lambda: self.app.page,
            refresh_stage=self._stage_manager.update_stage_status,
            reload_current_target=self._data_loader.reload_current_nbt_target,
            warn=self.app.warn_dialog,
            info=self.app.info_dialog,
            error=self.app.error_dialog,
            handle_error=lambda ex, title: self.app.handle_exception(
                ex, title=title
            ),
            log=self.app.log,
        )

    def _replace_world_session(self, session: WorldSession) -> None:
        self.world_session = session

    def _set_nbt_view_state(
        self,
        label: str,
        edit_format: NbtEditFormat,
    ) -> None:
        self._current_nbt_label = label
        self._current_edit_format = edit_format

    def _set_nbt_target_state(
        self,
        target: Optional[NbtTarget],
        label: str,
        edit_format: NbtEditFormat,
        chunk_target: Optional[ChunkNbtTarget],
    ) -> None:
        self._current_nbt_target = target
        self._current_nbt_label = label
        self._current_edit_format = edit_format
        self._current_chunk_target = chunk_target

    # ========== 折叠功能（预留） ==========

    def _toggle_left_panel(self, e: Any = None) -> None:
        """切换左侧面板显示/隐藏"""
        self._nbt_left_collapsed = not self._nbt_left_collapsed
        self._nbt_left_panel.visible = not self._nbt_left_collapsed
        self._nbt_left_panel.update()

    def _toggle_right_panel(self, e: Any = None) -> None:
        """切换右侧面板显示/隐藏"""
        self._nbt_right_collapsed = not self._nbt_right_collapsed
        self._nbt_right_panel.visible = not self._nbt_right_collapsed
        self._nbt_right_panel.update()

    # ========== 以下是委托方法（与之前相同） ==========

    def _expand_all_nbt(self, e: Any = None) -> None:
        try:
            self._nbt_tree.expand_all(show_all_children=True)
        except Exception as ex:
            self.app.handle_exception(ex, title="展开全部 NBT 失败")

    def _collapse_all_nbt(self, e: Any = None) -> None:
        try:
            self._nbt_tree.collapse_all()
        except Exception as ex:
            self.app.handle_exception(ex, title="折叠全部 NBT 失败")

    def _on_nbt_search(self, e: Any) -> None:
        try:
            self._nbt_tree.search(e.control.value or "")
        except Exception as ex:
            self.app.handle_exception(ex, title="搜索 NBT 失败")

    def _update_nbt_target_options(self) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.update_nbt_target_options()

    def _reload_current_nbt_target(self) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.reload_current_nbt_target()

    def _load_current_player_nbt(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_current_player_nbt(e)

    def _load_level_nbt(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_level_nbt(e)

    def _load_selected_nbt_target(self, e: Any) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_selected_nbt_target(e)

    def _load_chunk_nbt(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_chunk_nbt(e)

    def _fill_chunk_from_world_coords(self, e: Any = None) -> None:
        self._fill_chunk_from_world_coords_nbt(e)

    def _fill_chunk_from_world_coords_nbt(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.fill_chunk_from_world_coords(e)

    def _load_chunk_from_world_coords(self, e: Any = None) -> None:
        self._load_chunk_from_world_coords_nbt(e)

    def _load_chunk_from_world_coords_nbt(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_chunk_from_world_coords(e)

    def _export_nbt_json(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.export_nbt_json(e)

    def _stage_nbt_change(self,
                          path_parts: List[NbtPathPart],
                          old_value: Any,
                          new_value: Any,
                          display_path: str) -> None:
        if hasattr(self, '_stage_manager'):
            self._stage_manager.stage_change(
                path_parts, old_value, new_value, display_path)

    def _update_nbt_stage_status(self) -> None:
        if hasattr(self, '_stage_manager'):
            self._stage_manager.update_stage_status()

    def _unstage_nbt_change(self, index: int) -> None:
        if hasattr(self, '_stage_manager'):
            self._stage_manager.unstage_change(index)

    def _discard_nbt_changes(self, e: Any = None) -> None:
        if hasattr(self, '_stage_manager'):
            self._stage_manager.discard_all_changes(e)

    def _render_chunk_objects(self, chunk_data: Any) -> None:
        if hasattr(self, '_chunk_ops'):
            self._chunk_ops.render_chunk_objects(chunk_data)

    def _on_chunk_object_filter(self, e: Any) -> None:
        if hasattr(self, '_chunk_ops'):
            self._chunk_ops.on_chunk_object_filter(e)

    def _query_block_at_current_coords(
            self, e: Any = None, silent: bool = False) -> None:
        if hasattr(self, '_chunk_ops'):
            self._chunk_ops.query_block_at_current_coords(e, silent)

    def _replace_block_at_current_coords(self, e: Any = None) -> None:
        if hasattr(self, '_chunk_ops'):
            self._chunk_ops.replace_block_at_current_coords(e)

    def _commit_nbt_changes(self, e: Any = None) -> None:
        if hasattr(self, '_commit_handler'):
            self._commit_handler.commit_changes(e)
