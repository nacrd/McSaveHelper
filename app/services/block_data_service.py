"""Compatibility facade for the core Minecraft block-state service."""
from core.mca.block_data_service import (
    BlockDataService,
    BlockStateInfo,
    SetBlockResult,
)

__all__ = [
    "BlockDataService",
    "BlockStateInfo",
    "SetBlockResult",
    "get_block_data_service",
]


def get_block_data_service() -> BlockDataService:
    """Return an isolated block-state cache for one editing workflow."""
    return BlockDataService()
