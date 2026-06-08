"""Entity/Block Search Service - 实体/方块搜索服务

搜索特定实体（村民、苦力怕）或方块（钻石矿、下界合金）的位置
"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List, Tuple
import traceback

from core.logger import logger
from core.region_utils import scan_region_dir


@dataclass
class SearchResult:
    """搜索结果"""

    result_type: str  # "entity"、"block" 或 "container"
    name: str
    position: Tuple[int, int, int]  # (x, y, z)
    dimension: str  # "overworld", "nether", "end"
    extra_info: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.extra_info is None:
            self.extra_info = {}

    def __repr__(self) -> str:
        return f"SearchResult({
            self.result_type}, {
            self.name}, {
            self.position}, {
                self.dimension})"


@dataclass
class SearchSummary:
    """搜索摘要，用于 UI 和日志展示。"""

    scanned_regions: int = 0
    scanned_chunks: int = 0
    skipped_chunks: int = 0
    warnings: List[str] = field(default_factory=list)


class EntityBlockSearchService:
    """实体/方块搜索服务"""

    # 常见实体类型
    COMMON_ENTITIES = [
        "minecraft:villager",
        "minecraft:creeper",
        "minecraft:zombie",
        "minecraft:skeleton",
        "minecraft:spider",
        "minecraft:enderman",
        "minecraft:cow",
        "minecraft:pig",
        "minecraft:sheep",
        "minecraft:chicken",
        "minecraft:wolf",
        "minecraft:cat",
        "minecraft:horse",
        "minecraft:minecart",
        "minecraft:item_frame",
        "minecraft:armor_stand",
    ]

    # 常见方块类型
    COMMON_BLOCKS = [
        "minecraft:diamond_ore",
        "minecraft:deepslate_diamond_ore",
        "minecraft:ancient_debris",
        "minecraft:emerald_ore",
        "minecraft:gold_ore",
        "minecraft:iron_ore",
        "minecraft:coal_ore",
        "minecraft:redstone_ore",
        "minecraft:lapis_ore",
        "minecraft:spawner",
        "minecraft:chest",
        "minecraft:trapped_chest",
        "minecraft:barrel",
        "minecraft:shulker_box",
        "minecraft:ender_chest",
        "minecraft:furnace",
        "minecraft:blast_furnace",
        "minecraft:smoker",
        "minecraft:hopper",
        "minecraft:dropper",
        "minecraft:dispenser",
        "minecraft:beacon",
        "minecraft:dragon_egg",
    ]

    # 常见容器方块实体类型
    COMMON_CONTAINERS = [
        "minecraft:chest",
        "minecraft:trapped_chest",
        "minecraft:barrel",
        "minecraft:shulker_box",
        "minecraft:white_shulker_box",
        "minecraft:orange_shulker_box",
        "minecraft:magenta_shulker_box",
        "minecraft:light_blue_shulker_box",
        "minecraft:yellow_shulker_box",
        "minecraft:lime_shulker_box",
        "minecraft:pink_shulker_box",
        "minecraft:gray_shulker_box",
        "minecraft:light_gray_shulker_box",
        "minecraft:cyan_shulker_box",
        "minecraft:purple_shulker_box",
        "minecraft:blue_shulker_box",
        "minecraft:brown_shulker_box",
        "minecraft:green_shulker_box",
        "minecraft:red_shulker_box",
        "minecraft:black_shulker_box",
        "minecraft:furnace",
        "minecraft:blast_furnace",
        "minecraft:smoker",
        "minecraft:hopper",
        "minecraft:dropper",
        "minecraft:dispenser",
        "minecraft:brewing_stand",
    ]

    MAX_RESULTS = 10000

    def __init__(self) -> None:
        self.results: List[SearchResult] = []
        self.summary = SearchSummary()

    def search(
        self,
        world_path: Path,
        search_type: str,  # "entity"、"block" 或 "container"
        target: str,  # 实体/方块 ID
        # ["overworld", "nether", "end"]
        dimensions: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[SearchResult]:
        """搜索实体或方块

        Args:
            world_path: 存档路径
            search_type: 搜索类型（entity、block 或 container）
            target: 目标实体/方块 ID
            dimensions: 要搜索的维度列表
            progress_callback: 进度回调
            log_callback: 日志回调

        Returns:
            搜索结果列表
        """
        self.results = []
        self.summary = SearchSummary()

        def log(msg: str, level: str = "INFO") -> None:
            logger.info(msg, module="EntityBlockSearch")
            if log_callback:
                log_callback(msg, level)

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(value, msg)

        from core.performance import get_tracker
        tracker = get_tracker()

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")
            if search_type not in {"entity", "block", "container"}:
                raise ValueError(f"不支持的搜索类型: {search_type}")
            if not target:
                raise ValueError("搜索目标不能为空")

            with tracker.track("实体方块搜索", {"world": world_path.name, "type": search_type, "target": target}):
                if dimensions is None:
                    dimensions = ["overworld", "nether", "end"]
                dimensions = [
                    d for d in dimensions if d in {
                        "overworld", "nether", "end"}]
                if not dimensions:
                    raise ValueError("未选择有效维度")

                log(f"开始搜索 {search_type}: {target}")
                log(f"搜索维度: {', '.join(dimensions)}")

                total_progress = 0.0
                step = 1.0 / len(dimensions)

                for dimension in dimensions:
                    progress(total_progress, f"搜索维度: {dimension}")

                    if search_type == "entity":
                        self._search_entities_in_dimension(
                            world_path, dimension, target, log, lambda v, m: progress(
                                total_progress + v * step, m), )
                    elif search_type == "block":
                        self._search_blocks_in_dimension(
                            world_path, dimension, target, log, lambda v, m: progress(
                                total_progress + v * step, m), )
                    elif search_type == "container":
                        self._search_containers_in_dimension(
                            world_path, dimension, target, log, lambda v, m: progress(
                                total_progress + v * step, m), )

                    if self._is_result_limit_reached():
                        log(f"结果数量达到上限 {self.MAX_RESULTS}，已停止继续扫描", "WARNING")
                        break

                    total_progress += step

                progress(1.0, f"搜索完成，找到 {len(self.results)} 个结果")
                log(f"搜索完成，共找到 {len(self.results)} 个 {target}")
                tracker.add_metadata("results", len(self.results))
                tracker.add_metadata("regions", self.summary.scanned_regions)
                tracker.add_metadata("chunks", self.summary.scanned_chunks)

                if search_type == "entity" and len(self.results) == 0:
                    warning = "提示: 1.18+ 存档的实体数据可能存储在独立 entities/ 区域文件中"
                    self.summary.warnings.append(warning)
                    log(warning, "WARNING")

        except Exception as e:
            error_msg = f"搜索失败: {e}"
            log(error_msg, "ERROR")
            logger.error(traceback.format_exc(), module="EntityBlockSearch")

        return self.results

    def _search_entities_in_dimension(
        self,
        world_path: Path,
        dimension: str,
        target: str,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        """在指定维度搜索实体

        Args:
            world_path: 存档路径
            dimension: 维度
            target: 目标实体 ID
            log: 日志回调
            progress: 进度回调
        """
        try:
            region_files = self._get_dimension_region_files(
                world_path, dimension)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return

            log(f"在 {dimension} 中找到 {len(region_files)} 个区块文件", "INFO")

            try:
                from anvil import Region

                total = len(region_files)
                for idx, region_file in enumerate(region_files):
                    if self._is_result_limit_reached():
                        return
                    progress(idx / total, f"搜索区块文件 {idx + 1}/{total}")
                    self.summary.scanned_regions += 1

                    try:
                        region = Region.from_file(str(region_file))

                        # 搜索每个区块
                        for cx in range(32):
                            for cz in range(32):
                                if self._is_result_limit_reached():
                                    return
                                try:
                                    chunk = region.get_chunk(cx, cz)
                                    if chunk is not None:
                                        self.summary.scanned_chunks += 1
                                        self._search_entities_in_chunk(
                                            chunk,
                                            target,
                                            dimension,
                                        )
                                except Exception:
                                    self.summary.skipped_chunks += 1

                    except Exception as e:
                        log(f"读取区块文件 {region_file.name} 失败: {e}", "WARNING")

            except ImportError:
                log("anvil-parser2 未安装，无法搜索实体", "ERROR")

        except Exception as e:
            log(f"搜索维度 {dimension} 失败: {e}", "ERROR")

    def _search_entities_in_chunk(
        self,
        chunk: Any,
        target: str,
        dimension: str,
    ) -> None:
        """在区块中搜索实体

        Args:
            chunk: 区块对象
            target: 目标实体 ID
            dimension: 维度
        """
        try:
            entities = self._get_entities(chunk)

            if not entities:
                return

            for entity in entities:
                try:
                    entity_id = self._tag_to_str(entity.get('id', ''))

                    # 检查是否匹配
                    if self._matches_target(entity_id, target):
                        # 获取位置
                        pos = entity.get('Pos', [])
                        if len(pos) >= 3:
                            x = int(float(self._tag_value(pos[0])))
                            y = int(float(self._tag_value(pos[1])))
                            z = int(float(self._tag_value(pos[2])))

                            # 提取额外信息
                            extra_info: Dict[str, Any] = {}

                            # 村民：职业
                            if 'villager' in entity_id:
                                villager_data = entity.get('VillagerData', {})
                                if hasattr(villager_data, 'get'):
                                    profession = villager_data.get(
                                        'profession', 'unknown')
                                    extra_info['profession'] = self._tag_to_str(
                                        profession)

                            # 生命值
                            health = entity.get('Health', None)
                            if health is not None:
                                try:
                                    extra_info['health'] = float(
                                        self._tag_value(health))
                                except (ValueError, TypeError):
                                    pass

                            # 自定义名称
                            custom_name = entity.get('CustomName', None)
                            if custom_name:
                                extra_info['custom_name'] = self._tag_to_str(
                                    custom_name)

                            # 添加结果
                            result = SearchResult(
                                result_type="entity",
                                name=entity_id,
                                position=(x, y, z),
                                dimension=dimension,
                                extra_info=extra_info,
                            )
                            self.results.append(result)
                            if len(self.results) >= self.MAX_RESULTS:
                                return

                except Exception:
                    pass  # 跳过无效实体

        except Exception:
            pass  # 跳过损坏的区块数据

    def _search_blocks_in_dimension(
        self,
        world_path: Path,
        dimension: str,
        target: str,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        """在指定维度搜索方块

        Args:
            world_path: 存档路径
            dimension: 维度
            target: 目标方块 ID
            log: 日志回调
            progress: 进度回调
        """
        try:
            region_files = self._get_dimension_region_files(
                world_path, dimension)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return

            log(f"在 {dimension} 中找到 {len(region_files)} 个区块文件", "INFO")

            try:
                from anvil import Region

                total = len(region_files)
                for idx, region_file in enumerate(region_files):
                    if self._is_result_limit_reached():
                        return
                    progress(idx / total, f"搜索区块文件 {idx + 1}/{total}")
                    self.summary.scanned_regions += 1

                    try:
                        region = Region.from_file(str(region_file))

                        # 搜索每个区块
                        for cx in range(32):
                            for cz in range(32):
                                if self._is_result_limit_reached():
                                    return
                                try:
                                    chunk = region.get_chunk(cx, cz)
                                    if chunk is not None:
                                        self.summary.scanned_chunks += 1
                                        self._search_blocks_in_chunk(
                                            chunk,
                                            target,
                                            dimension,
                                        )
                                except Exception:
                                    self.summary.skipped_chunks += 1

                    except Exception as e:
                        log(f"读取区块文件 {region_file.name} 失败: {e}", "WARNING")

            except ImportError:
                log("anvil-parser2 未安装，无法搜索方块", "ERROR")

        except Exception as e:
            log(f"搜索维度 {dimension} 失败: {e}", "ERROR")

    def _search_blocks_in_chunk(
        self,
        chunk: Any,
        target: str,
        dimension: str,
    ) -> None:
        """在区块中搜索方块

        Args:
            chunk: 区块对象
            target: 目标方块 ID
            dimension: 维度
        """
        try:
            from anvil import Block

            target_block = None
            if ":" in target:
                try:
                    target_block = Block.from_name(target)
                except Exception:
                    pass

            section_range = self._get_section_range(chunk)
            matching_sections = []

            for section_y in section_range:
                try:
                    palette = chunk.get_palette(section_y)
                    if palette is None:
                        continue
                    for block in palette:
                        if block is None:
                            continue
                        if target_block and block == target_block:
                            matching_sections.append(section_y)
                            break
                        block_name = self._get_block_name(block)
                        block_id = self._tag_to_str(getattr(block, "id", ""))
                        if self._matches_target(
                                block_name,
                                target) or self._matches_target(
                                block_id,
                                target):
                            matching_sections.append(section_y)
                            break
                except Exception:
                    continue

            if not matching_sections:
                return

            for section_y in matching_sections:
                y_start = section_y * 16
                y_end = y_start + 16
                for x in range(16):
                    for z in range(16):
                        for y in range(y_start, y_end):
                            try:
                                block = chunk.get_block(x, y, z)
                                if block is None:
                                    continue
                                block_name = self._get_block_name(block)
                                block_id = self._tag_to_str(
                                    getattr(block, "id", ""))
                                if self._matches_target(
                                        block_name,
                                        target) or self._matches_target(
                                        block_id,
                                        target):
                                    world_x = chunk.x * 16 + x
                                    world_z = chunk.z * 16 + z
                                    result = SearchResult(
                                        result_type="block", name=block_name, position=(
                                            world_x, y, world_z), dimension=dimension, extra_info=self._get_container_info_at(
                                            chunk, world_x, y, world_z), )
                                    self.results.append(result)
                                    if len(self.results) >= self.MAX_RESULTS:
                                        return
                            except Exception:
                                pass

        except Exception:
            pass

    def _search_containers_in_dimension(
        self,
        world_path: Path,
        dimension: str,
        target: str,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        """在指定维度搜索容器方块实体。"""
        try:
            region_files = self._get_dimension_region_files(
                world_path, dimension)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return

            log(f"在 {dimension} 中找到 {len(region_files)} 个区块文件", "INFO")

            try:
                from anvil import Region

                total = len(region_files)
                for idx, region_file in enumerate(region_files):
                    if self._is_result_limit_reached():
                        return
                    progress(idx / total, f"搜索容器 {idx + 1}/{total}")
                    self.summary.scanned_regions += 1

                    try:
                        region = Region.from_file(str(region_file))
                        for cx in range(32):
                            for cz in range(32):
                                if self._is_result_limit_reached():
                                    return
                                try:
                                    chunk = region.get_chunk(cx, cz)
                                    if chunk is not None:
                                        self.summary.scanned_chunks += 1
                                        self._search_containers_in_chunk(
                                            chunk, target, dimension)
                                except Exception:
                                    self.summary.skipped_chunks += 1
                    except Exception as e:
                        log(f"读取区块文件 {region_file.name} 失败: {e}", "WARNING")

            except ImportError:
                log("anvil-parser2 未安装，无法搜索容器", "ERROR")

        except Exception as e:
            log(f"搜索维度 {dimension} 失败: {e}", "ERROR")

    def _search_containers_in_chunk(
            self,
            chunk: Any,
            target: str,
            dimension: str) -> None:
        """在区块中搜索容器方块实体。"""
        try:
            if not hasattr(chunk, "data") or not chunk.data:
                return

            for block_entity in self._get_block_entities(chunk):
                try:
                    container_id = self._tag_to_str(block_entity.get("id", ""))
                    if not self._matches_target(container_id, target):
                        continue

                    position = self._get_block_entity_position(block_entity)
                    if position is None:
                        continue

                    result = SearchResult(
                        result_type="container",
                        name=container_id,
                        position=position,
                        dimension=dimension,
                        extra_info=self._extract_container_info(block_entity),
                    )
                    self.results.append(result)
                    if len(self.results) >= self.MAX_RESULTS:
                        return
                except Exception:
                    pass
        except Exception:
            pass

    def _get_container_info_at(
            self, chunk: Any, x: int, y: int, z: int) -> Dict[str, Any]:
        """返回指定坐标容器内容摘要；非容器返回空字典。"""
        try:
            for block_entity in self._get_block_entities(chunk):
                position = self._get_block_entity_position(block_entity)
                if position == (x, y, z):
                    return self._extract_container_info(block_entity)
        except Exception:
            pass
        return {}

    def _get_block_entities(self, chunk: Any) -> List[Any]:
        data = chunk.data if hasattr(chunk, "data") else chunk
        if not data:
            return []
        for key in ("block_entities", "BlockEntities", "TileEntities"):
            block_entities = data.get(key, [])
            if block_entities:
                return list(block_entities)
        level = data.get("Level", {})
        if hasattr(level, "get"):
            for key in ("block_entities", "BlockEntities", "TileEntities"):
                block_entities = level.get(key, [])
                if block_entities:
                    return list(block_entities)
        return []

    def _get_entities(self, chunk: Any) -> List[Any]:
        data = chunk.data if hasattr(chunk, "data") else chunk
        if not data:
            return []
        for key in ("entities", "Entities"):
            entities = data.get(key, [])
            if entities:
                return list(entities)
        level = data.get("Level", {})
        if hasattr(level, "get"):
            for key in ("entities", "Entities"):
                entities = level.get(key, [])
                if entities:
                    return list(entities)
        return []

    def _get_block_entity_position(
            self, block_entity: Any) -> Optional[Tuple[int, int, int]]:
        try:
            x = block_entity.get("x", block_entity.get("X"))
            y = block_entity.get("y", block_entity.get("Y"))
            z = block_entity.get("z", block_entity.get("Z"))
            if x is None or y is None or z is None:
                return None
            return (int(self._tag_value(x)), int(
                self._tag_value(y)), int(self._tag_value(z)))
        except Exception:
            return None

    def _extract_container_info(self, block_entity: Any) -> Dict[str, Any]:
        items = block_entity.get(
            "Items",
            []) if hasattr(
            block_entity,
            "get") else []
        parsed_items = []

        for item in items or []:
            try:
                item_id = self._tag_to_str(item.get("id", "unknown"))
                count = int(self._tag_value(item.get("Count", 1)))
                slot = item.get("Slot", None)
                slot_text = ""
                if slot is not None:
                    slot_text = f"槽位{int(self._tag_value(slot))}: "
                parsed_items.append(f"{slot_text}{item_id} x{count}")
            except Exception:
                pass

        custom_name = block_entity.get(
            "CustomName", None) if hasattr(
            block_entity, "get") else None
        info: Dict[str, Any] = {
            "item_count": len(parsed_items),
            "items": "; ".join(parsed_items) if parsed_items else "空",
        }
        if custom_name:
            info["custom_name"] = self._tag_to_str(custom_name)
        return info

    def _matches_target(self, name: str, target: str) -> bool:
        return target == "*" or name == target or name.endswith(f":{target}")

    def _get_block_name(self, block: Any) -> str:
        try:
            name_attr = getattr(block, "name", "")
            if callable(name_attr):
                return self._tag_to_str(name_attr())
            return self._tag_to_str(name_attr)
        except Exception:
            return ""

    def _is_result_limit_reached(self) -> bool:
        return len(self.results) >= self.MAX_RESULTS

    def _get_dimension_region_files(
            self,
            world_path: Path,
            dimension: str) -> List[Path]:
        dimension_path = self._get_dimension_path(world_path, dimension)
        if not dimension_path:
            return []
        return scan_region_dir(dimension_path / "region")

    def _tag_to_str(self, value: Any) -> str:
        raw_value = self._tag_value(value)
        return str(raw_value)

    def _tag_value(self, value: Any) -> Any:
        return getattr(value, "value", value)

    def _get_section_range(self, chunk: Any) -> range:
        try:
            from anvil.chunk import _section_height_range
            result = _section_height_range(chunk.version)
            if isinstance(result, range):
                return result
            return range(-4, 20)
        except Exception:
            return range(-4, 20)

    def _get_dimension_path(
            self,
            world_path: Path,
            dimension: str) -> Optional[Path]:
        """获取维度路径

        Args:
            world_path: 存档路径
            dimension: 维度名称

        Returns:
            维度路径或 None
        """
        if dimension == "overworld":
            return world_path
        elif dimension == "nether":
            # 尝试多个可能的路径
            paths = [
                world_path / "DIM-1",
                world_path / "dimensions" / "minecraft" / "the_nether",
            ]
            for p in paths:
                if p.exists():
                    return p
            return None
        elif dimension == "end":
            paths = [
                world_path / "DIM1",
                world_path / "dimensions" / "minecraft" / "the_end",
            ]
            for p in paths:
                if p.exists():
                    return p
            return None
        return None

    def export_results_to_text(
            self, output_path: Path, results: Optional[List[SearchResult]] = None) -> None:
        """将搜索结果导出为文本文件

        Args:
            output_path: 输出文件路径
        """
        try:
            export_results = results if results is not None else self.results
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"搜索结果 - 共 {len(export_results)} 个\n")
                f.write(f"扫描区域: {self.summary.scanned_regions}\n")
                f.write(f"扫描区块: {self.summary.scanned_chunks}\n")
                f.write(f"跳过区块: {self.summary.skipped_chunks}\n")
                f.write("=" * 80 + "\n\n")

                for idx, result in enumerate(export_results, 1):
                    f.write(f"{idx}. {result.name}\n")
                    f.write(f"   类型: {result.result_type}\n")
                    f.write(
                        f"   位置: X={
                            result.position[0]}, Y={
                            result.position[1]}, Z={
                            result.position[2]}\n")
                    f.write(f"   维度: {result.dimension}\n")

                    if result.extra_info:
                        f.write("   额外信息:\n")
                        for key, value in result.extra_info.items():
                            f.write(f"      {key}: {value}\n")

                    f.write("\n")

        except Exception as e:
            logger.error(f"导出结果失败: {e}", module="EntityBlockSearch")
