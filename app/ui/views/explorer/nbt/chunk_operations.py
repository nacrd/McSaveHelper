"""区块对象展示与单方块查询、替换交互。"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import flet as ft

from app.models.nbt_edit import ChunkNbtTarget, NbtEditFormat, NbtPathPart
from core.mca.block_data_service import BlockDataService
from app.ui.components.cards import placeholder
from app.ui.icons import IconSet
from app.ui.theme import THEME
from app.ui.views.explorer.explorer_helpers import extract_chunk_objects
from app.ui.views.explorer.utils import safe_update


ErrorCallback = Callable[[Exception, str], None]
DialogCallback = Callable[[str, str], None]
StageCallback = Callable[[List[NbtPathPart], Any, Any, str], None]


class ChunkOperations:
    """协调区块控件与可复用的方块数据服务。

    方块替换只改内存区块并暂存，真正写 MCA 由上层提交流程完成。
    """

    def __init__(
        self,
        *,
        objects_list: ft.Column,
        nbt_tree: Any,
        target_label: ft.Text,
        world_x_field: ft.TextField,
        world_z_field: ft.TextField,
        block_y_field: ft.TextField,
        block_result: ft.Text,
        block_name_field: ft.TextField,
        get_chunk_target: Callable[[], Optional[ChunkNbtTarget]],
        set_view_state: Callable[[str, NbtEditFormat], None],
        stage_change: StageCallback,
        warn: DialogCallback,
        info: DialogCallback,
        handle_error: ErrorCallback,
        block_service: BlockDataService,
    ) -> None:
        """绑定区块对象列表、坐标字段与方块服务。

        Args:
            objects_list: 实体/方块实体列表容器。
            nbt_tree: NBT 树视图（需提供 ``load_nbt``）。
            target_label: 当前目标标签文本。
            world_x_field: 世界 X 输入框。
            world_z_field: 世界 Z 输入框。
            block_y_field: 世界 Y 输入框。
            block_result: 查询结果展示文本。
            block_name_field: 替换目标方块 ID 输入框。
            get_chunk_target: 取当前已加载区块目标。
            set_view_state: 设置视图标签与编辑格式。
            stage_change: 暂存回调。
            warn: 警告对话框。
            info: 信息对话框。
            handle_error: 异常处理。
            block_service: 方块读写服务（必填，禁止 UI 静默自建）。
        """
        self._objects_list = objects_list
        self._nbt_tree = nbt_tree
        self._target_label = target_label
        self._world_x_field = world_x_field
        self._world_z_field = world_z_field
        self._block_y_field = block_y_field
        self._block_result = block_result
        self._block_name_field = block_name_field
        self._get_chunk_target = get_chunk_target
        self._set_view_state = set_view_state
        self._stage_change = stage_change
        self._warn = warn
        self._info = info
        self._handle_error = handle_error
        self._block_service = block_service
        self._last_objects: List[Dict[str, Any]] = []

    def render_chunk_objects(self, chunk_data: Any) -> None:
        """提取并渲染区块内的实体和方块实体。"""
        try:
            self._block_service.clear_cache()
            self._last_objects = extract_chunk_objects(chunk_data)
            self.render_chunk_object_rows(self._last_objects)
        except Exception as ex:
            self._handle_error(ex, "渲染区块对象失败")

    def on_chunk_object_filter(self, e: Any) -> None:
        """按标题/副标题子串过滤已提取的区块对象列表。

        Args:
            e: 输入框变更事件，读取 ``e.control.value``。
        """
        query = (e.control.value or "").strip().lower()
        if not query:
            self.render_chunk_object_rows(self._last_objects)
            return
        filtered = [
            obj for obj in self._last_objects
            if query in obj["title"].lower() or query in obj["subtitle"].lower()
        ]
        self.render_chunk_object_rows(filtered)

    def render_chunk_object_rows(self, objects: List[Dict[str, Any]]) -> None:
        """渲染对象行；超过 120 条时截断并提示剩余数量。

        Args:
            objects: 含 title/subtitle/icon/data 的对象字典列表。
        """
        try:
            self._objects_list.controls.clear()
            if not objects:
                self._objects_list.controls.append(placeholder(
                    icon=IconSet.PACKAGE,
                    title="未发现实体或方块实体",
                    subtitle="请先加载区块，区块内的实体和容器将在此列出",
                    height=100,
                ))
            else:
                for obj in objects[:120]:
                    self._objects_list.controls.append(ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(obj["icon"], size=16, width=28),
                                ft.Column(
                                    [
                                        ft.Text(
                                            obj["title"],
                                            size=12,
                                            color=THEME.text_primary,
                                        ),
                                        ft.Text(
                                            obj["subtitle"],
                                            size=11,
                                            color=THEME.text_muted,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.TextButton(
                                    "查看",
                                    on_click=lambda e, data=obj["data"],
                                    title=obj["title"]: self.show_chunk_object(
                                        data, title
                                    ),
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding(left=6, right=6, top=4, bottom=4),
                        bgcolor=THEME.bg_card,
                    ))
                if len(objects) > 120:
                    self._objects_list.controls.append(ft.Text(
                        f"已显示前 120 个对象，剩余 {len(objects) - 120} 个",
                        size=12,
                        color=THEME.text_muted,
                    ))
            safe_update(self._objects_list)
        except Exception as ex:
            self._handle_error(ex, "渲染区块对象失败")

    def show_chunk_object(self, data: Any, title: str) -> None:
        """在 NBT 树中打开单个实体/方块实体。

        Args:
            data: 对象 NBT 子树。
            title: 展示标题。
        """
        editable = self._get_chunk_target() is not None
        label = f"区块对象: {title}" if editable else f"区块对象只读: {title}"
        edit_format: NbtEditFormat = "chunk" if editable else "chunk_readonly"
        self._set_view_state(label, edit_format)
        self._target_label.value = label
        safe_update(self._target_label)
        self._nbt_tree.load_nbt(data, editable=editable)

    def query_block_at_current_coords(
        self,
        e: Any = None,
        silent: bool = False,
    ) -> None:
        """查询当前区块数据中指定世界坐标的方块状态。

        Args:
            e: 可选点击事件（未使用，兼容 Flet 回调签名）。
            silent: True 时坐标非法或未加载区块不弹警告。
        """
        try:
            target = self._get_chunk_target()
            if target is None:
                if not silent:
                    self._warn("提示", "请先加载区块。")
                return
            world_x, world_y, world_z = self._read_block_coords()
            block = self._block_service.get_block_at(
                target.data,
                world_x,
                world_y,
                world_z,
            )
            if block is None:
                self._block_result.value = "未找到方块状态"
                self._block_result.color = THEME.warning
            else:
                properties = ", ".join(
                    f"{key}={value}" for key, value in block.properties.items()
                )
                suffix = f" [{properties}]" if properties else ""
                self._block_result.value = f"{block.name}{suffix}"
                self._block_result.color = THEME.text_secondary
            safe_update(self._block_result)
        except ValueError:
            if not silent:
                self._warn("提示", "方块坐标必须是数字。")
        except Exception as ex:
            self._handle_error(ex, "查询方块失败")

    def replace_block_at_current_coords(self, e: Any = None) -> None:
        """修改当前区块中的一个方块，并将变更加入暂存区。

        未带命名空间的方块 ID 会自动补 ``minecraft:`` 前缀。

        Args:
            e: 可选点击事件（未使用，兼容 Flet 回调签名）。
        """
        try:
            target = self._get_chunk_target()
            if target is None:
                self._warn("提示", "请先加载区块。")
                return
            block_name = (self._block_name_field.value or "").strip()
            if not block_name:
                self._warn("提示", "请输入方块 ID。")
                return
            if ":" not in block_name:
                block_name = f"minecraft:{block_name}"

            world_x, world_y, world_z = self._read_block_coords()
            result = self._block_service.set_block_at(
                target.data,
                world_x,
                world_y,
                world_z,
                block_name,
            )
            if not result.success:
                self._warn("替换失败", result.message)
                return
            if result.old_name != result.new_name:
                path: List[NbtPathPart] = [
                    "block",
                    world_x,
                    world_y,
                    world_z,
                ]
                display_path = f"方块 ({world_x}, {world_y}, {world_z})"
                self._stage_change(
                    path,
                    result.old_name,
                    result.new_name,
                    display_path,
                )
            self._nbt_tree.load_nbt(target.data, editable=True)
            self.query_block_at_current_coords(silent=True)
            self._info("方块替换", result.message)
        except ValueError:
            self._warn("提示", "方块坐标必须是数字。")
        except Exception as ex:
            self._handle_error(ex, "替换方块失败")

    def _read_block_coords(self) -> tuple[int, int, int]:
        world_x = int(float((self._world_x_field.value or "0").strip()))
        world_y = int(float((self._block_y_field.value or "0").strip()))
        world_z = int(float((self._world_z_field.value or "0").strip()))
        return world_x, world_y, world_z
