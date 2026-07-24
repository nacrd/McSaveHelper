"""Explorer 区块 NBT 输入、后台加载与 UI 投影协调器。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import flet as ft

from app.models.nbt_edit import ChunkNbtTarget, NbtEditFormat, NbtTarget
from app.ui.views.explorer.explorer_helpers import world_coords_to_region_chunk
from app.ui.views.explorer.nbt.nbt_io_coordinator import NbtIoCoordinator
from app.ui.views.explorer.nbt.nbt_io_operations import (
    ChunkLoadResult,
    ChunkMissingError,
    ChunkPathError,
    load_chunk_payload,
)
from app.ui.views.explorer.nbt_tree import NBTTreeView
from app.ui.views.explorer.utils import safe_update
from core.omni.world_session import WorldSession


DialogCallback = Callable[[str, str], None]
ErrorCallback = Callable[[Exception, str], None]
TargetStateCallback = Callable[
    [Optional[NbtTarget], str, NbtEditFormat, Optional[ChunkNbtTarget]],
    None,
]


@dataclass(frozen=True)
class NbtChunkLoaderContext:
    """区块加载所需的会话、维度与请求身份端口。"""

    get_world_session: Callable[[], Optional[WorldSession]]
    get_dimension: Callable[[], str]
    next_generation: Callable[[], int]
    is_current: Callable[[int, Optional[WorldSession]], bool]


@dataclass(frozen=True)
class NbtChunkLoaderUi:
    """区块加载使用的控件和 UI 回调。"""

    set_target_state: TargetStateCallback
    render_chunk_objects: Callable[[Any], None]
    query_current_block: Callable[[], None]
    target_label: ft.Text
    region_file_field: ft.TextField
    chunk_x_field: ft.TextField
    chunk_z_field: ft.TextField
    world_x_field: ft.TextField
    world_z_field: ft.TextField
    nbt_tree: NBTTreeView
    warn: DialogCallback
    handle_error: ErrorCallback


@dataclass(frozen=True)
class _ChunkRequest:
    """一次已完成 UI 输入校验的区块读取请求。"""

    relative_path: Path
    relative_text: str
    chunk_x: int
    chunk_z: int


class NbtChunkLoader:
    """协调区块表单、共享 I/O 通道和区块 UI 投影。"""

    def __init__(
        self,
        io: NbtIoCoordinator,
        context: NbtChunkLoaderContext,
        ui: NbtChunkLoaderUi,
    ) -> None:
        """绑定共享 I/O、请求身份端口和区块控件。

        Args:
            io: NBT 数据加载器共享的 I/O 协调器。
            context: 当前世界、维度和 generation 端口。
            ui: 区块输入、结果投影和消息端口。
        """
        self._io = io
        self._context = context
        self._ui = ui

    def load_chunk_nbt(self, e: Any = None) -> None:
        """校验区块表单并异步加载目标区块。

        Args:
            e: 可选 Flet 事件。
        """
        try:
            session = self._require_session()
            if session is None:
                return
            request = self._read_request()
            if request is None:
                return
            generation = self._context.next_generation()
            self._submit_request(session, request, generation)
        except Exception as ex:
            self._ui.handle_error(ex, "加载区块 NBT 失败")

    def _submit_request(
        self,
        session: WorldSession,
        request: _ChunkRequest,
        generation: int,
    ) -> None:
        """把已校验请求提交到共享 I/O 通道。"""
        self._io.submit(
            "load_chunk_nbt",
            lambda token: load_chunk_payload(
                session,
                request.relative_path,
                request.relative_text,
                request.chunk_x,
                request.chunk_z,
                token,
            ),
            lambda result: self._apply_payload(result, session, generation),
            "加载区块 NBT 失败",
            on_error=lambda error: self._apply_error(
                error,
                session,
                generation,
            ),
            session=session,
            request_guard=lambda: self._context.is_current(
                generation,
                session,
            ),
        )

    def _read_request(self) -> Optional[_ChunkRequest]:
        """读取表单；可恢复的用户输入错误直接显示并返回 None。"""
        relative_text = (
            self._ui.region_file_field.value or ""
        ).strip().replace("\\", "/")
        if not relative_text:
            self._ui.warn(
                "提示",
                "请输入区域文件路径，例如 region/r.0.0.mca。",
            )
            return None
        try:
            chunk_x = int((self._ui.chunk_x_field.value or "0").strip())
            chunk_z = int((self._ui.chunk_z_field.value or "0").strip())
        except ValueError:
            self._ui.warn("提示", "区块坐标必须是整数。")
            return None
        return _ChunkRequest(
            relative_path=Path(relative_text),
            relative_text=relative_text,
            chunk_x=chunk_x,
            chunk_z=chunk_z,
        )

    def _apply_payload(
        self,
        result: ChunkLoadResult,
        session: WorldSession,
        generation: int,
    ) -> None:
        """把当前请求的区块结果投影到 Explorer 控件。"""
        if not self._context.is_current(generation, session):
            return
        target = ChunkNbtTarget(
            region_path=result.region_path,
            chunk_x=result.chunk_x,
            chunk_z=result.chunk_z,
            data=result.data,
        )
        label = (
            f"区块 NBT: {result.relative_text} "
            f"[{result.chunk_x}, {result.chunk_z}]"
        )
        self._ui.set_target_state(target, label, "chunk", target)
        self._ui.target_label.value = label
        safe_update(self._ui.target_label)
        self._ui.nbt_tree.load_nbt(result.data, editable=True)
        self._ui.render_chunk_objects(result.data)
        self._ui.query_current_block()

    def _apply_error(
        self,
        error: Exception,
        session: WorldSession,
        generation: int,
    ) -> None:
        """把当前请求的区块领域错误转换为用户消息。"""
        if not self._context.is_current(generation, session):
            return
        if isinstance(error, ChunkMissingError):
            self._ui.warn("提示", "该区块不存在或无法读取。")
            return
        if isinstance(error, ChunkPathError):
            self._ui.warn("提示", str(error))
            return
        self._ui.handle_error(error, "加载区块 NBT 失败")

    def fill_chunk_from_world_coords(self, e: Any = None) -> None:
        """根据世界坐标填入区域路径与区块坐标字段。

        Args:
            e: 可选 Flet 事件。
        """
        self._fill_with_error_handling()

    def load_chunk_from_world_coords(self, e: Any = None) -> None:
        """填入区块坐标后立即加载该区块 NBT。

        Args:
            e: 可选 Flet 事件。
        """
        if self._fill_with_error_handling():
            self.load_chunk_nbt(e)

    def _fill_with_error_handling(self) -> bool:
        """填充区块字段，并统一处理用户输入和未知错误。"""
        try:
            self._set_fields_from_world_coords()
        except ValueError:
            self._ui.warn("提示", "世界坐标必须是数字。")
            return False
        except Exception as ex:
            self._ui.handle_error(ex, "填入区块坐标失败")
            return False
        return True

    def _set_fields_from_world_coords(self) -> None:
        """解析世界坐标并更新对应区域和区块字段。"""
        world_x = int(float((self._ui.world_x_field.value or "0").strip()))
        world_z = int(float((self._ui.world_z_field.value or "0").strip()))
        region_x, region_z, chunk_x, chunk_z = world_coords_to_region_chunk(
            world_x,
            world_z,
        )
        region_dir = dimension_region_dir(self._context.get_dimension())
        self._ui.region_file_field.value = (
            f"{region_dir}/r.{region_x}.{region_z}.mca"
        )
        self._ui.chunk_x_field.value = str(chunk_x)
        self._ui.chunk_z_field.value = str(chunk_z)
        safe_update(self._ui.region_file_field)
        safe_update(self._ui.chunk_x_field)
        safe_update(self._ui.chunk_z_field)

    def _require_session(self) -> Optional[WorldSession]:
        """返回当前会话；缺失时显示统一提示。"""
        session = self._context.get_world_session()
        if session is None:
            self._ui.warn("提示", "请先通过侧边栏设置当前存档。")
        return session


def dimension_region_dir(dimension: str) -> str:
    """返回维度对应的世界相对区域目录。

    Args:
        dimension: Explorer 当前维度 id。

    Returns:
        Java 版世界根目录下的相对 region 目录。
    """
    if dimension == "the_nether":
        return "DIM-1/region"
    if dimension == "the_end":
        return "DIM1/region"
    if dimension and dimension != "overworld":
        return f"dimensions/{dimension}/region"
    return "region"
