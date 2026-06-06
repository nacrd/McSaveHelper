"""Entity/Block Search Service - 实体/方块搜索服务

搜索特定实体（村民、苦力怕）或方块（钻石矿、下界合金）的位置
"""
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
import traceback

from core.logger import logger
from core.scanner import scan_all_regions


class SearchResult:
    """搜索结果"""
    
    def __init__(
        self,
        result_type: str,  # "entity" 或 "block"
        name: str,
        position: Tuple[int, int, int],  # (x, y, z)
        dimension: str,  # "overworld", "nether", "end"
        extra_info: Optional[Dict[str, Any]] = None,
    ):
        self.result_type = result_type
        self.name = name
        self.position = position
        self.dimension = dimension
        self.extra_info = extra_info or {}

    def __repr__(self) -> str:
        return f"SearchResult({self.result_type}, {self.name}, {self.position}, {self.dimension})"


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
        "minecraft:ender_chest",
        "minecraft:beacon",
        "minecraft:dragon_egg",
    ]

    def __init__(self) -> None:
        self.results: List[SearchResult] = []

    def search(
        self,
        world_path: Path,
        search_type: str,  # "entity" 或 "block"
        target: str,  # 实体/方块 ID
        dimensions: Optional[List[str]] = None,  # ["overworld", "nether", "end"]
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[SearchResult]:
        """搜索实体或方块
        
        Args:
            world_path: 存档路径
            search_type: 搜索类型（entity 或 block）
            target: 目标实体/方块 ID
            dimensions: 要搜索的维度列表
            progress_callback: 进度回调
            log_callback: 日志回调
            
        Returns:
            搜索结果列表
        """
        self.results = []

        def log(msg: str, level: str = "INFO") -> None:
            logger.info(msg, module="EntityBlockSearch")
            if log_callback:
                log_callback(msg, level)

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(value, msg)

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            if dimensions is None:
                dimensions = ["overworld", "nether", "end"]

            log(f"开始搜索 {search_type}: {target}")
            log(f"搜索维度: {', '.join(dimensions)}")

            total_progress = 0.0
            step = 1.0 / len(dimensions)

            for dimension in dimensions:
                progress(total_progress, f"搜索维度: {dimension}")
                
                if search_type == "entity":
                    self._search_entities_in_dimension(
                        world_path,
                        dimension,
                        target,
                        log,
                        lambda v, m: progress(total_progress + v * step, m),
                    )
                elif search_type == "block":
                    self._search_blocks_in_dimension(
                        world_path,
                        dimension,
                        target,
                        log,
                        lambda v, m: progress(total_progress + v * step, m),
                    )
                
                total_progress += step

            progress(1.0, f"搜索完成，找到 {len(self.results)} 个结果")
            log(f"搜索完成，共找到 {len(self.results)} 个 {target}")

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
            # 获取维度路径
            dimension_path = self._get_dimension_path(world_path, dimension)
            if not dimension_path:
                log(f"维度 {dimension} 不存在", "WARNING")
                return

            # 扫描区块文件
            region_files = scan_all_regions(dimension_path)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return

            log(f"在 {dimension} 中找到 {len(region_files)} 个区块文件", "INFO")

            try:
                from anvil import Region
                
                total = len(region_files)
                for idx, region_file in enumerate(region_files):
                    progress(idx / total, f"搜索区块文件 {idx+1}/{total}")
                    
                    try:
                        region = Region.from_file(str(region_file))
                        
                        # 搜索每个区块
                        for cx in range(32):
                            for cz in range(32):
                                try:
                                    chunk = region.get_chunk(cx, cz)
                                    if chunk is not None:
                                        self._search_entities_in_chunk(
                                            chunk,
                                            target,
                                            dimension,
                                        )
                                except Exception:
                                    pass  # 跳过损坏的区块
                                    
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
            # 获取区块数据
            if not hasattr(chunk, 'data') or 'Entities' not in chunk.data:
                return

            entities = chunk.data.get('Entities', [])
            
            for entity in entities:
                try:
                    entity_id = str(entity.get('id', ''))
                    
                    # 检查是否匹配
                    if entity_id == target or entity_id.endswith(f":{target}"):
                        # 获取位置
                        pos = entity.get('Pos', [])
                        if len(pos) >= 3:
                            x = int(float(pos[0]))
                            y = int(float(pos[1]))
                            z = int(float(pos[2]))
                            
                            # 提取额外信息
                            extra_info: Dict[str, Any] = {}
                            
                            # 村民：职业
                            if 'villager' in entity_id:
                                profession = entity.get('VillagerData', {}).get('profession', 'unknown')
                                extra_info['profession'] = str(profession)
                            
                            # 生命值
                            health = entity.get('Health', None)
                            if health is not None:
                                try:
                                    extra_info['health'] = float(str(health))
                                except (ValueError, TypeError):
                                    pass
                            
                            # 自定义名称
                            custom_name = entity.get('CustomName', None)
                            if custom_name:
                                extra_info['custom_name'] = str(custom_name)
                            
                            # 添加结果
                            result = SearchResult(
                                result_type="entity",
                                name=entity_id,
                                position=(x, y, z),
                                dimension=dimension,
                                extra_info=extra_info,
                            )
                            self.results.append(result)
                            
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
            # 获取维度路径
            dimension_path = self._get_dimension_path(world_path, dimension)
            if not dimension_path:
                log(f"维度 {dimension} 不存在", "WARNING")
                return

            # 扫描区块文件
            region_files = scan_all_regions(dimension_path)
            if not region_files:
                log(f"维度 {dimension} 没有区块文件", "WARNING")
                return

            log(f"在 {dimension} 中找到 {len(region_files)} 个区块文件", "INFO")

            try:
                from anvil import Region
                
                total = len(region_files)
                for idx, region_file in enumerate(region_files):
                    progress(idx / total, f"搜索区块文件 {idx+1}/{total}")
                    
                    try:
                        region = Region.from_file(str(region_file))
                        
                        # 搜索每个区块
                        for cx in range(32):
                            for cz in range(32):
                                try:
                                    chunk = region.get_chunk(cx, cz)
                                    if chunk is not None:
                                        self._search_blocks_in_chunk(
                                            chunk,
                                            target,
                                            dimension,
                                        )
                                except Exception:
                                    pass  # 跳过损坏的区块
                                    
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
            # 搜索区块中的所有方块
            for x in range(16):
                for z in range(16):
                    for y in range(-64, 320):  # 1.18+ 世界高度
                        try:
                            block = chunk.get_block(x, y, z)
                            if block:
                                block_id = str(block.id)
                                
                                # 检查是否匹配
                                if block_id == target or block_id.endswith(f":{target}"):
                                    # 计算世界坐标
                                    world_x = chunk.x * 16 + x
                                    world_z = chunk.z * 16 + z
                                    
                                    # 添加结果
                                    result = SearchResult(
                                        result_type="block",
                                        name=block_id,
                                        position=(world_x, y, world_z),
                                        dimension=dimension,
                                    )
                                    self.results.append(result)
                                    
                        except Exception:
                            pass  # 跳过无效方块
                            
        except Exception:
            pass  # 跳过损坏的区块数据

    def _get_dimension_path(self, world_path: Path, dimension: str) -> Optional[Path]:
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

    def export_results_to_text(self, output_path: Path) -> None:
        """将搜索结果导出为文本文件
        
        Args:
            output_path: 输出文件路径
        """
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"搜索结果 - 共 {len(self.results)} 个\n")
                f.write("=" * 80 + "\n\n")
                
                for idx, result in enumerate(self.results, 1):
                    f.write(f"{idx}. {result.name}\n")
                    f.write(f"   类型: {result.result_type}\n")
                    f.write(f"   位置: X={result.position[0]}, Y={result.position[1]}, Z={result.position[2]}\n")
                    f.write(f"   维度: {result.dimension}\n")
                    
                    if result.extra_info:
                        f.write(f"   额外信息:\n")
                        for key, value in result.extra_info.items():
                            f.write(f"      {key}: {value}\n")
                    
                    f.write("\n")
                    
        except Exception as e:
            logger.error(f"导出结果失败: {e}", module="EntityBlockSearch")
