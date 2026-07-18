"""PIL renderer for exported Minecraft region maps."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

try:
    from PIL import Image as _Image
    from PIL import ImageDraw as _ImageDraw
    Image = _Image
    ImageDraw = _ImageDraw
    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional packaged dependency
    Image = cast(Any, None)
    ImageDraw = cast(Any, None)
    PIL_AVAILABLE = False

from core.region_utils import parse_region_coords


@dataclass(frozen=True)
class MapImageSpec:
    width: int
    height: int
    estimated_mb: float


def analyze_region_bounds(region_files: List[Path]) -> Dict[str, int]:
    """Return the inclusive region coordinate bounds for valid MCA paths."""
    coords = [
        parsed
        for region_file in region_files
        if (parsed := parse_region_coords(region_file)) is not None
    ]
    if not coords:
        raise ValueError("未找到有效的区域文件坐标")
    return {
        "min_x": min(coord[0] for coord in coords),
        "max_x": max(coord[0] for coord in coords),
        "min_z": min(coord[1] for coord in coords),
        "max_z": max(coord[1] for coord in coords),
    }


class MapExportRenderer:
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

    def create_map_image(
        self,
        region_files: List[Path],
        bounds: Dict[str, int],
        map_type: str,
        scale: int,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> Any:
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
        if not PIL_AVAILABLE:
            raise ImportError("需要安装 Pillow 库才能导出地图")
        spec = self.calculate_image_spec(bounds, scale)
        log(
            f"创建 {spec.width}x{spec.height} 的图像 "
            f"(预计 {spec.estimated_mb:.0f} MB)",
            "INFO",
        )
        image = Image.new(
            "RGB",
            (spec.width, spec.height),
            color=(135, 206, 235),
        )
        try:
            self._render_regions(
                image,
                region_files,
                bounds,
                map_type,
                scale,
                log,
                progress,
            )
        except ImportError:
            log("地图渲染后端不可用，使用简化渲染", "WARNING")
            self.draw_fallback_grid(image, scale)
        return image

    @staticmethod
    def calculate_image_spec(
        bounds: Dict[str, int],
        scale: int,
    ) -> MapImageSpec:
        region_width = bounds["max_x"] - bounds["min_x"] + 1
        region_height = bounds["max_z"] - bounds["min_z"] + 1
        full_width = region_width * 32 * 16
        full_height = region_height * 32 * 16
        width = full_width // scale
        height = full_height // scale
        max_dimension = 32768
        if width > max_dimension or height > max_dimension:
            needed_scale = max(
                full_width // max_dimension + 1,
                full_height // max_dimension + 1,
            )
            raise ValueError(
                f"图像尺寸过大 ({width}x{height})，超出限制 ({max_dimension}px)。"
                f"请将缩放比例调整为至少 1:{needed_scale}"
            )
        estimated_mb = width * height * 3 / (1024 * 1024)
        if estimated_mb > 2048:
            raise ValueError(
                f"预计图像内存占用约 {estimated_mb:.0f} MB，"
                "超出安全限制 (2048 MB)。请增大缩放比例以减小图像尺寸"
            )
        return MapImageSpec(width, height, estimated_mb)

    def _render_regions(
        self,
        image: Any,
        region_files: List[Path],
        bounds: Dict[str, int],
        map_type: str,
        scale: int,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        from core.mca import NativeRegion

        pixels = image.load()
        total = len(region_files)
        for index, region_file in enumerate(region_files):
            progress(
                0.25 + (index / total) * 0.70,
                f"渲染区块 {index + 1}/{total}",
            )
            try:
                coords = parse_region_coords(region_file)
                if coords is None:
                    continue
                region_x, region_z = coords
                with NativeRegion.from_file(region_file) as region:
                    self._render_region_chunks(
                        image,
                        pixels,
                        region,
                        region_x,
                        region_z,
                        bounds,
                        map_type,
                        scale,
                    )
            except Exception as exc:
                log(f"处理区块文件 {region_file.name} 失败: {exc}", "WARNING")

    def _render_region_chunks(
        self,
        image: Any,
        pixels: Any,
        region: Any,
        region_x: int,
        region_z: int,
        bounds: Dict[str, int],
        map_type: str,
        scale: int,
    ) -> None:
        for chunk_x in range(32):
            for chunk_z in range(32):
                try:
                    chunk = region.get_chunk(chunk_x, chunk_z)
                    if chunk is not None:
                        self._render_chunk(
                            image,
                            chunk,
                            region_x,
                            region_z,
                            chunk_x,
                            chunk_z,
                            bounds,
                            map_type,
                            scale,
                            pixels,
                        )
                except Exception:
                    continue

    @staticmethod
    def draw_fallback_grid(image: Any, scale: int) -> None:
        draw = ImageDraw.Draw(image)
        step = max(1, 16 // scale)
        for offset in range(0, image.width, step):
            draw.line(
                [(offset, 0), (offset, image.height)],
                fill=(200, 200, 200),
                width=1,
            )
        for offset in range(0, image.height, step):
            draw.line(
                [(0, offset), (image.width, offset)],
                fill=(200, 200, 200),
                width=1,
            )

    def _render_chunk(
        self,
        image: Any,
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
                        y = self.highest_block_y(chunk, bx, bz)
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

    def highest_block_y(self, chunk: Any, x: int, z: int) -> Optional[int]:
        try:
            surface_y = self._native_surface_y(chunk, x, z)
            if surface_y is not None:
                return surface_y
            return self._scan_highest_block(
                chunk,
                self._get_non_air_sections(chunk),
                x,
                z,
            )
        except Exception:
            return None

    @staticmethod
    def _native_surface_y(chunk: Any, x: int, z: int) -> Optional[int]:
        blocks = getattr(chunk, "_blocks", None)
        if blocks is None or not hasattr(blocks, "surface_y"):
            return None
        value = blocks.surface_y(x, z)
        return int(value) if value is not None else None

    @staticmethod
    def _get_non_air_sections(chunk: Any) -> List[int]:
        cache_attr = "_mcsh_non_air_sections"
        cached = getattr(chunk, cache_attr, None)
        if isinstance(cached, list):
            return [int(section) for section in cached]
        try:
            from core.mca import section_range_for_chunk
            section_range = section_range_for_chunk(chunk)
        except Exception:
            section_range = range(-4, 20)
        sections = []
        for section_y in reversed(list(section_range)):
            try:
                palette = chunk.get_palette(section_y)
                if palette and any(
                    block is not None
                    and not str(getattr(block, "id", "")).endswith("air")
                    for block in palette
                ):
                    sections.append(section_y)
            except Exception:
                continue
        try:
            setattr(chunk, cache_attr, sections)
        except Exception:
            pass
        return sections

    @staticmethod
    def _scan_highest_block(
        chunk: Any,
        sections: List[int],
        x: int,
        z: int,
    ) -> Optional[int]:
        for section_y in sections:
            y_start = section_y * 16
            for y in range(y_start + 15, y_start - 1, -1):
                try:
                    block = chunk.get_block(x, y, z)
                    block_id = str(getattr(block, "id", ""))
                    if block and not block_id.endswith("air"):
                        return y
                except Exception:
                    continue
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
                color: Tuple[int, int, int] = self.BLOCK_COLORS[block_name]
            else:
                color = self._generate_color_from_name(block_name)

            # 地形图：根据高度调整亮度
            if map_type == "terrain":
                factor = (y + 64) / 383.0  # 归一化到 [0, 1]
                scale_factor = 0.5 + factor * 0.5
                color = (
                    int(color[0] * scale_factor),
                    int(color[1] * scale_factor),
                    int(color[2] * scale_factor),
                )

            return color

        except Exception:
            return (128, 128, 128)  # 默认灰色

    def _generate_color_from_name(
            self, block_name: str) -> Tuple[int, int, int]:
        h = hashlib.md5(block_name.encode("utf-8")).digest()
        return (h[0], h[1], h[2])
