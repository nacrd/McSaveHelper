"""NBT、JSON 与区块数据源加载协调器。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import flet as ft
import nbtlib

from app.models.nbt_edit import (
    ChunkNbtTarget,
    NbtEditFormat,
    NbtTarget,
)
from app.ui.views.explorer.explorer_helpers import world_coords_to_region_chunk
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
        self._get_dimension = get_dimension
        self._set_target_state = set_target_state
        self._load_player_data = load_player_data
        self._render_chunk_objects = render_chunk_objects
        self._query_current_block = query_current_block
        self._target_dropdown = target_dropdown
        self._target_label = target_label
        self._region_file_field = region_file_field
        self._chunk_x_field = chunk_x_field
        self._chunk_z_field = chunk_z_field
        self._world_x_field = world_x_field
        self._world_z_field = world_z_field
        self._nbt_tree = nbt_tree
        self._warn = warn
        self._info = info
        self._handle_error = handle_error
        self._save_file = save_file
        self._target_options: Dict[str, Path] = {}

    def update_nbt_target_options(self) -> None:
        """扫描当前存档中可直接编辑的 NBT 与 JSON 文件。"""
        try:
            self._target_options.clear()
            session = self._get_world_session()
            if not session:
                self._set_target_options([])
                return
            self._set_target_options(
                self._find_nbt_target_candidates(session.world_path)
            )
        except Exception as ex:
            self._handle_error(ex, "刷新 NBT 目标失败")

    @staticmethod
    def _find_nbt_target_candidates(world_path: Path) -> List[Tuple[str, Path]]:
        candidates: List[Tuple[str, Path]] = []
        if (world_path / "level.dat").exists():
            candidates.append(("世界 / level.dat", Path("level.dat")))
        candidates.extend(
            (f"数据 / {path.name}", path.relative_to(world_path))
            for path in sorted((world_path / "data").glob("*.dat"))
        )
        for folder_name, label in (("stats", "统计"), ("advancements", "进度")):
            candidates.extend(
                (f"{label} / {path.name}", path.relative_to(world_path))
                for path in sorted((world_path / folder_name).glob("*.json"))
            )
        return candidates

    def _set_target_options(self, candidates: List[Tuple[str, Path]]) -> None:
        self._target_options.update(
            {relative_path.as_posix(): relative_path for _, relative_path in candidates}
        )
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
        path = session.world_path / relative_path
        if not path.exists():
            self._warn("提示", f"文件不存在: {relative_path}")
            return
        if path.suffix.lower() != ".dat":
            self.load_json_file(relative_path, label)
            return

        self._set_loaded_target(relative_path, label, "nbt")
        self._nbt_tree.load_nbt(nbtlib.load(path))

    def load_json_file(self, relative_path: Path, label: str) -> None:
        """加载 stats/advancements 等 JSON 并以树形式展示。

        Args:
            relative_path: 相对世界根的路径。
            label: UI 展示标签。
        """
        session = self._require_session()
        if session is None:
            return
        path = session.world_path / relative_path
        if not path.exists():
            self._warn("提示", f"文件不存在: {relative_path}")
            return

        json_label = label.replace("NBT 文件", "JSON 文件")
        self._set_loaded_target(relative_path, json_label, "json")
        with path.open("r", encoding="utf-8") as file:
            self._nbt_tree.load_nbt(json.load(file))

    def load_chunk_nbt(self, e: Any = None) -> None:
        """从区域路径与区块坐标加载区块 NBT（校验路径不越界世界根）。

        Args:
            e: 可选 Flet 事件。
        """
        try:
            session = self._require_session()
            if session is None:
                return
            relative_text = (
                self._region_file_field.value or ""
            ).strip().replace("\\", "/")
            if not relative_text:
                self._warn(
                    "提示",
                    "请输入区域文件路径，例如 region/r.0.0.mca。",
                )
                return

            relative_path = Path(relative_text)
            region_path = (session.world_path / relative_path).resolve()
            world_root = session.world_path.resolve()
            try:
                region_path.relative_to(world_root)
            except ValueError:
                self._warn("提示", "区域文件必须位于当前存档目录内。")
                return
            if not region_path.exists() or region_path.suffix.lower() != ".mca":
                self._warn(
                    "提示",
                    f"区域文件不存在或不是 .mca 文件: {relative_text}",
                )
                return

            chunk_x = int((self._chunk_x_field.value or "0").strip())
            chunk_z = int((self._chunk_z_field.value or "0").strip())
            result = session.load_chunk_nbt(relative_path, chunk_x, chunk_z)
            if result is None:
                self._warn("提示", "该区块不存在或无法读取。")
                return

            chunk_data, _absolute_path = result
            target = ChunkNbtTarget(
                region_path=relative_path,
                chunk_x=chunk_x,
                chunk_z=chunk_z,
                data=chunk_data,
            )
            label = f"区块 NBT: {relative_text} [{chunk_x}, {chunk_z}]"
            self._set_target_state(target, label, "chunk", target)
            self._target_label.value = label
            safe_update(self._target_label)
            self._nbt_tree.load_nbt(chunk_data, editable=True)
            self._render_chunk_objects(chunk_data)
            self._query_current_block()
        except ValueError:
            self._warn("提示", "区块坐标必须是整数。")
        except Exception as ex:
            self._handle_error(ex, "加载区块 NBT 失败")

    def fill_chunk_from_world_coords(self, e: Any = None) -> None:
        """根据世界坐标填入区域路径与区块坐标字段。

        Args:
            e: 可选 Flet 事件。
        """
        try:
            self._set_chunk_fields_from_world_coords()
        except ValueError:
            self._warn("提示", "世界坐标必须是数字。")
        except Exception as ex:
            self._handle_error(ex, "填入区块坐标失败")

    def load_chunk_from_world_coords(self, e: Any = None) -> None:
        """填入区块坐标后立即加载该区块 NBT。

        Args:
            e: 可选 Flet 事件。
        """
        try:
            self._set_chunk_fields_from_world_coords()
        except ValueError:
            self._warn("提示", "世界坐标必须是数字。")
            return
        except Exception as ex:
            self._handle_error(ex, "填入区块坐标失败")
            return
        self.load_chunk_nbt(e)

    def reload_current_nbt_target(self) -> None:
        """按当前目标类型重新从磁盘加载（Path/玩家/区块）。"""
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
            if self._nbt_tree.get_modified_data() is None:
                self._warn("提示", "没有可导出的 NBT 数据")
                return
            path = self._save_file(
                title="保存 JSON 文件",
                default_ext=".json",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if not path:
                return
            if self._nbt_tree.export_json(path):
                self._info("成功", f"已导出到: {path}")
            else:
                self._warn(
                    "导出失败",
                    "导出 JSON 文件失败，请检查文件路径和权限。",
                )
        except Exception as ex:
            self._handle_error(ex, "导出 JSON 失败")

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

    def _set_chunk_fields_from_world_coords(self) -> None:
        world_x = int(float((self._world_x_field.value or "0").strip()))
        world_z = int(float((self._world_z_field.value or "0").strip()))
        region_x, region_z, chunk_x, chunk_z = world_coords_to_region_chunk(
            world_x,
            world_z,
        )
        region_dir = self._dimension_region_dir(self._get_dimension())
        self._region_file_field.value = (
            f"{region_dir}/r.{region_x}.{region_z}.mca"
        )
        self._chunk_x_field.value = str(chunk_x)
        self._chunk_z_field.value = str(chunk_z)
        safe_update(self._region_file_field)
        safe_update(self._chunk_x_field)
        safe_update(self._chunk_z_field)

    @staticmethod
    def _dimension_region_dir(dimension: str) -> str:
        if dimension == "the_nether":
            return "DIM-1/region"
        if dimension == "the_end":
            return "DIM1/region"
        if dimension and dimension != "overworld":
            return f"dimensions/{dimension}/region"
        return "region"
