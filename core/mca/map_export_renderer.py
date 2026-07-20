"""PIL renderer for exported Minecraft region maps."""
from __future__ import annotations

import hashlib
import threading
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


@dataclass(frozen=True)
class _ChunkRenderContext:
    image: Any
    pixels: Any
    chunk: Any
    block_bounds: Tuple[int, int, int, int]
    map_type: str
    scale: int


class MapRenderCancelled(Exception):
    """地图渲染被调用方取消。"""


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
    def __init__(self) -> None:
        self.last_rendered_chunks = 0

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
        *,
        block_bounds: Optional[Tuple[int, int, int, int]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Any:
        """创建地图图像

        Args:
            region_files: 区块文件列表
            bounds: inclusive region 坐标范围
            map_type: 地图类型
            scale: 缩放比例
            log: 日志回调
            progress: 进度回调
            block_bounds: 可选的 inclusive 方块裁剪范围
            cancel_event: 可选的取消事件

        Returns:
            PIL 图像对象
        """
        self._raise_if_cancelled(cancel_event)
        if not PIL_AVAILABLE:
            raise ImportError("需要安装 Pillow 库才能导出地图")
        normalized_block_bounds = self._normalize_block_bounds(
            block_bounds,
            bounds,
        )
        spec = self.calculate_image_spec(
            bounds,
            scale,
            block_bounds=block_bounds,
        )
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
        self.last_rendered_chunks = 0
        try:
            try:
                self.last_rendered_chunks = self._render_regions(
                    image,
                    region_files,
                    bounds,
                    map_type,
                    scale,
                    log,
                    progress,
                    block_bounds=normalized_block_bounds,
                    cancel_event=cancel_event,
                )
            except ImportError:
                log("地图渲染后端不可用，使用简化渲染", "WARNING")
                self.draw_fallback_grid(image, scale)
            if self.last_rendered_chunks == 0:
                raise ValueError("所有 MCA 文件均不可读或不包含可渲染区块")
            self._raise_if_cancelled(cancel_event)
        except Exception:
            try:
                image.close()
            except Exception:
                # best-effort: never mask the original render error
                pass
            raise
        return image

    @staticmethod
    def calculate_image_spec(
        bounds: Dict[str, int],
        scale: int,
        *,
        block_bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> MapImageSpec:
        """计算导出图像尺寸与预估内存。

        Args:
            bounds: inclusive region 坐标范围。
            scale: 正整数缩放比例（方块像素合并）。
            block_bounds: 可选 inclusive 方块裁剪范围。

        Returns:
            MapImageSpec: 宽高与预估 MB。

        Raises:
            ValueError: 缩放/范围非法，或尺寸/内存超限。
        """
        if not isinstance(scale, int) or isinstance(scale, bool) or scale <= 0:
            raise ValueError("缩放比例必须是正整数")
        if block_bounds is None:
            region_width = bounds["max_x"] - bounds["min_x"] + 1
            region_height = bounds["max_z"] - bounds["min_z"] + 1
            full_width = region_width * 32 * 16
            full_height = region_height * 32 * 16
            width = full_width // scale
            height = full_height // scale
        else:
            min_x, min_z, max_x, max_z = block_bounds
            if max_x < min_x or max_z < min_z:
                raise ValueError("方块范围无效")
            full_width = max_x - min_x + 1
            full_height = max_z - min_z + 1
            width = (full_width + scale - 1) // scale
            height = (full_height + scale - 1) // scale
        max_dimension = 32768
        if width > max_dimension or height > max_dimension:
            needed_scale = max(
                full_width // max_dimension + 1,
                full_height // max_dimension + 1,
            )
            raise ValueError(
                f"图像尺寸过大 ({width}x{height})，超出限制 "
                f"({max_dimension}px)。请将缩放比例调整为至少 1:{needed_scale}"
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
        *,
        block_bounds: Tuple[int, int, int, int],
        cancel_event: Optional[threading.Event],
    ) -> int:
        from core.mca import NativeRegion

        pixels = image.load()
        total = len(region_files)
        rendered_chunks = 0
        for index, region_file in enumerate(region_files):
            self._raise_if_cancelled(cancel_event)
            progress(
                0.25 + (index / max(total, 1)) * 0.70,
                f"渲染区块 {index + 1}/{total}",
            )
            try:
                coords = parse_region_coords(region_file)
                if coords is None:
                    continue
                region_x, region_z = coords
                with NativeRegion.from_file(region_file) as region:
                    rendered_chunks += self._render_region_chunks(
                        image,
                        pixels,
                        region,
                        region_x,
                        region_z,
                        bounds,
                        map_type,
                        scale,
                        block_bounds=block_bounds,
                        cancel_event=cancel_event,
                    )
            except MapRenderCancelled:
                raise
            except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
                log(
                    f"处理区块文件 {region_file.name} 失败: {exc}",
                    "WARNING",
                )
            except Exception as exc:
                # Region/MCA libraries may raise package-specific errors.
                log(
                    f"处理区块文件 {region_file.name} 失败: {exc}",
                    "WARNING",
                )
        return rendered_chunks

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
        *,
        block_bounds: Tuple[int, int, int, int],
        cancel_event: Optional[threading.Event],
    ) -> int:
        rendered_chunks = 0
        try:
            coordinates = region.iter_present_chunks()
        except AttributeError:
            coordinates = (
                (chunk_x, chunk_z)
                for chunk_x in range(32)
                for chunk_z in range(32)
            )
        for chunk_x, chunk_z in coordinates:
            self._raise_if_cancelled(cancel_event)
            chunk_min_x = region_x * 512 + chunk_x * 16
            chunk_min_z = region_z * 512 + chunk_z * 16
            min_x, min_z, max_x, max_z = block_bounds
            if (
                chunk_min_x + 15 < min_x
                or chunk_min_x > max_x
                or chunk_min_z + 15 < min_z
                or chunk_min_z > max_z
            ):
                continue
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
                        block_bounds=block_bounds,
                        cancel_event=cancel_event,
                    )
                    rendered_chunks += 1
            except MapRenderCancelled:
                raise
            except (OSError, ValueError, TypeError, RuntimeError, KeyError):
                continue
        return rendered_chunks

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
        *,
        block_bounds: Optional[Tuple[int, int, int, int]] = None,
        cancel_event: Optional[threading.Event] = None,
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
            pixel_access = pixels if pixels is not None else image.load()
            bounds_value = block_bounds or self._normalize_block_bounds(None, bounds)
            self._render_chunk_columns(
                _ChunkRenderContext(
                    image=image,
                    pixels=pixel_access,
                    chunk=chunk,
                    block_bounds=bounds_value,
                    map_type=map_type,
                    scale=scale,
                ),
                rx,
                rz,
                cx,
                cz,
                cancel_event,
            )

        except MapRenderCancelled:
            raise
        except (OSError, ValueError, TypeError, RuntimeError, KeyError, IndexError):
            # 跳过损坏的区块数据
            return

    def _render_chunk_columns(
        self,
        context: _ChunkRenderContext,
        rx: int,
        rz: int,
        cx: int,
        cz: int,
        cancel_event: Optional[threading.Event],
    ) -> None:
        origin_x, origin_z, max_x, max_z = context.block_bounds
        world_chunk_x, world_chunk_z = rx * 32 + cx, rz * 32 + cz
        for block_x in range(16):
            self._raise_if_cancelled(cancel_event)
            world_x = world_chunk_x * 16 + block_x
            if not origin_x <= world_x <= max_x:
                continue
            for block_z in range(16):
                world_z = world_chunk_z * 16 + block_z
                if not origin_z <= world_z <= max_z:
                    continue
                try:
                    height = self.highest_block_y(
                        context.chunk,
                        block_x,
                        block_z,
                    )
                    if height is None:
                        continue
                    block = context.chunk.get_block(block_x, height, block_z)
                    color = self._get_block_color(block, height, context.map_type)
                    pixel_x = (world_x - origin_x) // context.scale
                    pixel_z = (world_z - origin_z) // context.scale
                    if (
                        0 <= pixel_x < context.image.width
                        and 0 <= pixel_z < context.image.height
                    ):
                        context.pixels[pixel_x, pixel_z] = color
                except (
                    OSError,
                    ValueError,
                    TypeError,
                    RuntimeError,
                    KeyError,
                    IndexError,
                    AttributeError,
                ):
                    continue

    @staticmethod
    def _raise_if_cancelled(
        cancel_event: Optional[threading.Event],
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise MapRenderCancelled("地图导出已取消")

    @staticmethod
    def _normalize_block_bounds(
        block_bounds: Optional[Tuple[int, int, int, int]],
        region_bounds: Dict[str, int],
    ) -> Tuple[int, int, int, int]:
        if block_bounds is not None:
            if len(block_bounds) != 4:
                raise ValueError("方块范围必须包含四个坐标")
            min_x, min_z, max_x, max_z = (
                int(block_bounds[0]),
                int(block_bounds[1]),
                int(block_bounds[2]),
                int(block_bounds[3]),
            )
        else:
            min_x = int(region_bounds["min_x"]) * 512
            min_z = int(region_bounds["min_z"]) * 512
            max_x = (int(region_bounds["max_x"]) + 1) * 512 - 1
            max_z = (int(region_bounds["max_z"]) + 1) * 512 - 1
        if max_x < min_x or max_z < min_z:
            raise ValueError("方块范围无效")
        return min_x, min_z, max_x, max_z

    def highest_block_y(self, chunk: Any, x: int, z: int) -> Optional[int]:
        """Return the highest non-air block Y for column ``(x, z)``."""
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
        except (OSError, ValueError, TypeError, RuntimeError, AttributeError):
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
        """List section indices that contain at least one non-air palette entry."""
        cache_attr = "_mcsh_non_air_sections"
        cached = getattr(chunk, cache_attr, None)
        if isinstance(cached, list):
            return [int(section) for section in cached]
        try:
            from core.mca import section_range_for_chunk
            section_range = section_range_for_chunk(chunk)
        except (ImportError, TypeError, ValueError, AttributeError):
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
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
        try:
            setattr(chunk, cache_attr, sections)
        except (AttributeError, TypeError):
            pass
        return sections

    @staticmethod
    def _scan_highest_block(
        chunk: Any,
        sections: List[int],
        x: int,
        z: int,
    ) -> Optional[int]:
        """Scan section columns from top to bottom for the first solid block."""
        for section_y in sections:
            y_start = section_y * 16
            for y in range(y_start + 15, y_start - 1, -1):
                try:
                    block = chunk.get_block(x, y, z)
                    block_id = str(getattr(block, "id", ""))
                    if block and not block_id.endswith("air"):
                        return y
                except (
                    OSError,
                    ValueError,
                    TypeError,
                    KeyError,
                    IndexError,
                    AttributeError,
                ):
                    continue
        return None

    def _get_block_color(
        self,
        block: Any,
        y: int,
        map_type: str,
    ) -> Tuple[int, int, int]:
        """获取方块颜色。

        Args:
            block: 方块对象。
            y: Y 坐标。
            map_type: 地图类型（``terrain`` 时按高度调亮度）。

        Returns:
            RGB 颜色元组；失败时返回中性灰。
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
        except (AttributeError, TypeError, ValueError, KeyError):
            return (128, 128, 128)

    def _generate_color_from_name(
        self,
        block_name: str,
    ) -> Tuple[int, int, int]:
        """Derive a stable pseudo-random RGB color from a block name."""
        digest = hashlib.md5(block_name.encode("utf-8")).digest()
        return (digest[0], digest[1], digest[2])
