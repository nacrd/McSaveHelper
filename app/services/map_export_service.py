"""Map Export Service - 地图导出服务

将存档地图导出为 PNG 图片（俯视图/地形图）
"""
import io
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Tuple, List
import traceback

from core.logger import logger
from core.scanner import scan_all_regions

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class MapExportService:
    """地图导出服务"""

    # 方块颜色映射（简化版）
    BLOCK_COLORS = {
        "minecraft:air": (135, 206, 235),  # 天蓝色
        "minecraft:stone": (128, 128, 128),
        "minecraft:grass_block": (34, 139, 34),
        "minecraft:dirt": (139, 69, 19),
        "minecraft:sand": (238, 214, 175),
        "minecraft:water": (64, 164, 223),
        "minecraft:lava": (207, 16, 32),
        "minecraft:snow": (255, 255, 255),
        "minecraft:ice": (151, 210, 255),
        "minecraft:gravel": (136, 136, 136),
        "minecraft:bedrock": (85, 85, 85),
        "minecraft:oak_log": (139, 90, 43),
        "minecraft:oak_leaves": (0, 100, 0),
        "minecraft:cobblestone": (169, 169, 169),
        "minecraft:coal_ore": (67, 67, 67),
        "minecraft:iron_ore": (216, 175, 147),
        "minecraft:gold_ore": (255, 215, 0),
        "minecraft:diamond_ore": (0, 191, 255),
        "minecraft:emerald_ore": (0, 201, 87),
        "minecraft:obsidian": (20, 18, 29),
        "minecraft:netherrack": (139, 0, 0),
        "minecraft:soul_sand": (84, 64, 51),
        "minecraft:glowstone": (255, 198, 73),
        "minecraft:end_stone": (221, 223, 165),
    }

    def __init__(self) -> None:
        if not PIL_AVAILABLE:
            raise ImportError("需要安装 Pillow 库才能使用地图导出功能\n请运行: pip install Pillow")

    def export_map(
        self,
        world_path: Path,
        output_path: Path,
        map_type: str = "topview",  # topview 或 terrain
        scale: int = 1,  # 缩放比例
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """导出地图
        
        Args:
            world_path: 存档路径
            output_path: 输出文件路径
            map_type: 地图类型 (topview: 俯视图, terrain: 地形图)
            scale: 缩放比例
            progress_callback: 进度回调
            log_callback: 日志回调
            
        Returns:
            导出结果字典
        """
        results: Dict[str, Any] = {
            "success": False,
            "output_path": None,
            "dimensions": (0, 0),
            "chunks_processed": 0,
        }

        def log(msg: str, level: str = "INFO") -> None:
            logger.info(msg, module="MapExport")
            if log_callback:
                log_callback(msg, level)

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(value, msg)

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            log(f"开始导出地图: {world_path}", "INFO")
            progress(0.05, "扫描区块文件...")

            # 扫描区块文件
            region_files = scan_all_regions(world_path)
            if not region_files:
                raise ValueError("未找到区块文件")

            log(f"找到 {len(region_files)} 个区块文件", "INFO")

            # 分析区块范围
            progress(0.15, "分析地图范围...")
            bounds = self._analyze_region_bounds(region_files, log)
            log(f"地图范围: X[{bounds['min_x']} ~ {bounds['max_x']}], Z[{bounds['min_z']} ~ {bounds['max_z']}]", "INFO")

            # 创建地图图像
            progress(0.25, "创建地图图像...")
            image = self._create_map_image(
                world_path,
                region_files,
                bounds,
                map_type,
                scale,
                log,
                progress,
            )

            # 保存图像
            progress(0.95, "保存图像...")
            image.save(output_path, "PNG")
            log(f"地图已保存: {output_path}", "INFO")

            results["success"] = True
            results["output_path"] = str(output_path)
            results["dimensions"] = image.size
            results["chunks_processed"] = len(region_files)

            progress(1.0, "导出完成")

        except Exception as e:
            error_msg = f"导出失败: {e}"
            log(error_msg, "ERROR")
            logger.error(traceback.format_exc(), module="MapExport")

        return results

    def _analyze_region_bounds(
        self,
        region_files: List[Path],
        log: Callable[[str, str], None],
    ) -> Dict[str, int]:
        """分析区块文件范围
        
        Args:
            region_files: 区块文件列表
            log: 日志回调
            
        Returns:
            范围字典
        """
        import re
        
        min_x = float('inf')
        max_x = float('-inf')
        min_z = float('inf')
        max_z = float('-inf')

        pattern = re.compile(r"r\.(-?\d+)\.(-?\d+)\.mca")
        
        for region_file in region_files:
            match = pattern.match(region_file.name)
            if match:
                rx = int(match.group(1))
                rz = int(match.group(2))
                min_x = min(min_x, rx)
                max_x = max(max_x, rx)
                min_z = min(min_z, rz)
                max_z = max(max_z, rz)

        return {
            "min_x": int(min_x),
            "max_x": int(max_x),
            "min_z": int(min_z),
            "max_z": int(max_z),
        }

    def _create_map_image(
        self,
        world_path: Path,
        region_files: List[Path],
        bounds: Dict[str, int],
        map_type: str,
        scale: int,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> Image.Image:
        """创建地图图像
        
        Args:
            world_path: 存档路径
            region_files: 区块文件列表
            bounds: 区块范围
            map_type: 地图类型
            scale: 缩放比例
            log: 日志回调
            progress: 进度回调
            
        Returns:
            PIL 图像对象
        """
        # 计算图像尺寸（每个区块文件 32x32 区块，每个区块 16x16 方块）
        width = (bounds["max_x"] - bounds["min_x"] + 1) * 32 * 16
        height = (bounds["max_z"] - bounds["min_z"] + 1) * 32 * 16

        # 应用缩放
        width = width // scale
        height = height // scale

        log(f"创建 {width}x{height} 的图像", "INFO")
        
        # 创建图像
        image = Image.new("RGB", (width, height), color=(135, 206, 235))  # 天蓝色背景

        try:
            from anvil import Region
            
            total = len(region_files)
            for idx, region_file in enumerate(region_files):
                # 更新进度 (25% - 95%)
                progress(0.25 + (idx / total) * 0.70, f"渲染区块 {idx+1}/{total}")
                
                try:
                    # 解析区块坐标
                    import re
                    pattern = re.compile(r"r\.(-?\d+)\.(-?\d+)\.mca")
                    match = pattern.match(region_file.name)
                    if not match:
                        continue
                    
                    rx = int(match.group(1))
                    rz = int(match.group(2))
                    
                    # 读取区块
                    region = Region.from_file(str(region_file))
                    
                    # 渲染区块
                    for cx in range(32):
                        for cz in range(32):
                            try:
                                chunk = region.get_chunk(cx, cz)
                                if chunk is not None:
                                    self._render_chunk(
                                        image,
                                        chunk,
                                        rx,
                                        rz,
                                        cx,
                                        cz,
                                        bounds,
                                        map_type,
                                        scale,
                                    )
                            except Exception:
                                pass  # 跳过损坏的区块
                                
                except Exception as e:
                    log(f"处理区块文件 {region_file.name} 失败: {e}", "WARNING")
                    
        except ImportError:
            log("anvil-parser2 未安装，使用简化渲染", "WARNING")
            # 简化渲染：绘制网格
            draw = ImageDraw.Draw(image)
            for i in range(0, width, 16 // scale):
                draw.line([(i, 0), (i, height)], fill=(200, 200, 200), width=1)
            for i in range(0, height, 16 // scale):
                draw.line([(0, i), (width, i)], fill=(200, 200, 200), width=1)

        return image

    def _render_chunk(
        self,
        image: Image.Image,
        chunk: Any,
        rx: int,
        rz: int,
        cx: int,
        cz: int,
        bounds: Dict[str, int],
        map_type: str,
        scale: int,
    ) -> None:
        """渲染单个区块
        
        Args:
            image: PIL 图像对象
            chunk: 区块对象
            rx: 区块文件 X 坐标
            rz: 区块文件 Z 坐标
            cx: 区块 X 偏移
            cz: 区块 Z 偏移
            bounds: 区块范围
            map_type: 地图类型
            scale: 缩放比例
        """
        try:
            # 计算区块在图像中的位置
            chunk_x = (rx - bounds["min_x"]) * 32 + cx
            chunk_z = (rz - bounds["min_z"]) * 32 + cz
            
            # 获取区块的最高方块
            for bx in range(16):
                for bz in range(16):
                    try:
                        # 获取最高非空气方块
                        y = self._get_highest_block_y(chunk, bx, bz)
                        if y is not None:
                            # 获取方块类型
                            block = chunk.get_block(bx, y, bz)
                            color = self._get_block_color(block, y, map_type)
                            
                            # 计算像素位置
                            px = (chunk_x * 16 + bx) // scale
                            py = (chunk_z * 16 + bz) // scale
                            
                            # 绘制像素
                            if 0 <= px < image.width and 0 <= py < image.height:
                                image.putpixel((px, py), color)
                    except Exception:
                        pass  # 跳过无效方块
                        
        except Exception:
            pass  # 跳过损坏的区块数据

    def _get_highest_block_y(self, chunk: Any, x: int, z: int) -> Optional[int]:
        """获取最高非空气方块的 Y 坐标
        
        Args:
            chunk: 区块对象
            x: 方块 X 坐标
            z: 方块 Z 坐标
            
        Returns:
            Y 坐标或 None
        """
        try:
            # 从高到低搜索
            for y in range(319, -64, -1):  # 1.18+ 世界高度
                try:
                    block = chunk.get_block(x, y, z)
                    if block and not block.id.endswith("air"):
                        return y
                except Exception:
                    continue
            return None
        except Exception:
            return None

    def _get_block_color(self, block: Any, y: int, map_type: str) -> Tuple[int, int, int]:
        """获取方块颜色
        
        Args:
            block: 方块对象
            y: Y 坐标
            map_type: 地图类型
            
        Returns:
            RGB 颜色元组
        """
        try:
            block_id = str(block.id)
            
            # 从颜色映射中获取
            if block_id in self.BLOCK_COLORS:
                color = self.BLOCK_COLORS[block_id]
            else:
                # 默认颜色：根据方块名称生成
                color = self._generate_color_from_name(block_id)
            
            # 地形图：根据高度调整亮度
            if map_type == "terrain":
                factor = (y + 64) / 383.0  # 归一化到 [0, 1]
                color = tuple(int(c * (0.5 + factor * 0.5)) for c in color)  # type: ignore[assignment]
            
            return color
            
        except Exception:
            return (128, 128, 128)  # 默认灰色

    def _generate_color_from_name(self, block_id: str) -> Tuple[int, int, int]:
        """根据方块 ID 生成颜色
        
        Args:
            block_id: 方块 ID
            
        Returns:
            RGB 颜色元组
        """
        # 使用哈希生成稳定的颜色
        h = hash(block_id)
        r = (h & 0xFF0000) >> 16
        g = (h & 0x00FF00) >> 8
        b = h & 0x0000FF
        return (r, g, b)
