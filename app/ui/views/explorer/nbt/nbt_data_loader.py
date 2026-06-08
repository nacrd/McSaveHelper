"""NBT Data Loader - 负责加载各种 NBT 数据源"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import flet as ft
import nbtlib

from app.ui.views.explorer.utils import safe_update


class NbtDataLoader:
    """NBT 数据加载器 - 统一处理 NBT/JSON/区块数据的加载"""

    def __init__(self, context: Any):
        """
        Args:
            context: 上下文对象，需要提供 world_session, app, current_uuid, _nbt_tree 等属性
        """
        self.ctx = context

    # ==================== 目标选项管理 ====================

    def update_nbt_target_options(self) -> None:
        """更新 NBT 目标下拉列表"""
        try:
            self.ctx._nbt_target_options.clear()
            if not self.ctx.world_session:
                if hasattr(self.ctx, "_nbt_target_dropdown"):
                    self.ctx._nbt_target_dropdown.options = []
                    safe_update(self.ctx._nbt_target_dropdown)
                return

            world_path = self.ctx.world_session.world_path
            candidates: List[Tuple[str, Path]] = []

            # level.dat
            level_path = world_path / "level.dat"
            if level_path.exists():
                candidates.append(("世界 / level.dat", Path("level.dat")))

            # data/*.dat
            data_dir = world_path / "data"
            if data_dir.exists():
                for path in sorted(data_dir.glob("*.dat")):
                    candidates.append(
                        (f"数据 / {path.name}", path.relative_to(world_path)))

            # stats/*.json, advancements/*.json
            for folder_name, label in [
                    ("stats", "统计"), ("advancements", "进度")]:
                folder = world_path / folder_name
                if folder.exists():
                    for path in sorted(folder.glob("*.json")):
                        candidates.append(
                            (f"{label} / {path.name}", path.relative_to(world_path)))

            # 填充选项字典
            for label, relative_path in candidates:
                key = str(relative_path).replace("\\", "/")
                self.ctx._nbt_target_options[key] = relative_path

            # 更新下拉框
            if hasattr(self.ctx, "_nbt_target_dropdown"):
                self.ctx._nbt_target_dropdown.options = [
                    ft.dropdown.Option(
                        key, label) for label, key in [
                        (label, str(path).replace(
                            "\\", "/")) for label, path in candidates]]
                safe_update(self.ctx._nbt_target_dropdown)
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="刷新 NBT 目标失败")

    # ==================== 通用加载入口 ====================

    def load_current_player_nbt(self, e: Any = None) -> None:
        """加载当前选中玩家的 NBT"""
        try:
            if not self.ctx.current_uuid:
                self.ctx.app.warn_dialog("提示", "请先选择玩家。")
                return
            self.ctx._load_player_data(self.ctx.current_uuid)
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="加载玩家 NBT 失败")

    def load_level_nbt(self, e: Any = None) -> None:
        """加载 level.dat"""
        try:
            if not self.ctx.world_session:
                self.ctx.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return
            self.load_nbt_file(Path("level.dat"), "世界 NBT: level.dat")
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="加载 level.dat 失败")

    def load_selected_nbt_target(self, e: Any) -> None:
        """加载下拉列表选中的 NBT 目标"""
        try:
            key = e.control.value
            if not key or key not in self.ctx._nbt_target_options:
                return
            relative_path = self.ctx._nbt_target_options[key]
            self.load_nbt_file(relative_path, f"NBT 文件: {key}")
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="加载 NBT 目标失败")

    # ==================== 文件加载 ====================

    def load_nbt_file(self, relative_path: Path, label: str) -> None:
        """加载 NBT 文件"""
        if not self.ctx.world_session:
            self.ctx.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
            return

        path = self.ctx.world_session.world_path / relative_path
        if not path.exists():
            self.ctx.app.warn_dialog("提示", f"文件不存在: {relative_path}")
            return

        # 根据扩展名判断类型
        if path.suffix.lower() != ".dat":
            self.load_json_file(relative_path, label)
            return

        # 加载 NBT 文件
        self.ctx._current_nbt_target = relative_path
        self.ctx._current_nbt_label = label
        self.ctx._current_edit_format = "nbt"
        self.ctx._nbt_target_label.value = self.ctx._current_nbt_label
        self.ctx._nbt_target_dropdown.value = str(
            relative_path).replace("\\", "/")
        safe_update(self.ctx._nbt_target_label)
        safe_update(self.ctx._nbt_target_dropdown)
        self.ctx._nbt_tree.load_nbt(nbtlib.load(path))

    def load_json_file(self, relative_path: Path, label: str) -> None:
        """加载 JSON 文件（统计、进度等）"""
        if not self.ctx.world_session:
            self.ctx.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
            return

        path = self.ctx.world_session.world_path / relative_path
        if not path.exists():
            self.ctx.app.warn_dialog("提示", f"文件不存在: {relative_path}")
            return

        self.ctx._current_nbt_target = relative_path
        self.ctx._current_nbt_label = label.replace("NBT 文件", "JSON 文件")
        self.ctx._current_edit_format = "json"
        self.ctx._nbt_target_label.value = self.ctx._current_nbt_label
        self.ctx._nbt_target_dropdown.value = str(
            relative_path).replace("\\", "/")
        safe_update(self.ctx._nbt_target_label)
        safe_update(self.ctx._nbt_target_dropdown)

        with open(path, "r", encoding="utf-8") as f:
            self.ctx._nbt_tree.load_nbt(json.load(f))

    # ==================== 区块加载 ====================

    def load_chunk_nbt(self, e: Any = None) -> None:
        """加载区块 NBT"""
        try:
            if not self.ctx.world_session:
                self.ctx.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return

            relative_text = (
                self.ctx._region_file_field.value or "").strip().replace(
                "\\", "/")
            if not relative_text:
                self.ctx.app.warn_dialog(
                    "提示", "请输入区域文件路径，例如 region/r.0.0.mca。")
                return

            relative_path = Path(relative_text)
            region_path = (
                self.ctx.world_session.world_path /
                relative_path).resolve()
            world_root = self.ctx.world_session.world_path.resolve()

            # 安全检查：确保文件在存档目录内
            try:
                region_path.relative_to(world_root)
            except ValueError:
                self.ctx.app.warn_dialog("提示", "区域文件必须位于当前存档目录内。")
                return

            if not region_path.exists() or region_path.suffix.lower() != ".mca":
                self.ctx.app.warn_dialog(
                    "提示", f"区域文件不存在或不是 .mca 文件: {relative_text}")
                return

            chunk_x = int((self.ctx._chunk_x_field.value or "0").strip())
            chunk_z = int((self.ctx._chunk_z_field.value or "0").strip())

            # 加载区块数据
            result = self.ctx.world_session.load_chunk_nbt(
                relative_path, chunk_x, chunk_z)
            if result is None:
                self.ctx.app.warn_dialog("提示", "该区块不存在或无法读取。")
                return

            chunk_data, abs_path = result

            # 保存区块信息用于后续提交
            self.ctx._current_chunk_target = {
                "region_path": relative_path,
                "chunk_x": chunk_x,
                "chunk_z": chunk_z,
                "data": chunk_data
            }
            self.ctx._current_nbt_target = self.ctx._current_chunk_target
            self.ctx._current_nbt_label = f"区块 NBT: {relative_text} [{chunk_x}, {chunk_z}]"
            self.ctx._current_edit_format = "chunk"
            self.ctx._nbt_target_label.value = self.ctx._current_nbt_label
            safe_update(self.ctx._nbt_target_label)
            self.ctx._nbt_tree.load_nbt(chunk_data, editable=True)

            # 渲染区块对象
            if hasattr(self.ctx, '_render_chunk_objects'):
                self.ctx._render_chunk_objects(chunk_data)

            # 查询当前坐标的方块
            if hasattr(self.ctx, '_query_block_at_current_coords'):
                self.ctx._query_block_at_current_coords(silent=True)

        except ValueError:
            self.ctx.app.warn_dialog("提示", "区块坐标必须是整数。")
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="加载区块 NBT 失败")

    # ==================== 坐标转换辅助 ====================

    def fill_chunk_from_world_coords(self, e: Any = None) -> None:
        """根据世界坐标填入区块坐标"""
        try:
            world_x = int(
                float(
                    (self.ctx._world_x_field.value or "0").strip()))
            world_z = int(
                float(
                    (self.ctx._world_z_field.value or "0").strip()))
            region_x, region_z, chunk_x, chunk_z = self.ctx._world_coords_to_region_chunk(
                world_x, world_z)

            # 确定维度路径
            if hasattr(
                    self.ctx,
                    "_current_dimension") and self.ctx._current_dimension:
                dim_name = self.ctx._current_dimension
                if dim_name == "overworld":
                    region_path = "region"
                elif dim_name == "the_nether":
                    region_path = "DIM-1/region"
                elif dim_name == "the_end":
                    region_path = "DIM1/region"
                else:
                    region_path = f"dimensions/{dim_name}/region"
            else:
                region_path = "region"

            self.ctx._region_file_field.value = f"{region_path}/r.{region_x}.{region_z}.mca"
            self.ctx._chunk_x_field.value = str(chunk_x)
            self.ctx._chunk_z_field.value = str(chunk_z)
            safe_update(self.ctx._region_file_field)
            safe_update(self.ctx._chunk_x_field)
            safe_update(self.ctx._chunk_z_field)
        except ValueError:
            self.ctx.app.warn_dialog("提示", "世界坐标必须是数字。")
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="填入区块坐标失败")

    def load_chunk_from_world_coords(self, e: Any = None) -> None:
        """根据世界坐标定位并加载区块"""
        self.fill_chunk_from_world_coords(e)
        self.load_chunk_nbt(e)

    # ==================== 重新加载 ====================

    def reload_current_nbt_target(self) -> None:
        """重新加载当前 NBT 目标"""
        if isinstance(self.ctx._current_nbt_target, Path):
            self.load_nbt_file(
                self.ctx._current_nbt_target,
                self.ctx._current_nbt_label)
        elif isinstance(self.ctx._current_nbt_target, str):
            self.ctx._load_player_data(self.ctx._current_nbt_target)
        elif isinstance(self.ctx._current_nbt_target, dict) and "region_path" in self.ctx._current_nbt_target:
            self.load_chunk_nbt()

    # ==================== 导出 ====================

    def export_nbt_json(self, e: Any = None) -> None:
        """导出 NBT 为 JSON"""
        try:
            if not self.ctx._nbt_tree._root_data:
                self.ctx.app.warn_dialog("提示", "没有可导出的 NBT 数据")
                return

            path = self.ctx.app.save_file(
                title="保存 JSON 文件",
                default_ext=".json",
                file_types=[("JSON 文件 (*.json)", "*.json")]
            )
            if path:
                success = self.ctx._nbt_tree.export_json(path)
                if success:
                    self.ctx.app.info_dialog("成功", f"已导出到: {path}")
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="导出 JSON 失败")
