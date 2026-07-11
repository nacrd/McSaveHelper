"""Map Export Service - 地图导出服务

将存档地图导出为 PNG 图片（俯视图/地形图）
"""
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Tuple, List
import traceback

from core.logger import logger
from core.region_utils import parse_region_coords, scan_region_dir

try:
    from PIL import Image, ImageDraw
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
            raise ImportError(
                "需要安装 Pillow 库才能使用地图导出功能\n请运行: pip install Pillow")

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

            from core.performance import get_tracker
            tracker = get_tracker()
            with tracker.track("地图导出", {"world": world_path.name, "type": map_type}):
                log(f"开始导出地图: {world_path}", "INFO")
                progress(0.05, "扫描区块文件...")

            # 只扫描主世界的区块文件（避免不同维度区块重叠）
            region_dir = world_path / "region"
            if not region_dir.exists():
                raise ValueError("未找到主世界 region 目录")

            region_files = scan_region_dir(region_dir)

            if not region_files:
                raise ValueError("未找到区块文件")

            log(f"找到 {len(region_files)} 个区块文件", "INFO")

            # 分析区块范围
            progress(0.15, "分析地图范围...")
            bounds = self._analyze_region_bounds(region_files, log)
            log(
                f"地图范围: X[{
                    bounds['min_x']} ~ {
                    bounds['max_x']}], Z[{
                    bounds['min_z']} ~ {
                    bounds['max_z']}]",
                "INFO")

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
            # 在关闭前获取图像尺寸，避免访问已关闭的图像对象
            image_size = image.size
            try:
                image.save(output_path, "PNG")
                log(f"地图已保存: {output_path}", "INFO")
            finally:
                # 确保关闭图像对象，释放文件句柄
                image.close()

            results["success"] = True
            results["output_path"] = str(output_path)
            results["dimensions"] = image_size
            results["chunks_processed"] = len(region_files)
            tracker.increment_files(len(region_files))

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
        min_x = float('inf')
        max_x = float('-inf')
        min_z = float('inf')
        max_z = float('-inf')

        for region_file in region_files:
            coords = parse_region_coords(region_file)
            if coords is not None:
                rx, rz = coords
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

        MAX_DIMENSION = 32768
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            needed_scale = max(
                ((bounds["max_x"] - bounds["min_x"] + 1) * 32 * 16) // MAX_DIMENSION + 1,
                ((bounds["max_z"] - bounds["min_z"] + 1) * 32 * 16) // MAX_DIMENSION + 1,
            )
            raise ValueError(
                f"图像尺寸过大 ({width}x{height})，超出限制 ({MAX_DIMENSION}px)。"
                f"请将缩放比例调整为至少 1:{needed_scale}"
            )

        pixel_count = width * height
        estimated_mb = pixel_count * 3 / (1024 * 1024)
        if estimated_mb > 2048:
            raise ValueError(
                f"预计图像内存占用约 {estimated_mb:.0f} MB，超出安全限制 (2048 MB)。"
                f"请增大缩放比例以减小图像尺寸"
            )

        log(f"创建 {width}x{height} 的图像 (预计 {estimated_mb:.0f} MB)", "INFO")

        # 创建图像
        image = Image.new(
            "RGB", (width, height), color=(
                135, 206, 235))  # 天蓝色背景

        try:
            from core.mca import NativeRegion

            # 使用像素访问对象，比逐个 putpixel 调用快得多
            pixels = image.load()

            total = len(region_files)
            for idx, region_file in enumerate(region_files):
                # 更新进度 (25% - 95%)
                progress(0.25 + (idx / total) * 0.70,
                         f"渲染区块 {idx + 1}/{total}")

                try:
                    # 解析区块坐标
                    coords = parse_region_coords(region_file)
                    if coords is None:
                        continue

                    rx, rz = coords

                    with NativeRegion.from_file(region_file) as region:
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
                                            pixels,
                                        )
                                except Exception:
                                    pass  # 跳过损坏的区块

                except Exception as e:
                    log(f"处理区块文件 {region_file.name} 失败: {e}", "WARNING")

        except ImportError:
            log("地图渲染后端不可用，使用简化渲染", "WARNING")
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
        pixels: Any = None,
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
            pixels: 像素访问对象（可选，用于批量写入优化）
        """
        try:
            if pixels is None:
                pixels = image.load()

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

                            # 绘制像素（使用像素访问对象，比 putpixel 快 5-10 倍）
                            if 0 <= px < image.width and 0 <= py < image.height:
                                pixels[px, py] = color
                    except Exception:
                        pass  # 跳过无效方块

        except Exception:
            pass  # 跳过损坏的区块数据

    def _get_highest_block_y(self, chunk: Any, x: int,
                             z: int) -> Optional[int]:
        try:
            blocks = getattr(chunk, "_blocks", None)
            if blocks is not None and hasattr(blocks, "surface_y"):
                return blocks.surface_y(x, z)

            cache_attr = "_mcsh_non_air_sections"
            non_air_sections = getattr(chunk, cache_attr, None)
            if non_air_sections is None:
                try:
                    from core.mca import section_range_for_chunk
                    section_range = section_range_for_chunk(chunk)
                except Exception:
                    section_range = range(-4, 20)

                non_air_sections = []
                for section_y in reversed(list(section_range)):
                    try:
                        palette = chunk.get_palette(section_y)
                        if palette is None:
                            continue
                        has_non_air = any(
                            p is not None and not str(getattr(p, "id", "")).endswith("air")
                            for p in palette
                        )
                        if has_non_air:
                            non_air_sections.append(section_y)
                    except Exception:
                        continue
                try:
                    setattr(chunk, cache_attr, non_air_sections)
                except Exception:
                    pass

            for section_y in non_air_sections:
                y_start = section_y * 16
                for y in range(y_start + 15, y_start - 1, -1):
                    try:
                        block = chunk.get_block(x, y, z)
                        bid = str(getattr(block, "id", ""))
                        if block and not bid.endswith("air"):
                            return y
                    except Exception:
                        continue
            return None
        except Exception:
            return None

    def _get_block_color(self, block: Any, y: int,
                         map_type: str) -> Tuple[int, int, int]:
        """获取方块颜色

        Args:
            block: 方块对象
            y: Y 坐标
            map_type: 地图类型

        Returns:
            RGB 颜色元组
        """
        try:
            block_name = block.name()

            if block_name in self.BLOCK_COLORS:
                color = self.BLOCK_COLORS[block_name]
            else:
                color = self._generate_color_from_name(block_name)

            # 地形图：根据高度调整亮度
            if map_type == "terrain":
                factor = (y + 64) / 383.0  # 归一化到 [0, 1]
                color = tuple(int(c * (0.5 + factor * 0.5))
                              for c in color)  # type: ignore[assignment]

            return color

        except Exception:
            return (128, 128, 128)  # 默认灰色

    def _generate_color_from_name(
            self, block_name: str) -> Tuple[int, int, int]:
        h = hashlib.md5(block_name.encode("utf-8")).digest()
        return (h[0], h[1], h[2])
