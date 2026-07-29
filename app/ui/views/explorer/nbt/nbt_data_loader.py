"""NBT、JSON 与区块数据源的 UI 加载协调器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import flet as ft

from app.models.nbt_edit import (
    ChunkNbtTarget,
    NbtEditFormat,
    NbtTarget,
)
from app.services.execution_runtime import OperationScope
from app.ui.views.explorer.nbt.nbt_chunk_loader import (
    NbtChunkLoader,
    NbtChunkLoaderContext,
    NbtChunkLoaderUi,
    dimension_region_dir,
)
from app.ui.views.explorer.nbt.nbt_io_coordinator import NbtIoCoordinator
from app.ui.views.explorer.nbt.nbt_io_operations import (
    export_json_payload,
    find_nbt_target_candidates,
    load_world_json,
    load_world_nbt,
)
from app.ui.views.explorer.nbt_tree import NBTTreeView
from app.ui.views.explorer.utils import safe_update
from core.omni.world_session import WorldSession


DialogCallback = Callable[[str, str], None]
ErrorCallback = Callable[[Exception, str], None]
SaveFileCallback = Callable[..., Optional[str]]
TargetStateCallback = Callable[
    [Optional[NbtTarget], str, NbtEditFormat, Optional[ChunkNbtTarget]],
    None,
]


class NbtDataLoader:
    """加载 Explorer 可编辑的数据源，不持有 Explorer 宿主对象。

    通过注入的回调读写 WorldSession、目标状态与 UI 控件，保持加载逻辑
    可单测且与页面生命周期解耦。
    """

    def __init__(
        self,
        *,
        get_world_session: Callable[[], Optional[WorldSession]],
        get_current_uuid: Callable[[], Optional[str]],
        get_current_target: Callable[[], Optional[NbtTarget]],
        get_current_label: Callable[[], str],
        get_dimension: Callable[[], str],
        set_target_state: TargetStateCallback,
        load_player_data: Callable[[str], None],
        render_chunk_objects: Callable[[Any], None],
        query_current_block: Callable[[], None],
        target_dropdown: ft.Dropdown,
        target_label: ft.Text,
        region_file_field: ft.TextField,
        chunk_x_field: ft.TextField,
        chunk_z_field: ft.TextField,
        world_x_field: ft.TextField,
        world_z_field: ft.TextField,
        nbt_tree: NBTTreeView,
        warn: DialogCallback,
        info: DialogCallback,
        handle_error: ErrorCallback,
        save_file: SaveFileCallback,
        task_scope: Optional[OperationScope] = None,
        page: Optional[ft.Page] = None,
    ) -> None:
        """注入会话/UI 依赖（仅绑定引用，不执行 I/O）。

        Args:
            get_world_session: 当前 WorldSession 获取器。
            get_current_uuid: 当前选中玩家 UUID。
            get_current_target: 当前编辑目标。
            get_current_label: 当前目标展示标签。
            get_dimension: 当前维度 id。
            set_target_state: 回写目标状态到宿主。
            load_player_data: 加载玩家 NBT 的宿主方法。
            render_chunk_objects: 渲染区块内对象列表。
            query_current_block: 刷新当前方块查询。
            target_dropdown: 目标下拉控件。
            target_label: 目标标签文本。
            region_file_field: 区域文件路径输入。
            chunk_x_field: 区块 X 输入。
            chunk_z_field: 区块 Z 输入。
            world_x_field: 世界 X 输入。
            world_z_field: 世界 Z 输入。
            nbt_tree: NBT 树控件。
            warn: 警告对话框。
            info: 信息对话框。
            handle_error: 异常处理回调。
            save_file: 保存文件对话框。
        """
        self._get_world_session = get_world_session
        self._get_current_uuid = get_current_uuid
        self._get_current_target = get_current_target
        self._get_current_label = get_current_label
        self._set_target_state = set_target_state
        self._load_player_data = load_player_data
        self._target_dropdown = target_dropdown
        self._target_label = target_label
        self._nbt_tree = nbt_tree
        self._warn = warn
        self._info = info
        self._handle_error = handle_error
        self._save_file = save_file
        self._io = NbtIoCoordinator(
            task_scope=task_scope,
            page=page,
            get_world_session=get_world_session,
            handle_error=handle_error,
        )
        self._request_generation = 0
        self._target_options: Dict[str, Path] = {}
        self._chunk_loader = NbtChunkLoader(
            self._io,
            NbtChunkLoaderContext(
                get_world_session=get_world_session,
                get_dimension=get_dimension,
                next_generation=self._next_request_generation,
                is_current=self._is_current_request,
            ),
            NbtChunkLoaderUi(
                set_target_state=set_target_state,
                render_chunk_objects=render_chunk_objects,
                query_current_block=query_current_block,
                target_label=target_label,
                region_file_field=region_file_field,
                chunk_x_field=chunk_x_field,
                chunk_z_field=chunk_z_field,
                world_x_field=world_x_field,
                world_z_field=world_z_field,
                nbt_tree=nbt_tree,
                warn=warn,
                handle_error=handle_error,
            ),
        )

    def update_nbt_target_options(self) -> None:
        """扫描当前存档中可直接编辑的 NBT 与 JSON 文件。"""
        try:
            session = self._get_world_session()
            if not session:
                self._set_target_options([])
                return
            generation = self._next_request_generation()
            self._io.submit(
                "scan_nbt_targets",
                lambda token: find_nbt_target_candidates(
                    session.world_path,
                    token,
                ),
                lambda candidates: self._apply_target_options(
                    candidates,
                    session,
                    generation,
                ),
                "刷新 NBT 目标失败",
                session=session,
                request_guard=lambda: self._is_current_request(
                    generation,
                    session,
                ),
            )
        except Exception as ex:
            self._handle_error(ex, "刷新 NBT 目标失败")

    def _apply_target_options(
        self,
        candidates: List[Tuple[str, Path]],
        session: WorldSession,
        generation: int,
    ) -> None:
        if not self._is_current_request(generation, session):
            return
        self._set_target_options(candidates)

    def _set_target_options(self, candidates: List[Tuple[str, Path]]) -> None:
        self._target_options = {
            relative_path.as_posix(): relative_path
            for _, relative_path in candidates
        }
        self._target_dropdown.options = [
            ft.dropdown.Option(path.as_posix(), label) for label, path in candidates
        ]
        safe_update(self._target_dropdown)

    def load_current_player_nbt(self, e: Any = None) -> None:
        """加载当前选中玩家的 player.dat。

        Args:
            e: 可选 Flet 事件（按钮回调兼容）。
        """
        try:
            current_uuid = self._get_current_uuid()
            if not current_uuid:
                self._warn("提示", "请先选择玩家。")
                return
            self._load_player_data(current_uuid)
        except Exception as ex:
            self._handle_error(ex, "加载玩家 NBT 失败")

    def load_level_nbt(self, e: Any = None) -> None:
        """加载世界根 ``level.dat``。

        Args:
            e: 可选 Flet 事件。
        """
        try:
            if not self._get_world_session():
                self._warn("提示", "请先通过侧边栏设置当前存档。")
                return
            self.load_nbt_file(Path("level.dat"), "世界 NBT: level.dat")
        except Exception as ex:
            self._handle_error(ex, "加载 level.dat 失败")

    def load_selected_nbt_target(self, e: Any) -> None:
        """根据目标下拉选择加载 NBT/JSON 文件。

        Args:
            e: 下拉 ``on_select`` 事件，``e.control.value`` 为相对路径键。
        """
        try:
            key = e.control.value
            relative_path = self._target_options.get(key)
            if relative_path is None:
                return
            self.load_nbt_file(relative_path, f"NBT 文件: {key}")
        except Exception as ex:
            self._handle_error(ex, "加载 NBT 目标失败")

    def load_nbt_file(self, relative_path: Path, label: str) -> None:
        """加载存档内相对路径的 ``.dat`` 或转调 JSON 加载。

        Args:
            relative_path: 相对世界根的路径。
            label: UI 展示标签。
        """
        session = self._require_session()
        if session is None:
            return
        if relative_path.suffix.lower() != ".dat":
            self.load_json_file(relative_path, label)
            return
        generation = self._next_request_generation()
        self._io.submit(
            "load_nbt_file",
            lambda token: load_world_nbt(
                session.world_path,
                relative_path,
                token,
            ),
            lambda data: self._apply_nbt_payload(
                relative_path,
                label,
                data,
                session,
                generation,
            ),
            "加载 NBT 目标失败",
            session=session,
            request_guard=lambda: self._is_current_request(
                generation,
                session,
            ),
        )

    def load_json_file(self, relative_path: Path, label: str) -> None:
        """加载 stats/advancements 等 JSON 并以树形式展示。

        Args:
            relative_path: 相对世界根的路径。
            label: UI 展示标签。
        """
        session = self._require_session()
        if session is None:
            return
        json_label = label.replace("NBT 文件", "JSON 文件")
        generation = self._next_request_generation()
        self._io.submit(
            "load_json_file",
            lambda token: load_world_json(
                session.world_path,
                relative_path,
                token,
            ),
            lambda data: self._apply_nbt_payload(
                relative_path,
                json_label,
                data,
                session,
                generation,
                edit_format="json",
            ),
            "加载 JSON 目标失败",
            session=session,
            request_guard=lambda: self._is_current_request(
                generation,
                session,
            ),
        )

    def _apply_nbt_payload(
        self,
        relative_path: Path,
        label: str,
        data: Any,
        session: WorldSession,
        generation: int,
        *,
        edit_format: NbtEditFormat = "nbt",
    ) -> None:
        if not self._is_current_request(generation, session):
            return
        self._set_loaded_target(relative_path, label, edit_format)
        self._nbt_tree.load_nbt(data, editable=True)

    def load_chunk_nbt(self, e: Any = None) -> None:
        """从区域路径与区块坐标加载区块 NBT（校验路径不越界世界根）。

        Args:
            e: 可选 Flet 事件。
        """
        self._chunk_loader.load_chunk_nbt(e)

    def fill_chunk_from_world_coords(self, e: Any = None) -> None:
        """根据世界坐标填入区域路径与区块坐标字段。

        Args:
            e: 可选 Flet 事件。
        """
        self._chunk_loader.fill_chunk_from_world_coords(e)

    def load_chunk_from_world_coords(self, e: Any = None) -> None:
        """填入区块坐标后立即加载该区块 NBT。

        Args:
            e: 可选 Flet 事件。
        """
        self._chunk_loader.load_chunk_from_world_coords(e)

    def reload_current_nbt_target(self) -> None:
        """按当前目标类型重新从磁盘加载（Path/玩家/区块）。"""
        self._next_request_generation()
        target = self._get_current_target()
        if isinstance(target, Path):
            self.load_nbt_file(target, self._get_current_label())
        elif isinstance(target, str):
            self._load_player_data(target)
        elif isinstance(target, ChunkNbtTarget):
            self.load_chunk_nbt()

    def export_nbt_json(self, e: Any = None) -> None:
        """将树中当前数据导出为 JSON 文件。

        Args:
            e: 可选 Flet 事件。
        """
        try:
            data = self._nbt_tree.get_modified_data()
            if data is None:
                self._warn("提示", "没有可导出的 NBT 数据")
                return
            path = self._save_file(
                title="保存 JSON 文件",
                default_ext=".json",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if not path:
                return
            generation = self._next_request_generation()
            output_path = Path(path)
            self._io.submit(
                "export_nbt_json",
                lambda token: export_json_payload(
                    data,
                    output_path,
                    token,
                ),
                lambda _: self._apply_export_success(
                    output_path,
                    generation,
                ),
                "导出 JSON 失败",
                on_error=lambda error: self._apply_export_error(
                    error,
                    generation,
                ),
                request_guard=lambda: (
                    generation == self._request_generation
                ),
            )
        except Exception as ex:
            self._handle_error(ex, "导出 JSON 失败")

    def _apply_export_success(self, output_path: Path, generation: int) -> None:
        if generation != self._request_generation:
            return
        self._info("成功", f"已导出到: {output_path}")

    def _apply_export_error(self, error: Exception, generation: int) -> None:
        if generation != self._request_generation:
            return
        self._handle_error(error, "导出 JSON 失败")

    def _require_session(self) -> Optional[WorldSession]:
        session = self._get_world_session()
        if session is None:
            self._warn("提示", "请先通过侧边栏设置当前存档。")
        return session

    def _set_loaded_target(
        self,
        target: Path,
        label: str,
        edit_format: NbtEditFormat,
    ) -> None:
        self._set_target_state(target, label, edit_format, None)
        self._target_label.value = label
        self._target_dropdown.value = target.as_posix()
        safe_update(self._target_label)
        safe_update(self._target_dropdown)

    @staticmethod
    def _dimension_region_dir(dimension: str) -> str:
        return dimension_region_dir(dimension)

    def _next_request_generation(self) -> int:
        """递增数据请求代数，使旧回调在页面切换后失效。"""
        self._request_generation += 1
        return self._request_generation

    def _is_current_request(
        self,
        generation: int,
        session: Optional[WorldSession] = None,
    ) -> bool:
        """检查回调是否仍属于当前 loader 与存档会话。"""
        if generation != self._request_generation:
            return False
        return session is None or self._get_world_session() is session

    def dispose(self) -> None:
        """使未完成回调失效；任务作用域由 ExplorerView 统一关闭。"""
        self._next_request_generation()
        self._io.close()
