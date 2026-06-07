"""纯净扫描模块

移除存档中所有模组相关的方块和实体，让模组存档能够“无损”降级回原版服务端运行。
"""
import nbtlib
import anvil
from pathlib import Path
from typing import Optional, Tuple, List

from .scanner import scan_all_regions
from .types import LogCallback


def is_vanilla_id(identifier: str) -> bool:
    """判断是否为原版ID（以 minecraft: 开头）"""
    return identifier.startswith("minecraft:")


def purge_mod_blocks_and_entities(world_path: Path, log: LogCallback) -> None:
    """从世界存档中移除所有模组相关的方块和实体

    Args:
        world_path: 世界存档路径
        log: 日志回调函数
    """
    log("开始纯净扫描：移除模组方块和实体", "PURE")
    region_files = scan_all_regions(world_path)
    total_regions = len(region_files)
    if total_regions == 0:
        log("未找到任何区域文件，跳过纯净扫描", "INFO")
        return

    total_chunks = 0
    total_blocks_replaced = 0
    total_entities_removed = 0

    for idx, region_file in enumerate(region_files, start=1):
        log(f"处理区域文件 ({idx}/{total_regions}): {region_file.name}", "INFO")
        try:
            region = anvil.Region.from_file(str(region_file))
            region_changes = 0
            region_entities = 0
            for x in range(32):
                for z in range(32):
                    chunk = region.get_chunk(x, z)
                    if chunk is None:
                        continue
                    total_chunks += 1
                    # 一次遍历处理方块、实体和方块实体
                    blocks_replaced, entities_removed = _purge_mod_data_in_chunk(chunk)
                    total_blocks_replaced += blocks_replaced
                    total_entities_removed += entities_removed
                    if blocks_replaced > 0 or entities_removed > 0:
                        region_changes += 1
            if region_changes > 0:
                region.save(str(region_file))  # type: ignore[attr-defined]
                log(f"  保存修改: {region_changes} 个区块受影响", "INFO")
        except Exception as e:
            log(f"处理区域文件失败 {region_file.name}: {e}", "ERROR")

    log("纯净扫描完成", "PURE")
    log(f"总计扫描 {total_chunks} 个区块", "INFO")
    log(f"替换了 {total_blocks_replaced} 个模组方块", "INFO")
    log(f"移除了 {total_entities_removed} 个模组实体", "INFO")


def _purge_mod_data_in_chunk(chunk) -> Tuple[int, int]:
    """单次遍历移除模组方块、实体和方块实体，返回 (替换方块数, 移除实体数)"""
    data = chunk.data if hasattr(chunk, 'data') else chunk
    if not isinstance(data, nbtlib.tag.Compound):
        return 0, 0

    blocks_replaced = 0
    entities_removed = 0

    # 1. 处理方块 palette
    sections = data.get('sections')
    if sections:
        for section in sections:
            palette = section.get('palette')
            if not palette:
                continue
            for block_state in palette:
                block_id = block_state.get('Name')
                if not isinstance(block_id, nbtlib.tag.String):
                    continue
                if not is_vanilla_id(str(block_id)):
                    block_state['Name'] = nbtlib.tag.String('minecraft:air')
                    if 'Properties' in block_state:
                        del block_state['Properties']
                    blocks_replaced += 1

    # 2. 处理实体
    entities_key = 'Entities' if 'Entities' in data else 'entities'
    entities = data.get(entities_key)
    if entities:
        vanilla_entities = []
        for entity in entities:
            entity_id = entity.get('id')
            if not isinstance(entity_id, nbtlib.tag.String):
                vanilla_entities.append(entity)
                continue
            if is_vanilla_id(str(entity_id)):
                vanilla_entities.append(entity)
            else:
                entities_removed += 1
        if entities_removed > 0:
            data[entities_key] = nbtlib.tag.List(vanilla_entities)

    # 3. 处理方块实体
    for key in ('block_entities', 'BlockEntities', 'TileEntities'):
        block_entities = data.get(key)
        if not block_entities:
            continue
        key_removed = 0
        vanilla_block_entities = []
        for block_entity in block_entities:
            block_entity_id = block_entity.get('id')
            if not isinstance(block_entity_id, nbtlib.tag.String):
                vanilla_block_entities.append(block_entity)
                continue
            if is_vanilla_id(str(block_entity_id)):
                vanilla_block_entities.append(block_entity)
            else:
                key_removed += 1
        if key_removed > 0:
            data[key] = nbtlib.tag.List(vanilla_block_entities)
            entities_removed += key_removed

    return blocks_replaced, entities_removed


