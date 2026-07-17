"""Compatibility facade for the region editor now owned by ``core.mca``."""
from typing import Optional

from core.mca.editor import ChunkInfo, RegionEditor, RegionInfo
from core.types import LogCallback

RegionEditorService = RegionEditor


def get_region_editor_service(
    log: Optional[LogCallback] = None,
) -> RegionEditorService:
    """Return an editor scoped to the caller instead of shared global state."""
    return RegionEditorService(log=log)


__all__ = [
    "ChunkInfo",
    "RegionEditorService",
    "RegionInfo",
    "get_region_editor_service",
]
