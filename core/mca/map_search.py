"""地图坐标和标记的统一搜索解析。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

from .map_models import MapMarker


MapSearchKind = Literal["block", "chunk", "region", "marker"]
MapSearchErrorCode = Literal["empty", "invalid_format", "not_found"]
_INTEGER = r"[+-]?\d+"
_BLOCK_XZ_RE = re.compile(rf"^({_INTEGER})\s*,\s*({_INTEGER})$")
_BLOCK_XYZ_RE = re.compile(rf"^({_INTEGER})\s+({_INTEGER})\s+({_INTEGER})$")
_REGION_RE = re.compile(rf"^r\.({_INTEGER})\.({_INTEGER})$", re.IGNORECASE)
_CHUNK_RE = re.compile(rf"^c\.({_INTEGER})\.({_INTEGER})$", re.IGNORECASE)


class MapSearchError(ValueError):
    """搜索内容为空、格式无效或没有匹配结果。"""

    def __init__(
        self,
        message: str,
        code: MapSearchErrorCode = "invalid_format",
        query: str = "",
    ) -> None:
        """地图搜索错误，携带人类可读消息。"""
        super().__init__(message)
        self.code = code
        self.query = query


@dataclass(frozen=True)
class MapSearchResult:
    """一次地图搜索命中的方块坐标或标记。"""

    kind: MapSearchKind
    x: int
    z: int
    y: int | None = None
    label: str = ""
    marker_id: str | None = None


def parse_map_query(
    query: str,
    markers: Iterable[MapMarker] = (),
    dimension_id: str | None = None,
) -> list[MapSearchResult]:
    """解析坐标表达式，或按名称查找当前维度的标记。

    坐标表达式优先于标记名称。区域和区块坐标会转换为相应单元格
    的中心方块坐标，便于调用方直接将地图视口移动到结果位置。
    """
    if not isinstance(query, str) or not query.strip():
        raise MapSearchError("搜索内容不能为空", code="empty")

    text = query.strip()
    coordinate = _parse_coordinate(text)
    if coordinate is not None:
        return [coordinate]

    normalized = text.casefold()
    matches = [
        (index, marker)
        for index, marker in enumerate(markers)
        if (dimension_id is None or marker.dimension_id == dimension_id)
        and normalized in marker.name.casefold()
    ]
    if matches:
        matches.sort(
            key=lambda item: (
                item[1].name.casefold() != normalized,
                item[1].name.casefold(),
                item[1].x * item[1].x + item[1].z * item[1].z,
            )
        )
        return [
            MapSearchResult(
                kind="marker",
                x=marker.x,
                y=marker.y,
                z=marker.z,
                label=marker.name,
                marker_id=marker.id,
            )
            for _index, marker in matches
        ]

    if "," in text or text.lower().startswith(("r.", "c.")):
        raise MapSearchError(
            "坐标格式无效，请输入 x,z、x y z、r.rx.rz 或 c.cx.cz",
            code="invalid_format",
            query=text,
        )
    raise MapSearchError(
        f"未找到名称包含“{text}”的地图标记",
        code="not_found",
        query=text,
    )


def _parse_coordinate(text: str) -> MapSearchResult | None:
    block_xz = _BLOCK_XZ_RE.fullmatch(text)
    if block_xz is not None:
        x, z = (int(value) for value in block_xz.groups())
        return MapSearchResult(kind="block", x=x, z=z)

    block_xyz = _BLOCK_XYZ_RE.fullmatch(text)
    if block_xyz is not None:
        x, y, z = (int(value) for value in block_xyz.groups())
        return MapSearchResult(kind="block", x=x, y=y, z=z)

    region = _REGION_RE.fullmatch(text)
    if region is not None:
        region_x, region_z = (int(value) for value in region.groups())
        return MapSearchResult(
            kind="region",
            x=region_x * 512 + 256,
            z=region_z * 512 + 256,
        )

    chunk = _CHUNK_RE.fullmatch(text)
    if chunk is not None:
        chunk_x, chunk_z = (int(value) for value in chunk.groups())
        return MapSearchResult(
            kind="chunk",
            x=chunk_x * 16 + 8,
            z=chunk_z * 16 + 8,
        )

    return None