def _purge_mod_blocks_in_chunk(chunk) -> int:
    """从单个区块中移除模组方块，返回替换的方块数量"""
    # 注意：chunk 可能是 anvil.Chunk 对象，也可能是 nbtlib.tag.Compound
    # 这里我们假设它是 anvil.Chunk，拥有 data 属性
    data = chunk.data if hasattr(chunk, 'data') else chunk
    if not isinstance(data, nbtlib.tag.Compound):
        return 0

    # 检测 Minecraft 版本，不同版本的数据结构不同
    # 1.13+ 使用 "sections" 和 "palette"
    # 更早版本使用 "Blocks"、"Data" 等，但现代模组存档通常是 1.12+
    # 我们仅支持 1.13+ 的区块格式
    sections = data.get('sections')
    if not sections:
        return 0

    replaced = 0
    for section in sections:
        # 每个 section 是一个复合标签，包含 "palette" 和 "block_states"
        palette = section.get('palette')
        if not palette:
            continue
        # 遍历调色板中的每个方块状态
        for i, block_state in enumerate(palette):
            block_id = block_state.get('Name')
            if not isinstance(block_id, nbtlib.tag.String):
                continue
            id_str = str(block_id)
            if not is_vanilla_id(id_str):
                # 替换为空气
                block_state['Name'] = nbtlib.tag.String('minecraft:air')
                # 可选：清除其他属性
                if 'Properties' in block_state:
                    del block_state['Properties']
                replaced += 1
    return replaced


def _purge_mod_entities_in_chunk(chunk) -> int:
    """从单个区块中移除模组实体，返回移除的实体数量"""
    data = chunk.data if hasattr(chunk, 'data') else chunk
    if not isinstance(data, nbtlib.tag.Compound):
        return 0

    entities_key = 'Entities' if 'Entities' in data else 'entities'
    entities = data.get(entities_key)
    if not entities:
        return 0

    vanilla_entities = []
    removed = 0
    for entity in entities:
        entity_id = entity.get('id')
        if not isinstance(entity_id, nbtlib.tag.String):
            continue
        id_str = str(entity_id)
        if is_vanilla_id(id_str):
            vanilla_entities.append(entity)
        else:
            removed += 1
    # 替换实体列表
    if removed > 0:
        data[entities_key] = nbtlib.tag.List(vanilla_entities)
    return removed


def _purge_mod_block_entities_in_chunk(chunk) -> int:
    """Remove non-vanilla block entities left behind by modded blocks."""
    data = chunk.data if hasattr(chunk, 'data') else chunk
    if not isinstance(data, nbtlib.tag.Compound):
        return 0

    removed = 0
    for key in ('block_entities', 'BlockEntities', 'TileEntities'):
        block_entities = data.get(key)
        if not block_entities:
            continue
        key_removed = 0
        vanilla_block_entities = []
        for block_entity in block_entities:
            block_entity_id = block_entity.get('id')
            if not isinstance(block_entity_id, nbtlib.tag.String):
                vanilla_block_entities.append(block_entity)
                continue
            if is_vanilla_id(str(block_entity_id)):
                vanilla_block_entities.append(block_entity)
            else:
                key_removed += 1
        if key_removed > 0:
            data[key] = nbtlib.tag.List(vanilla_block_entities)
            removed += key_removed
    return removed
