"""区域地图服务共享类型。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass
class ScanProgress:
    """扫描进度信息"""
    total_files: int = 0
    scanned_files: int = 0
    progress: float = 0.0  # 0.0 到 1.0
    is_scanning: bool = False
    error: Optional[str] = None


class TopviewTilePhase(str, Enum):
    """Lifecycle phase for one topview tile request."""

    EMPTY = "empty"
    LOADING = "loading"
    READY = "ready"
    UPGRADING = "upgrading"
    FAILED = "failed"


class TopviewTileIntegrity(str, Enum):
    """Whether the available PNG covers every requested source chunk."""

    UNKNOWN = "unknown"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class TopviewTileState:
    """Consistent service snapshot for one progressive topview tile.

    Args:
        generation: Owning map generation.
        revision: Monotonic PNG revision in that service instance.
        available_size: Edge length of the currently published PNG.
        requested_size: Highest queued or running edge length.
        failed_size: Largest source-incomplete size under retry suppression.
        processed_chunks: Number of chunks handled by the active request.
        total_chunks: Total chunks in the active progressive request.
        integrity: Completeness of the published source data.
    """

    generation: int
    revision: int = 0
    available_size: int = 0
    requested_size: int = 0
    failed_size: int = 0
    processed_chunks: int = 0
    total_chunks: int = 0
    integrity: TopviewTileIntegrity = TopviewTileIntegrity.UNKNOWN

    @property
    def phase(self) -> TopviewTilePhase:
        """Return the lifecycle phase without conflating source integrity."""
        if self.available_size > 0:
            if self.requested_size > self.available_size:
                return TopviewTilePhase.UPGRADING
            return TopviewTilePhase.READY
        if self.requested_size > 0:
            return TopviewTilePhase.LOADING
        if self.failed_size > 0:
            return TopviewTilePhase.FAILED
        return TopviewTilePhase.EMPTY

    @property
    def is_pending(self) -> bool:
        """Return whether the current generation owns queued or running work."""
        return self.requested_size > 0

    @property
    def is_progressive_upgrade(self) -> bool:
        """Return whether a coarse tile remains usable during a finer request."""
        return self.phase is TopviewTilePhase.UPGRADING

    @property
    def progress(self) -> float:
        """Return active chunk progress in the inclusive range 0..1."""
        if self.total_chunks <= 0:
            return 0.0
        return min(1.0, max(0.0, self.processed_chunks / self.total_chunks))

    def is_usable(self, min_size: int = 0) -> bool:
        """Return whether the available tile satisfies an LOD request.

        Args:
            min_size: Required edge length; zero accepts any available LOD.

        Returns:
            Whether the tile is large enough and not awaiting a damage retry.
        """
        if self.available_size <= 0:
            return False
        if (
            self.integrity is TopviewTileIntegrity.INCOMPLETE
            and self.failed_size < self.available_size
        ):
            return False
        return self.available_size >= max(0, int(min_size))


__all__ = [
    "ScanProgress",
    "TopviewTileIntegrity",
    "TopviewTilePhase",
    "TopviewTileState",
]
